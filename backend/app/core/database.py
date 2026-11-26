"""Async engine, session factory and declarative base re-export."""

from __future__ import annotations

import asyncio
import ssl
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

import asyncpg

import sqlalchemy.exc
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger("sbdma.db")

_settings = get_settings()


def _ssl_context_for(sslmode: str) -> ssl.SSLContext:
    """Give ``sslmode`` the meaning libpq gives it.

    asyncpg's ``ssl=True`` means *verify fully*, which is stricter than libpq's
    ``sslmode=require`` — the level managed providers (Supabase, Neon, RDS in some
    modes) document. Mapping the two as equal makes the app fail the handshake with
    "self-signed certificate in certificate chain": the traffic was meant to be
    encrypted, not certified.

    ``verify-full`` is the level worth using wherever the provider's chain is
    publicly trusted, and it maps to a fully verifying context.
    """
    context = ssl.create_default_context()
    if sslmode == "require":
        # encrypt, do not verify — libpq's meaning of "require"
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    elif sslmode == "verify-ca":
        # verify the chain, allow a hostname mismatch (pooler domains)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_REQUIRED
    return context


def engine_url_and_connect_args(database_url: str) -> tuple[str, dict]:
    """Translate libpq-style query parameters SQLAlchemy's asyncpg driver rejects.

    Managed PostgreSQL documents its connection string as ``?sslmode=require`` — that
    is the libpq spelling, understood by psycopg (Alembic's driver) but **not** by
    asyncpg, which takes ``ssl=`` instead. SQLAlchemy passes unknown query parameters
    straight into ``asyncpg.connect``, so the app died at startup with
    ``TypeError: connect() got an unexpected keyword argument 'sslmode'`` — the kind
    of failure that only appears against a real managed database, never against a
    local one.

    The parameter is therefore moved out of the URL and expressed in the driver's own
    vocabulary. ``sslmode=prefer`` (libpq's default) needs no argument at all.
    """
    url = make_url(database_url)
    query = dict(url.query)
    connect_args: dict = {}

    sslmode = query.pop("sslmode", None)
    if sslmode in {"require", "verify-ca", "verify-full"}:
        connect_args["ssl"] = _ssl_context_for(sslmode)
    elif sslmode == "disable":
        connect_args["ssl"] = False

    # Transaction-mode poolers (pgbouncer / Supavisor on :6543) cannot keep prepared
    # statements between transactions; asyncpg's cache has to be turned off there.
    if str(query.pop("prepared_statements", "")).lower() in {"0", "false"}:
        connect_args.update(prepared_statement_cache_size=0, statement_cache_size=0)
    # Neon's spelling of the same condition, and not a keyword asyncpg understands
    pgbouncer = str(query.pop("pgbouncer", "")).lower() in {"1", "true"}

    # A transaction-mode pooler cannot keep prepared statements: the server-side name
    # outlives the client that created it, and the next client's prepare collides
    # (`DuplicatePreparedStatementError` → 503 on a healthy database). The port is the
    # one unambiguous signal — :6543 is Supavisor/pgbouncer transaction mode, and
    # `?pgbouncer=true` is Neon's spelling of the same thing — so it is honoured even
    # when the setting says otherwise: a flag that can be wrong must not outrank the URL.
    pooled = url.port == 6543 or pgbouncer
    if _settings.db_disable_prepared_statements or pooled:
        connect_args.update(prepared_statement_cache_size=0, statement_cache_size=0)

    cleaned = url.set(query=query)
    return cleaned.render_as_string(hide_password=False), connect_args


_engine_url, _connect_args = engine_url_and_connect_args(_settings.database_url)

engine = create_async_engine(
    _engine_url,
    echo=False,
    pool_size=_settings.db_pool_size,
    max_overflow=_settings.db_max_overflow,
    pool_recycle=_settings.db_pool_recycle_seconds,
    pool_pre_ping=True,
    connect_args=_connect_args,
)

SessionFactory = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
)


#: Connection failures that mean "try again in a moment", not "this request is broken".
#: A managed pooler refuses a connection when it is momentarily at its client limit
#: (Supavisor answers exactly this way), and a cold function's first TLS handshake can
#: time out. Both succeed on the next attempt; surfacing them as 503 tells a user reading
#: the letterhead that the laboratory is down when it is not.
TRANSIENT_CONNECT_ERRORS: tuple[type[BaseException], ...] = (
    asyncio.TimeoutError,
    ConnectionError,
    OSError,
    # asyncpg's own connection-level family (ConnectionDoesNotExistError,
    # ConnectionFailureError, …) rather than a hand-picked few
    asyncpg.exceptions.PostgresConnectionError,
    asyncpg.exceptions.CannotConnectNowError,
    asyncpg.exceptions.TooManyConnectionsError,
    asyncpg.exceptions.InterfaceError,
    # SQLAlchemy wraps every driver error, so the *driver's* exception type never
    # reaches this code: a refused handshake arrives as OperationalError, and the
    # first version of this retry therefore never fired once — it caught types that
    # the session could not raise. ProgrammingError and IntegrityError are deliberately
    # absent: a broken statement or a constraint violation is not a hiccup.
    sqlalchemy.exc.DisconnectionError,
    sqlalchemy.exc.InterfaceError,
    sqlalchemy.exc.OperationalError,
)

#: 4 attempts, 100 ms → 300 ms → 900 ms. Long enough to ride out a pooler hiccup
#: (the observed refusals last well under a second), short enough that a genuinely
#: unreachable database still fails inside the platform's request timeout.
CONNECT_ATTEMPTS = 4
CONNECT_BACKOFF_SECONDS = 0.1


async def connect_with_retry(session: AsyncSession, *, attempts: int = CONNECT_ATTEMPTS) -> None:
    """Acquire the session's connection, retrying transient failures.

    The connection is acquired once, explicitly, and reused by every query in the
    request — so the retry costs nothing on the happy path and cannot multiply work.
    """
    delay = CONNECT_BACKOFF_SECONDS
    for attempt in range(1, attempts + 1):
        try:
            await session.connection()
            return
        except TRANSIENT_CONNECT_ERRORS as exc:
            if attempt == attempts:
                log.error(
                    "database connection failed",
                    extra={"extra_fields": {"attempts": attempt, "error": str(exc)}},
                )
                raise
            log.warning(
                "database connection refused, retrying",
                extra={"extra_fields": {"attempt": attempt, "error": str(exc)}},
            )
            await asyncio.sleep(delay)
            delay *= 3


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Transactional scope: commits on success, rolls back on any exception."""
    async with SessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency. The router layer commits through the service layer."""
    async with SessionFactory() as session:
        try:
            await connect_with_retry(session)
            yield session
        except Exception:
            # A session whose connection was never established has nothing to roll back;
            # asking it to would raise a second, less informative error over the first.
            with suppress(Exception):
                await session.rollback()
            raise


async def _ping_once() -> None:
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def ping(attempts: int = CONNECT_ATTEMPTS) -> bool:
    """Answer whether the database is *actually* down, not whether one handshake failed.

    ``/health`` flapped ``postgresql: down`` → ``up`` on the same minute the API served
    every request: each flap was a single refused handshake at the pooler. A health check
    that cries outage on the first refusal trains people to ignore it, so — exactly like a
    request — it retries the transient kind and reports a failure only when the connection
    cannot be made at all. A non-transient error (bad credentials, missing database) is
    still reported immediately: retrying it would only hide it.
    """
    delay = CONNECT_BACKOFF_SECONDS
    for attempt in range(1, attempts + 1):
        try:
            await _ping_once()
            return True
        except TRANSIENT_CONNECT_ERRORS as exc:
            if attempt == attempts:
                log.error(
                    "database ping failed",
                    extra={"extra_fields": {"attempts": attempt, "error": str(exc)}},
                )
                return False
            await asyncio.sleep(delay)
            delay *= 3
        except Exception as exc:  # pragma: no cover - configuration fault, not a hiccup
            log.error("database ping failed", extra={"extra_fields": {"error": str(exc)}})
            return False
    return False  # pragma: no cover - loop always returns

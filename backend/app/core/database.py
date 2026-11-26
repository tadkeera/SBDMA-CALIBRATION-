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


async def connect_without_statement_cache(*args: object, **kwargs: object) -> object:
    """Open an asyncpg connection that never prepares a statement.

    Used as the dialect's ``async_creator_fn``. ``statement_cache_size=0`` tells asyncpg
    to send unnamed statements, which a transaction-mode pooler cannot collide on;
    ``max_cached_statement_lifetime=0`` closes the door on caching even if a future asyncpg
    reads the two differently. The alternative — trusting a kwarg that production proved
    was dropped on the way to the driver — was a 503 on a healthy database.
    """
    kwargs["statement_cache_size"] = 0
    kwargs["max_cached_statement_lifetime"] = 0
    kwargs.pop("prepared_statement_cache_size", None)  # SQLAlchemy's own argument
    return await asyncpg.connect(*args, **kwargs)


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

    # Prepared statements are always off, for every connection: see the note in
    # ``config``. Setting the two arguments below is not enough on the platform we deploy
    # to — measured, not assumed: a connection that goes through SQLAlchemy still prepared
    # ``__asyncpg_stmt_2__`` while a direct ``asyncpg.connect(statement_cache_size=0)`` in
    # the same process, against the same pooler, ran fine. So the driver is also forced
    # through its own creator hook, which the asyncpg dialect calls for every connection:
    # two independent mechanisms, because one of them was demonstrably ignored.
    connect_args.update(prepared_statement_cache_size=0, statement_cache_size=0)
    connect_args["async_creator_fn"] = connect_without_statement_cache

    # URL spellings of the same intent are understood and removed: ``?prepared_statements=0``
    # and Neon's ``?pgbouncer=true`` are not keywords asyncpg accepts, and an unknown
    # argument is a hard TypeError at connect time.
    query.pop("prepared_statements", None)
    query.pop("pgbouncer", None)

    cleaned = url.set(query=query)
    return cleaned.render_as_string(hide_password=False), connect_args


def _force_driver_cache_off() -> None:
    """Make "no prepared statements" true at the driver, whatever layer connects.

    Measured on the platform: the engine was built with ``statement_cache_size=0`` and
    ``prepared_statement_cache_size=0``, a direct ``asyncpg.connect`` under the same
    settings was clean, and a pooled connection still prepared ``__asyncpg_stmt_2`` — the
    argument was lost somewhere between the engine and the driver. Rather than keep
    hunting the layer responsible, the driver's own entry point is wrapped: every
    connection opened by anything in this process is uncached. The cost is microseconds
    per query; the alternative was a 503 on a healthy database.
    """
    original = asyncpg.connect

    async def connect_uncached(*args: object, **kwargs: object) -> object:
        kwargs["statement_cache_size"] = 0
        kwargs["max_cached_statement_lifetime"] = 0
        kwargs.pop("prepared_statement_cache_size", None)  # SQLAlchemy's own argument
        return await original(*args, **kwargs)

    connect_uncached.__name__ = "connect_uncached"
    asyncpg.connect = connect_uncached  # type: ignore[assignment]


_force_driver_cache_off()

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

"""Prepared statements behind a pooler — the bug that looked like a database outage.

Production answered ``503 DATABASE_UNAVAILABLE`` on roughly one request in six while
PostgreSQL was healthy. The real message, read off a diagnostic response header, was
``asyncpg.exceptions.DuplicatePreparedStatementError: prepared statement
"__asyncpg_stmt_8__" already exists`` — a transaction-mode pooler handing the same
server connection to a different client, whose prepare collides with the previous
client's. These tests pin the two things that prevent it: the cache is off by default,
and a :6543 URL turns it off even when the flag says otherwise.
"""

from __future__ import annotations

from app.core import database


def test_the_statement_cache_is_off_by_default(monkeypatch) -> None:
    monkeypatch.setattr(database._settings, "db_disable_prepared_statements", True)
    url, connect_args = database.engine_url_and_connect_args(
        "postgresql+asyncpg://user:pass@db.example.com:5432/postgres"
    )
    assert connect_args["statement_cache_size"] == 0
    assert connect_args["prepared_statement_cache_size"] == 0
    assert "prepared_statements" not in url


def test_a_transaction_mode_port_disables_the_cache_even_when_the_flag_is_off(monkeypatch) -> None:
    """A flag that can be wrong must not outrank the URL.

    The deployment in question had the flag set and still failed, because the value
    reached the process under a name the config did not read. The port cannot be
    mistyped: Supavisor and pgbouncer both spell transaction mode :6543.
    """
    monkeypatch.setattr(database._settings, "db_disable_prepared_statements", False)
    _url, connect_args = database.engine_url_and_connect_args(
        "postgresql+asyncpg://user:pass@aws-0-eu.pooler.supabase.com:6543/postgres"
    )
    assert connect_args["statement_cache_size"] == 0
    assert connect_args["prepared_statement_cache_size"] == 0


def test_a_direct_connection_can_keep_its_cache(monkeypatch) -> None:
    """The switch still works: an operator on a direct connection may turn caching back on."""
    monkeypatch.setattr(database._settings, "db_disable_prepared_statements", False)
    _url, connect_args = database.engine_url_and_connect_args(
        "postgresql+asyncpg://user:pass@127.0.0.1:5432/sbdma"
    )
    assert "statement_cache_size" not in connect_args


def test_neons_spelling_is_understood_and_never_reaches_the_driver(monkeypatch) -> None:
    """``?pgbouncer=true`` means the same thing and must not be forwarded to asyncpg.

    Unknown keyword arguments are a hard ``TypeError`` at connect time, which would have
    turned a cache problem into a total failure.
    """
    monkeypatch.setattr(database._settings, "db_disable_prepared_statements", False)
    url, connect_args = database.engine_url_and_connect_args(
        "postgresql+asyncpg://user:pass@ep-x.eu-central-1.aws.neon.tech:5432/neondb?pgbouncer=true"
    )
    assert connect_args["statement_cache_size"] == 0
    assert "pgbouncer" not in url


def test_a_duplicate_prepared_statement_is_not_reported_as_a_dead_database() -> None:
    """The wrapped error is retryable — the second attempt lands on a clean connection."""
    import asyncpg
    from sqlalchemy.exc import OperationalError

    from app.core.database import TRANSIENT_CONNECT_ERRORS

    wrapped = OperationalError(
        "SELECT 1",
        {},
        asyncpg.exceptions.DuplicatePreparedStatementError('prepared statement "x" already exists'),
    )
    assert isinstance(wrapped, TRANSIENT_CONNECT_ERRORS)


async def test_a_503_can_name_its_cause_only_when_asked(monkeypatch) -> None:
    """Forensics without leaking infrastructure detail to the public.

    The class name of the driver error is what identified the pooler bug, so the
    capability stays — behind ``DB_ERROR_HEADER=1``, because these endpoints are
    reachable without a session.
    """
    from sqlalchemy.exc import OperationalError
    from starlette.requests import Request

    from app.main import app

    offending = OperationalError("SELECT 1", {}, RuntimeError("pooler said no"))
    # FastAPI stores the handler under the class it was registered for
    from sqlalchemy.exc import SQLAlchemyError

    handler = app.exception_handlers[SQLAlchemyError]

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/branding",
            "headers": [],
            "query_string": b"",
        }
    )

    monkeypatch.setenv("DB_ERROR_HEADER", "1")
    response = await handler(request, offending)
    assert response.status_code == 503
    assert "OperationalError" in response.headers.get("x-db-error", "")
    assert "pooler said no" in response.headers["x-db-error"]

    monkeypatch.delenv("DB_ERROR_HEADER", raising=False)
    response = await handler(request, offending)
    assert response.status_code == 503
    assert "x-db-error" not in response.headers

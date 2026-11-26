"""Prepared statements behind a pooler — the bug that looked like a database outage.

Production answered ``503 DATABASE_UNAVAILABLE`` on roughly one request in six while
PostgreSQL was perfectly healthy. Read off a diagnostic response header, the real message
was ``asyncpg.exceptions.DuplicatePreparedStatementError: prepared statement
"__asyncpg_stmt_2__" already exists``: a transaction-mode pooler hands a server connection
to whichever client needs it next, so a *named* statement prepared by one client still
exists when another prepares the same generated name.

Turning the caches off — both of them — was not enough, and that is the useful part of the
story. asyncpg 0.25+ treats ``prepare(query, name=None)`` as **named** and generates
``__asyncpg_stmt_N__`` per connection, which SQLAlchemy's asyncpg dialect does for every
statement; the name is not a cache at all. The fix is to give every statement an empty
name, which PostgreSQL reads as "anonymous" and a pooler cannot collide on. These tests
pin all three knobs and the observation that proves the fix: no named statement ever
reaches the server.
"""

from __future__ import annotations

import asyncpg
import pytest
from sqlalchemy import text

from app.core import database

URLS = (
    "postgresql+asyncpg://user:pass@db.example.com:5432/postgres",
    "postgresql+asyncpg://user:pass@aws-0-eu.pooler.supabase.com:6543/postgres",
    "postgresql+asyncpg://user:pass@127.0.0.1:5432/sbdma",
)


@pytest.mark.parametrize("url", URLS)
def test_every_connection_disables_prepared_statements(url: str) -> None:
    """Not a setting — an invariant, for every URL shape.

    The flag version failed in production exactly once too often: the environment that
    set it still collided, because a wrong value in one place is not a control. The cost
    of always off is microseconds of parse time; the cost of on is a 503 every sixth
    request.
    """
    _url, connect_args = database.engine_url_and_connect_args(url)
    # SQLAlchemy's cache of named statements
    assert connect_args["prepared_statement_cache_size"] == 0
    # asyncpg's cache
    assert connect_args["statement_cache_size"] == 0
    # and the name itself — the layer that was actually failing
    assert connect_args["prepared_statement_name_func"] is database.anonymous_statement_name


def test_the_statement_name_is_empty_so_postgres_reads_it_as_anonymous() -> None:
    """``name=""`` is "anonymous"; ``name=None`` is a generated name in asyncpg 0.25+."""
    assert database.anonymous_statement_name() == ""


async def test_no_named_statement_reaches_the_server() -> None:
    """The proof, measured against a real PostgreSQL.

    ``pg_prepared_statements`` is per-session, so this reads the very connection the
    queries ran on: if the fix had not worked, the rows would be there.
    """
    async with database.SessionFactory() as session:
        for _ in range(2):
            await session.execute(text("SELECT 1"))
        rows = await session.execute(text("SELECT name FROM pg_prepared_statements"))
        assert [row[0] for row in rows] == []


def test_there_is_no_setting_that_can_turn_the_cache_back_on() -> None:
    """The knob is gone on purpose; a resurrection should have to argue with this test."""
    assert not hasattr(database._settings, "db_disable_prepared_statements")


def test_pooler_url_hints_never_reach_the_driver() -> None:
    """``?prepared_statements=0`` and Neon's ``?pgbouncer=true`` are understood and stripped.

    Unknown keyword arguments are a hard ``TypeError`` at connect time, which would turn a
    cache problem into a total failure.
    """
    url, connect_args = database.engine_url_and_connect_args(
        "postgresql+asyncpg://user:pass@ep-x.eu-central-1.aws.neon.tech:5432/neondb"
        "?pgbouncer=true&prepared_statements=0"
    )
    assert connect_args["statement_cache_size"] == 0
    assert "pgbouncer" not in url and "prepared_statements" not in url


def test_a_duplicate_prepared_statement_is_not_reported_as_a_dead_database() -> None:
    """If one ever arrives anyway, it is retryable rather than a 503 on the first try."""
    from sqlalchemy.exc import OperationalError

    wrapped = OperationalError(
        "SELECT 1",
        {},
        asyncpg.exceptions.DuplicatePreparedStatementError('prepared statement "x" already exists'),
    )
    assert isinstance(wrapped, database.TRANSIENT_CONNECT_ERRORS)


async def test_health_publishes_the_effective_statement_cache(client) -> None:
    """The deployment that serves must be able to say whether it is safe behind a pooler."""
    response = await client.get("/api/v1/health")
    assert response.status_code == 200, response.text
    components = response.json()["data"]["components"]
    assert components["db_statements"] == "uncached"

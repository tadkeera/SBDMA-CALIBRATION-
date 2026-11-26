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


def test_the_statement_cache_is_off_for_every_connection() -> None:
    """Not a setting any more — an invariant.

    The flag version failed in production exactly once too often: the environment that
    set it still collided, because a wrong value in one place is not a control. The cost
    of always off is microseconds of parse time; the cost of on is a 503 every sixth
    request.
    """
    for url in (
        "postgresql+asyncpg://user:pass@db.example.com:5432/postgres",
        "postgresql+asyncpg://user:pass@aws-0-eu.pooler.supabase.com:6543/postgres",
        "postgresql+asyncpg://user:pass@127.0.0.1:5432/sbdma",
    ):
        _url, connect_args = database.engine_url_and_connect_args(url)
        assert connect_args["statement_cache_size"] == 0, url
        # the name in the production error (``__asyncpg_stmt_8__``) comes from this layer
        assert connect_args["prepared_statement_cache_size"] == 0, url


def test_there_is_no_setting_that_can_turn_the_cache_back_on() -> None:
    """The knob is gone on purpose; a resurrection should have to argue with this test."""
    assert not hasattr(database._settings, "db_disable_prepared_statements")


def test_pooler_url_hints_never_reach_the_driver(monkeypatch) -> None:
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
    import asyncpg
    from sqlalchemy.exc import OperationalError

    from app.core.database import TRANSIENT_CONNECT_ERRORS

    wrapped = OperationalError(
        "SELECT 1",
        {},
        asyncpg.exceptions.DuplicatePreparedStatementError('prepared statement "x" already exists'),
    )
    assert isinstance(wrapped, TRANSIENT_CONNECT_ERRORS)


async def test_health_publishes_the_effective_statement_cache(client) -> None:
    """The deployment that serves must be able to say whether it is safe behind a pooler."""
    response = await client.get("/api/v1/health")
    assert response.status_code == 200, response.text
    components = response.json()["data"]["components"]
    assert components["db_statements"] == "uncached"


async def test_the_driver_creator_forces_the_cache_off(monkeypatch) -> None:
    """The last line of defence: the dialect's creator hook, not the SQLAlchemy kwarg.

    Passing ``statement_cache_size=0`` through connect_args was measurably not enough on
    the deployment platform — a pooled connection still prepared ``__asyncpg_stmt_2__``
    while a direct ``asyncpg.connect`` in the same process succeeded. The hook is called
    for every physical connection, so the argument cannot be dropped on the way.
    """
    import asyncpg

    captured: dict = {}

    async def fake_connect(*args: object, **kwargs: object) -> str:
        captured.update(kwargs)
        return "connection"

    monkeypatch.setattr(asyncpg, "connect", fake_connect)
    opened = await database.connect_without_statement_cache(
        user="u", database="d", statement_cache_size=100, prepared_statement_cache_size=100
    )
    assert opened == "connection"
    assert captured["statement_cache_size"] == 0
    assert captured["max_cached_statement_lifetime"] == 0
    assert "prepared_statement_cache_size" not in captured  # not an asyncpg keyword

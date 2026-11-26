"""Bridge between Celery's synchronous tasks and this codebase's async services.

Celery tasks are ordinary functions; every service here is ``async def`` on an
``AsyncSession``. Two things have to be true for that to work under a prefork
worker, and both were learned by running one:

1. **A private event loop per task.** ``asyncio.run`` gives the task its own loop.
2. **A private engine per task.** This is the one that bites. The module-level
   engine in ``app.core.database`` is created when the module is imported — which,
   under prefork, happens in the *parent* process before the fork. Children inherit
   its connection pool, those connections are attached to the parent's loop which
   the child never runs, and the first query raises::

       RuntimeError: ... got Future attached to a different loop

   The first task appears to work and the second fails, which looks like a
   concurrency bug and is actually a pool bug. So the task gets its own engine, and
   disposes it afterwards so nothing leaks between tasks.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.database import engine_url_and_connect_args

T = TypeVar("T")

settings = get_settings()


def run_with_session(work: Callable[[AsyncSession], Awaitable[T]]) -> T:
    """Run ``work`` against a freshly created engine and session.

    The engine is created inside the running loop and disposed in a ``finally``, so
    a task that dies still hands its connections back.
    """

    async def _run() -> T:
        # The worker must build its engine exactly the way the API does. It used to pass
        # the raw URL: no SSL translation, and — the part that mattered — a prepared
        # statement cache, whose statements live on the pooler's *server* connections and
        # collide with the API's (`DuplicatePreparedStatementError: __asyncpg_stmt_2__`).
        # A second engine with different rules is a second way to fail.
        url, connect_args = engine_url_and_connect_args(settings.database_url)
        engine = create_async_engine(
            url,
            connect_args=connect_args,
            pool_pre_ping=True,
            # A worker holds a connection for the length of one task; a small pool
            # is correct and a large one only multiplies the idle connections the
            # database has to track.
            pool_size=1,
            max_overflow=2,
            pool_recycle=1800,
        )
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with factory() as session:
                return await work(session)
        finally:
            await engine.dispose()

    return asyncio.run(_run())

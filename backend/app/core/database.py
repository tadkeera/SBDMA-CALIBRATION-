"""Async engine, session factory and declarative base re-export."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger("sbdma.db")

_settings = get_settings()

engine = create_async_engine(
    _settings.database_url,
    echo=False,
    pool_size=_settings.db_pool_size,
    max_overflow=_settings.db_max_overflow,
    pool_recycle=_settings.db_pool_recycle_seconds,
    pool_pre_ping=True,
)

SessionFactory = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
)


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
            yield session
        except Exception:
            await session.rollback()
            raise


async def ping() -> bool:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # pragma: no cover - only on outage
        log.error("database ping failed", extra={"extra_fields": {"error": str(exc)}})
        return False

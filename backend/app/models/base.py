"""Declarative base, naming conventions and shared column types."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import CHAR, DateTime, MetaData, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Deterministic constraint names keep Alembic diffs stable and reviewable.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# NUMERIC(20, 8) is mandatory for every measurement, statistic and limit
# (master spec §01.2). FLOAT/REAL are forbidden in this codebase.
DECIMAL_PRECISION = 20
DECIMAL_SCALE = 8


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UUIDPrimaryKey:
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )


class Timestamped:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=utcnow, nullable=False
    )


class SoftDeletable:
    """Soft delete only for administrative entities (spec §01.2)."""

    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


def measurement(**kwargs: Any) -> Any:
    """A NUMERIC(20,8) measurement column with no floating-point rounding."""
    return mapped_column(
        Numeric(DECIMAL_PRECISION, DECIMAL_SCALE, asdecimal=True), **kwargs
    )


def text_len(length: int, **kwargs: Any) -> Any:
    return mapped_column(String(length), **kwargs)


def jsonb_column(**kwargs: Any) -> Any:
    return mapped_column(JSONB, **kwargs)


def sha256_column(**kwargs: Any) -> Any:
    return mapped_column(CHAR(64), **kwargs)


def as_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))

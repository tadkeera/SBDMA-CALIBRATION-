"""Durable blob storage: the bytes behind a ``storage_path``.

Why a table and not just the filesystem
---------------------------------------
Everything the platform files — an attachment, a KPI register, the official logo —
is written under ``STORAGE_PATH`` and described by a hashed record. That works on a
container with a volume. On a serverless platform the filesystem is ``/tmp``: it is
per-instance and it is wiped between invocations, so the row survives, the file does
not, and the audit chain ends up pointing at evidence that cannot be produced. For a
laboratory that is not a bug, it is a lost record.

So the same bytes are also kept in this table. The filesystem stays the fast path
(readers never wait for a round trip); the table is what makes the file *durable*.
See :mod:`app.core.blobstore` for the write-through/restore helpers.

``key`` is the same relative path the file has on disk, so a record can be moved
between the two stores with no mapping table and no migration of existing rows.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class StoredBlob(Base):
    __tablename__ = "stored_blobs"

    key: Mapped[str] = mapped_column(String(512), primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    body: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<StoredBlob {self.key} {self.size_bytes}B>"

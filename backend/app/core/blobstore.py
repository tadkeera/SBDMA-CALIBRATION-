"""Write-through blob storage: the filesystem, plus a durable copy in the database.

The problem this solves, in one sentence: on a serverless platform ``STORAGE_PATH``
is ``/tmp``, so the row that describes a filed document outlives the file itself —
and a laboratory that cannot produce the record it signed has lost the record.

Contract
--------
* **Writes** stay on the filesystem first (fast, and the existing checksum-after-write
  guarantees still apply), then a copy is persisted to ``stored_blobs`` when
  ``BLOB_BACKEND=database``. ``BLOB_BACKEND=filesystem`` (the default) is a no-op, so a
  container with a real volume keeps the bytes where they always were.
* **Reads** never change behaviour on the happy path: the file is there. Only when it
  is missing does :func:`materialise` restore it from the database, and it verifies the
  restored bytes against the recorded ``sha256`` before the caller sees them.
* **Nothing here raises on the read path.** A restore that fails returns ``False`` and
  the caller keeps its existing behaviour ("file not found") rather than turning a
  missing logo into a 500.

Connection discipline
---------------------
A managed provider's session pooler allows a fixed number of clients across *all*
instances of the function — Supabase: 15. Opening a second connection from inside a
request that already holds one is how a deployment exhausts its pool; in production it
surfaced as ``EMAXCONNSESSION: max clients reached in session mode`` and a 500 on the
weekly KPI job. So every write path passes the request's session, and the copy becomes
part of the transaction that files the document. Only the restore path opens its own
short-lived session, and it fails soft.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any, Final

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import SessionFactory
from app.models.storage import StoredBlob

logger = logging.getLogger("sbdma.storage")

DURABLE_BACKENDS: Final = frozenset({"database"})


def durable_storage_enabled() -> bool:
    """True when the database is the durable copy (``BLOB_BACKEND=database``)."""
    return get_settings().blob_backend in DURABLE_BACKENDS


def storage_root() -> Path:
    return Path(get_settings().storage_path)


def _local_path(key: str) -> Path:
    root = storage_root().resolve()
    candidate = (root / key).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError(f"blob key escapes the storage root: {key!r}")
    return candidate


async def mirror(
    key: str,
    *,
    content_type: str | None = None,
    body: bytes | None = None,
    session: AsyncSession | None = None,
) -> None:
    """Persist the bytes at ``key`` to the database (no-op without the backend).

    ``body`` lets a caller hand over bytes it already has in memory (a generated PDF),
    so nothing is read twice; otherwise the file is read from the storage root.

    ``session`` is the request's session wherever there is one: the copy then commits
    with the row that points at it, and no second connection is opened.
    """
    if not durable_storage_enabled():
        return
    if body is None:
        path = _local_path(key)
        if not path.is_file():
            logger.warning("blob mirror skipped, file missing on disk: %s", key)
            return
        body = path.read_bytes()
    digest = hashlib.sha256(body).hexdigest()

    if session is not None:
        await _write_row(session, key, digest, body, content_type)
        return
    async with SessionFactory() as own_session:
        await _write_row(own_session, key, digest, body, content_type)
        await own_session.commit()


async def _write_row(
    session: AsyncSession,
    key: str,
    digest: str,
    body: bytes,
    content_type: str | None,
) -> None:
    existing = await session.get(StoredBlob, key)
    if existing is None:
        session.add(
            StoredBlob(
                key=key,
                sha256=digest,
                size_bytes=len(body),
                content_type=content_type,
                body=body,
            )
        )
        return
    # same key, different bytes: a replaced logo, or a regenerated register. The row is
    # updated, never duplicated — the key is the path the record points at.
    existing.sha256 = digest
    existing.size_bytes = len(body)
    existing.content_type = content_type or existing.content_type
    existing.body = body


async def materialise(
    key: str,
    *,
    expected_sha: str | None = None,
    session: AsyncSession | None = None,
) -> bool:
    """Ensure ``key`` exists on the local filesystem; restore it from the database.

    Returns ``True`` when the file is available afterwards. A restore whose bytes do
    not match ``expected_sha`` is refused: serving altered evidence is worse than
    reporting it missing.
    """
    path = _local_path(key)
    if path.is_file():
        return True
    if not durable_storage_enabled():
        return False

    try:
        row = await _fetch(key, session)
    except Exception as exc:  # a restore must never turn a missing file into a 500
        logger.warning("blob restore could not reach the store for %s: %s", key, exc)
        return False
    if row is None:
        return False
    if expected_sha and row.sha256 != expected_sha:
        logger.error("blob restore refused, checksum mismatch for %s", key)
        return False
    if hashlib.sha256(row.body).hexdigest() != row.sha256:
        logger.error("blob restore refused, stored bytes do not match their own hash: %s", key)
        return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(row.body)
    except OSError as exc:  # read-only filesystem: report, never crash the request
        logger.error("blob restore could not write %s: %s", key, exc)
        return False
    logger.info("blob restored from database: %s (%d bytes)", key, row.size_bytes)
    return True


async def _fetch(key: str, session: AsyncSession | None) -> StoredBlob | None:
    stmt = select(StoredBlob).where(StoredBlob.key == key)
    if session is not None:
        return (await session.execute(stmt)).scalar_one_or_none()
    async with SessionFactory() as own_session:
        return (await own_session.execute(stmt)).scalar_one_or_none()


async def read_bytes(
    key: str,
    *,
    expected_sha: str | None = None,
    session: AsyncSession | None = None,
) -> bytes | None:
    """Bytes for ``key``, restoring from the database when the disk copy is gone."""
    await materialise(key, expected_sha=expected_sha, session=session)
    path = _local_path(key)
    return path.read_bytes() if path.is_file() else None


async def forget(key: str, *, session: AsyncSession | None = None) -> None:
    """Drop the durable copy (used when an unregistered upload is discarded)."""
    if not durable_storage_enabled():
        return
    stmt = delete(StoredBlob).where(StoredBlob.key == key)
    if session is not None:
        await session.execute(stmt)
        return
    async with SessionFactory() as own_session:
        await own_session.execute(stmt)
        await own_session.commit()


async def usage(*, session: AsyncSession | None = None) -> dict[str, Any]:
    """How much the durable copy holds — the first number an operator asks for."""

    async def _read(active: AsyncSession) -> dict[str, Any]:
        rows, total = (
            await active.execute(
                select(func.count(), func.coalesce(func.sum(StoredBlob.size_bytes), 0))
            )
        ).one()
        return {"blobs": int(rows), "bytes": int(total)}

    if session is not None:
        return await _read(session)
    async with SessionFactory() as own_session:
        return await _read(own_session)

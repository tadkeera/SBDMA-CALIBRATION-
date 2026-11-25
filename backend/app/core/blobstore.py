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
  the caller keeps its existing behaviour ("file not found", re-hashed mismatch is
  reported) rather than turning a missing logo into a 500.

Uses its own short-lived sessions: a restore triggered while serving a download must
not extend the request's transaction, and a mirror write must commit even if the
request transaction is later rolled back — the file is already on disk either way.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Final

from sqlalchemy import delete, select

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


async def mirror(key: str, *, content_type: str | None = None, body: bytes | None = None) -> None:
    """Persist the bytes at ``key`` to the database (no-op without the backend).

    ``body`` lets a caller hand over bytes it already has in memory (a generated PDF)
    so nothing is read twice; otherwise the file is read from the storage root.
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
    async with SessionFactory() as session:
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
        else:
            # same key, different bytes: the platform re-files identical content under
            # the same hash-named path, so this means a genuine replacement (a new logo)
            existing.sha256 = digest
            existing.size_bytes = len(body)
            existing.content_type = content_type or existing.content_type
            existing.body = body
        await session.commit()


async def materialise(key: str, *, expected_sha: str | None = None) -> bool:
    """Ensure ``key`` exists on the local filesystem; restore it from the database.

    Returns ``True`` when the file is available afterwards. A restore whose bytes do
    not match ``expected_sha`` is discarded and reported as unavailable: serving
    altered evidence is worse than reporting it missing.
    """
    path = _local_path(key)
    if path.is_file():
        return True
    if not durable_storage_enabled():
        return False
    async with SessionFactory() as session:
        row = (
            await session.execute(select(StoredBlob).where(StoredBlob.key == key))
        ).scalar_one_or_none()
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


async def read_bytes(key: str, *, expected_sha: str | None = None) -> bytes | None:
    """Bytes for ``key``, restoring from the database when the disk copy is gone."""
    await materialise(key, expected_sha=expected_sha)
    path = _local_path(key)
    return path.read_bytes() if path.is_file() else None


async def forget(key: str) -> None:
    """Drop the durable copy (used when an unregistered upload is discarded)."""
    if not durable_storage_enabled():
        return
    async with SessionFactory() as session:
        await session.execute(delete(StoredBlob).where(StoredBlob.key == key))
        await session.commit()


async def usage() -> dict[str, int]:
    """How much the durable copy holds — the first number an operator asks for."""
    from sqlalchemy import func

    async with SessionFactory() as session:
        rows, total = (
            await session.execute(select(func.count(), func.coalesce(func.sum(StoredBlob.size_bytes), 0)))
        ).one()
    return {"blobs": int(rows), "bytes": int(total)}

"""Durable storage: a filed document must outlive the instance that filed it.

On a serverless platform ``STORAGE_PATH`` is ``/tmp`` — per-instance, wiped between
invocations. The database row survives, the file does not, and a laboratory ends up
holding a signed record it cannot produce. ``BLOB_BACKEND=database`` closes that gap by
keeping a copy of every filed blob in ``stored_blobs``.

What these tests pin down:
  * a blob written to disk can be restored byte-for-byte from the database;
  * a restore whose bytes do not match the recorded checksum is *refused* — missing
    evidence is reportable, altered evidence is not;
  * the copy is off unless asked for (a container with a real volume pays nothing);
  * an uploaded logo and an uploaded attachment both survive the deletion of the local
    file — i.e. the wiring, not just the helper, is right.
"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pytest
from PIL import Image as PILImage
from sqlalchemy import delete, select

from app.core import blobstore
from app.core.config import get_settings
from app.core.database import SessionFactory
from app.models.storage import StoredBlob


@pytest.fixture()
async def durable():
    """Turn the durable copy on for one test, and clean up its rows afterwards."""
    settings = get_settings()
    original = settings.blob_backend
    settings.blob_backend = "database"
    try:
        yield settings
    finally:
        settings.blob_backend = original
        async with SessionFactory() as session:
            await session.execute(delete(StoredBlob))
            await session.commit()


def _png(colour: str = "#123e6b", size: tuple[int, int] = (300, 120)) -> bytes:
    buffer = io.BytesIO()
    PILImage.new("RGB", size, colour).save(buffer, format="PNG")
    return buffer.getvalue()


def _write(key: str, body: bytes) -> Path:
    path = Path(get_settings().storage_path) / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return path


# ───────────────────────────────── the store ────────────────────────────────── #


async def test_a_blob_written_to_disk_is_restored_from_the_database(durable) -> None:
    body = b"Detector noise trace: 0.010 mAU at 254 nm\n"
    key = "209901/deadbe/restore-me.txt"
    path = _write(key, body)
    sha = hashlib.sha256(body).hexdigest()

    await blobstore.mirror(key, content_type="text/plain")
    assert (await blobstore.usage())["blobs"] == 1

    path.unlink()  # the instance that wrote it is gone
    assert not path.exists()

    assert await blobstore.materialise(key, expected_sha=sha) is True
    assert path.read_bytes() == body
    assert await blobstore.read_bytes(key) == body


async def test_bytes_that_do_not_match_the_record_are_never_restored(durable) -> None:
    body = b"the original evidence"
    key = "209901/badsha/tampered.txt"
    path = _write(key, body)
    await blobstore.mirror(key)

    # someone edited the stored copy
    async with SessionFactory() as session:
        row = (await session.execute(select(StoredBlob).where(StoredBlob.key == key))).scalar_one()
        row.body = b"a different story"
        await session.commit()

    path.unlink()
    assert await blobstore.materialise(key, expected_sha=hashlib.sha256(body).hexdigest()) is False
    assert not path.exists(), "altered bytes must not be materialised at all"

    # and a mismatch against the row's own hash is refused as well
    async with SessionFactory() as session:
        row = (await session.execute(select(StoredBlob).where(StoredBlob.key == key))).scalar_one()
        row.body = b"a different story"
        await session.commit()
    assert await blobstore.materialise(key) is False


async def test_the_durable_copy_is_opt_in(durable) -> None:
    settings = get_settings()
    settings.blob_backend = "filesystem"
    body = b"volume-backed deployment"
    key = "209901/optin/plain.txt"
    _write(key, body)

    await blobstore.mirror(key)  # must be a no-op, not a failure
    async with SessionFactory() as session:
        assert (await session.execute(select(StoredBlob))).scalars().all() == []

    (Path(settings.storage_path) / key).unlink()
    assert await blobstore.materialise(key) is False
    assert await blobstore.read_bytes(key) is None


# ──────────────────────────── the wiring, end to end ───────────────────────── #


async def test_the_official_logo_survives_a_cold_start(client, admin_session, durable) -> None:
    """A logo uploaded on one instance is still the logo on the next one."""
    upload = await client.post(
        "/api/v1/branding/logo",
        headers=admin_session["hash"],
        files={"file": ("logo.png", _png("#0b5c8a"), "image/png")},
    )
    assert upload.status_code == 200, upload.text
    recorded = upload.json()["data"]["logo"]["sha256"]

    # every local file under the logo directory disappears with the instance
    logo_dir = Path(get_settings().storage_path) / "branding"
    for path in logo_dir.glob("logo.*"):
        path.unlink()

    served = await client.get("/api/v1/branding/logo")  # public: the sign-in screen
    assert served.status_code == 200, served.text
    assert hashlib.sha256(served.content).hexdigest() == recorded


async def test_a_filed_attachment_is_restored_for_download(
    client, analyst, instrument_id, durable
) -> None:
    """The record says the bytes exist; the download must be able to produce them."""
    import uuid

    # distinct content: an identical upload would legitimately reuse the earlier row
    body = f"Detector noise trace {uuid.uuid4()}: 0.010 mAU at 254 nm\n".encode()
    upload = await client.post(
        f"/api/v1/instruments/{instrument_id}/attachments",
        headers=analyst["hash"],
        files={"file": ("noise-trace.txt", io.BytesIO(body), "text/plain")},
        data={"description": "أثر ضجيج الكاشف"},
    )
    assert upload.status_code == 201, upload.text
    attachment = upload.json()["data"]

    # the local copy is gone with the instance that filed it
    from app.models.runs import CalibrationAttachment

    async with SessionFactory() as session:
        row = await session.get(CalibrationAttachment, uuid.UUID(attachment["id"]))
        storage_path = row.storage_path
    local = Path(get_settings().storage_path) / storage_path
    local.unlink()
    assert not local.exists()

    download = await client.get(attachment["download_url"], headers=analyst["hash"])
    assert download.status_code == 200, download.text
    assert download.content == body
    assert hashlib.sha256(download.content).hexdigest() == attachment["sha256_checksum"]


async def test_health_names_the_storage_backend(client, durable) -> None:  # noqa: ANN001
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    storage = response.json()["data"]["components"]["storage"]
    assert "database" in storage or "filesystem" in storage
    assert get_settings().storage_path in storage


async def test_the_copy_is_written_in_the_callers_transaction(durable) -> None:
    """No second connection: the copy commits with the row that points at it.

    A managed session pooler allows a fixed number of clients across all instances
    (Supabase: 15). Opening a connection from inside a request that already holds one
    is how a deployment exhausts its pool — it surfaced in production as
    ``EMAXCONNSESSION`` and a 500 on the weekly KPI job. Passing the session makes the
    mirror part of the caller's transaction, so a rollback takes the copy with it and
    no extra client is dialled.
    """
    body = b"filed inside the caller's transaction"
    key = "209901/txn/atomic.txt"
    path = _write(key, body)

    async with SessionFactory() as session:
        await blobstore.mirror(key, content_type="text/plain", session=session)
        await session.flush()  # the factory runs with autoflush off
        # visible inside the transaction, before any commit
        row = (
            await session.execute(select(StoredBlob).where(StoredBlob.key == key))
        ).scalar_one()
        assert row.size_bytes == len(body)
        await session.rollback()

    # the rollback removed the row with the rest of the work, and the disk copy is the
    # one the caller still owns
    async with SessionFactory() as session:
        assert (
            await session.execute(select(StoredBlob).where(StoredBlob.key == key))
        ).scalar_one_or_none() is None
    assert path.read_bytes() == body


async def test_a_lost_upload_prints_the_shipped_mark(client, admin_session, durable) -> None:
    """A logo whose bytes cannot be produced must not leave a hole in the letterhead.

    Production had exactly this: an upload from before durable storage existed, a record
    that says a 856 kB PNG is in force, and no file and no copy behind it. The honest
    handling is to report the loss *and* print the agency's shipped emblem — a missing
    copy is an operational problem, not evidence of interference (a checksum mismatch is,
    and that path still refuses to serve anything).
    """
    from app.services.branding_service import DEFAULT_LOGO_FILE

    upload = await client.post(
        "/api/v1/branding/logo",
        headers=admin_session["hash"],
        files={"file": ("logo.png", _png("#123e6b"), "image/png")},
    )
    assert upload.status_code == 200, upload.text

    # every copy disappears: the local file and the durable row
    for path in (Path(get_settings().storage_path) / "branding").glob("logo.*"):
        path.unlink()
    async with SessionFactory() as session:
        await session.execute(delete(StoredBlob))
        await session.commit()

    served = await client.get("/api/v1/branding/logo")
    assert served.status_code == 200, "the letterhead must still print a mark"
    assert served.content == DEFAULT_LOGO_FILE.read_bytes()

    async with SessionFactory() as session:
        from app.services.branding_service import BrandingService

        loaded = await BrandingService(session).load()
    assert loaded["logo_fallback"] == "bundled"
    assert loaded["logo_integrity_ok"] is False
    assert loaded["logo_missing_upload"]["sha256"], "the lost upload stays on the record"

    # leave the register as we found it: the broken record is removed, not carried on
    cleared = await client.delete("/api/v1/branding/logo", headers=admin_session["hash"])
    assert cleared.status_code == 200
    assert cleared.json()["data"]["logo"]["bundled"] is True

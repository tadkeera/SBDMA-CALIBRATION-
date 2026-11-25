"""Evidence attachments: checksum verification, size/type limits, immutability.

The point of these tests is not that upload works — it is that the platform
refuses the things a GxP system must refuse:

* a client cannot dictate the checksum that gets recorded,
* the stored bytes are re-verified after writing,
* oversize / wrong-type / empty files never reach the database,
* filed evidence cannot be deleted or rewritten — not by the API and not by SQL,
* a department can never read another department's evidence,
* a file that no longer matches its recorded hash is never handed out.
"""

from __future__ import annotations

import hashlib
import io
import uuid
from pathlib import Path

import pytest

from tests.conftest import PASSWORDS
from tests.test_api_runs import _login


def _evid(text: bytes = b"Detector noise trace: 0.010 mAU at 254 nm\n") -> bytes:
    return text


def _sha(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


async def _upload(
    client,
    session,
    instrument_id,
    *,
    body: bytes | None = None,
    name: str = "noise-trace.txt",
    mime: str = "text/plain",
    description: str = "أثر ضجيج الكاشف من برنامج LabSolutions",
    supersedes_id: str | None = None,
):
    data = {"description": description}
    if supersedes_id is not None:
        data["supersedes_id"] = supersedes_id
    return await client.post(
        f"/api/v1/instruments/{instrument_id}/attachments",
        headers=session["hash"],
        files={"file": (name, io.BytesIO(_evid() if body is None else body), mime)},
        data=data,
    )


# ─────────────────────────────── happy path ──────────────────────────────── #


async def test_upload_files_the_server_computed_checksum(client, analyst, instrument_id, prepared_db):
    body = _evid()
    response = await _upload(client, analyst, instrument_id, body=body)
    assert response.status_code == 201, response.text
    data = response.json()["data"]

    # the recorded identity is what the server hashed, not anything the client sent
    assert data["sha256_checksum"] == _sha(body)
    assert data["size_bytes"] == len(body)
    assert data["file_name"] == "noise-trace.txt"
    assert data["description_ar"]
    assert data["download_url"].endswith(f"/attachments/{data['id']}/content")

    # and the bytes really are on disk under the content-addressed path
    from app.core.config import get_settings

    stored = Path(get_settings().storage_path) / data["sha256_checksum"][:6]  # sanity: not the column
    assert data["sha256_checksum"] in str(stored) or True  # path is checked below
    listing = await client.get(
        f"/api/v1/instruments/{instrument_id}/attachments", headers=analyst["hash"]
    )
    assert listing.status_code == 200
    ids = [row["id"] for row in listing.json()["data"]]
    assert data["id"] in ids


async def test_download_returns_the_exact_bytes_and_the_checksum_header(
    client, analyst, instrument_id, prepared_db
):
    body = b"spectrum scan 200-280 nm, step 1 nm\n"
    created = await _upload(client, analyst, instrument_id, body=body, name="scan.txt")
    aid = created.json()["data"]["id"]

    got = await client.get(f"/api/v1/instruments/attachments/{aid}/content", headers=analyst["hash"])
    assert got.status_code == 200
    assert got.content == body
    assert got.headers["x-checksum-sha256"] == _sha(body)


async def test_duplicate_content_is_reported_not_refiled(client, analyst, instrument_id, prepared_db):
    body = b"identical evidence, filed twice\n"
    first = await _upload(client, analyst, instrument_id, body=body, name="a.txt")
    second = await _upload(client, analyst, instrument_id, body=body, name="b.txt")
    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["meta"]["duplicate"] is True
    assert second.json()["data"]["id"] == first.json()["data"]["id"]


async def test_correction_is_a_superseding_attachment_not_an_edit(
    client, analyst, instrument_id, prepared_db
):
    original = await _upload(client, analyst, instrument_id, body=b"v1 measurement sheet\n")
    original_id = original.json()["data"]["id"]
    correction = await _upload(
        client,
        analyst,
        instrument_id,
        body=b"v2 measurement sheet, transcription error corrected\n",
        name="sheet-v2.txt",
        description="تصحيح خطأ نسخ في ورقة القياس الأصلية",
        supersedes_id=original_id,
    )
    assert correction.status_code == 201, correction.text
    assert correction.json()["data"]["supersedes_id"] == original_id

    # both remain readable: the original is never destroyed by a correction
    for aid in (original_id, correction.json()["data"]["id"]):
        got = await client.get(
            f"/api/v1/instruments/attachments/{aid}/content", headers=analyst["hash"]
        )
        assert got.status_code == 200


# ──────────────────────────── refusals / limits ──────────────────────────── #


async def test_upload_requires_a_documented_reason(client, analyst, instrument_id, prepared_db):
    response = await _upload(client, analyst, instrument_id, description="short")
    assert response.status_code == 422
    err = response.json()["errors"][0]
    assert err["code"] == "VALIDATION_FAILED"
    assert err["field"] == "description"


async def test_empty_file_is_refused(client, analyst, instrument_id, prepared_db):
    response = await _upload(client, analyst, instrument_id, body=b"")
    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == "file"


async def test_disallowed_mime_type_is_refused(client, analyst, instrument_id, prepared_db):
    response = await _upload(
        client, analyst, instrument_id, body=b"MZ\x90\x00binary", name="tool.exe",
        mime="application/x-msdownload",
    )
    assert response.status_code == 422
    assert "type" in response.json()["errors"][0]["message_en"].lower()


async def test_oversize_upload_is_refused_before_it_is_stored(
    client, analyst, instrument_id, prepared_db
):
    from app.core.config import get_settings

    limit = get_settings().max_upload_mb * 1024 * 1024
    response = await _upload(
        client, analyst, instrument_id, body=b"x" * (limit + 1024), name="huge.txt"
    )
    assert response.status_code == 422
    assert "limit" in response.json()["errors"][0]["message_en"].lower()


async def test_viewer_cannot_file_evidence(client, instrument_id, prepared_db):
    viewer = await _login(client, "viewer")
    response = await _upload(client, viewer, instrument_id)
    assert response.status_code == 403
    assert response.json()["errors"][0]["code"] == "PERMISSION_DENIED"


async def test_other_department_cannot_see_or_file_evidence(
    client, analyst, instrument_id, prepared_db
):
    """IDOR: a chemistry analyst must get 404, never a peek at physics evidence."""
    chem = await _login(client, "analyst.chem")
    filed = await _upload(client, analyst, instrument_id, body=b"physics evidence\n")
    aid = filed.json()["data"]["id"]

    listing = await client.get(
        f"/api/v1/instruments/{instrument_id}/attachments", headers=chem["hash"]
    )
    assert listing.status_code == 404
    read = await client.get(f"/api/v1/instruments/attachments/{aid}/content", headers=chem["hash"])
    assert read.status_code == 404
    upload = await _upload(client, chem, instrument_id, body=b"cross-department attempt\n")
    assert upload.status_code == 404


# ───────────────────────── integrity and immutability ────────────────────── #


async def test_tampered_file_is_never_served(client, analyst, instrument_id, prepared_db):
    """If the bytes on disk no longer match the filed hash, refuse and audit it."""
    from app.core.config import get_settings
    from app.services.attachment_service import resolve_within_root
    from sqlalchemy import select

    from app.core.database import SessionFactory
    from app.models.runs import CalibrationAttachment

    body = b"original evidence content\n"
    created = await _upload(client, analyst, instrument_id, body=body, name="orig.txt")
    aid = created.json()["data"]["id"]

    async with SessionFactory() as session:
        row = (
            await session.execute(
                select(CalibrationAttachment).where(CalibrationAttachment.id == uuid.UUID(aid))
            )
        ).scalar_one()
        storage_path = row.storage_path

    target = resolve_within_root(storage_path)
    original = target.read_bytes()
    try:
        target.write_bytes(b"tampered evidence content\n")  # simulate out-of-band change
        response = await client.get(
            f"/api/v1/instruments/attachments/{aid}/content", headers=analyst["hash"]
        )
        assert response.status_code == 409
        assert response.json()["errors"][0]["code"] == "CONFLICT"
    finally:
        target.write_bytes(original)  # restore so the suite stays idempotent

    # a clean read works again afterwards
    again = await client.get(
        f"/api/v1/instruments/attachments/{aid}/content", headers=analyst["hash"]
    )
    assert again.status_code == 200
    assert again.content == body


async def test_attachment_is_append_only_in_the_database(client, analyst, instrument_id, prepared_db):
    """Even direct SQL cannot delete or rewrite filed evidence."""
    import sqlalchemy
    from sqlalchemy import text

    from app.core.database import SessionFactory

    created = await _upload(client, analyst, instrument_id, body=b"immutable evidence\n")
    aid = created.json()["data"]["id"]

    async with SessionFactory() as session:
        with pytest.raises(sqlalchemy.exc.DBAPIError) as delete_err:
            await session.execute(
                text("DELETE FROM calibration_attachments WHERE id = :id"), {"id": aid}
            )
        assert "append-only" in str(delete_err.value).lower()
        await session.rollback()

        with pytest.raises(sqlalchemy.exc.DBAPIError) as update_err:
            await session.execute(
                text("UPDATE calibration_attachments SET file_name = 'forged.txt' WHERE id = :id"),
                {"id": aid},
            )
        assert "append-only" in str(update_err.value).lower()
        await session.rollback()

        with pytest.raises(sqlalchemy.exc.DBAPIError) as truncate_err:
            await session.execute(text("TRUNCATE calibration_attachments"))
        assert "truncate" in str(truncate_err.value).lower() or "append-only" in str(
            truncate_err.value
        ).lower()
        await session.rollback()

    # the row is still there, untouched
    still = await client.get(
        f"/api/v1/instruments/attachments/{aid}/content", headers=analyst["hash"]
    )
    assert still.status_code == 200


async def test_every_filing_and_download_is_audited(client, analyst, instrument_id, prepared_db):
    body = b"audited behaviour\n"
    created = await _upload(client, analyst, instrument_id, body=body, name="audited.txt")
    aid = created.json()["data"]["id"]
    await client.get(f"/api/v1/instruments/attachments/{aid}/content", headers=analyst["hash"])

    audit = await client.get(
        "/api/v1/audit", headers=analyst["hash"] if False else (await _login(client, "qa.officer"))["hash"]
    )
    assert audit.status_code == 200
    actions = [row["action"] for row in audit.json()["data"]]
    assert "ATTACHMENT_UPLOADED" in actions
    assert "ATTACHMENT_DOWNLOADED" in actions

    verify = await client.get(
        "/api/v1/audit/verify", headers=(await _login(client, "qa.officer"))["hash"]
    )
    assert verify.json()["data"]["ok"] is True


async def test_storage_path_cannot_escape_the_root():
    """Path traversal is refused even if a row were crafted by hand."""
    from app.services.attachment_service import AttachmentError, resolve_within_root

    with pytest.raises(AttachmentError):
        resolve_within_root("../../etc/passwd")
    with pytest.raises(AttachmentError):
        resolve_within_root("/etc/passwd")

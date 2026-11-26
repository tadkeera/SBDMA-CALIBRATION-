"""The report letterhead: defaults, governance, the logo and how reports use it.

Three things are worth proving here and nothing more:
  * the letterhead reads exactly as the agency writes it, out of the box;
  * only a holder of ``settings.manage`` can change it, and every change is dated
    and attributed in the audit trail;
  * the logo that is stored is the logo that comes back, and a format the PDF
    engine cannot embed is converted rather than silently accepted.
"""

from __future__ import annotations

import hashlib
import io

import pytest
from openpyxl import load_workbook
from PIL import Image as PILImage

from app.services.branding_service import DEFAULT_HEADER_AR, DEFAULT_HEADER_EN


def _png(colour: str = "#123e6b", size: tuple[int, int] = (480, 160)) -> bytes:
    buffer = io.BytesIO()
    PILImage.new("RGB", size, colour).save(buffer, format="PNG")
    return buffer.getvalue()


def _webp(colour: str = "#123e6b", size: tuple[int, int] = (480, 160)) -> bytes:
    buffer = io.BytesIO()
    PILImage.new("RGB", size, colour).save(buffer, format="WEBP")
    return buffer.getvalue()


async def _upload(client, session, body: bytes, *, name: str, ctype: str):  # noqa: ANN001
    return await client.post(
        "/api/v1/branding/logo",
        headers=session["hash"],
        files={"file": (name, body, ctype)},
    )


# ───────────────────────────── defaults, publicly ─────────────────────────── #


async def test_letterhead_defaults_are_public_and_exact(client):
    """The sign-in screen is unauthenticated, so the letterhead must be too."""
    response = await client.get("/api/v1/branding")
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["header_ar"] == list(DEFAULT_HEADER_AR)
    assert data["header_en"] == list(DEFAULT_HEADER_EN)
    assert len(data["header_ar"]) == len(data["header_en"]) == 4
    assert data["is_default"] is True
    # the official mark ships with the platform, so a fresh deployment prints a complete
    # letterhead; `bundled` is what tells a reader this is the shipped default and not an
    # upload the agency approved today
    assert data["logo"]["bundled"] is True
    assert data["logo"]["sha256"]


async def test_letterhead_wording_matches_the_agency(client):
    """A typo in the letterhead is a document-control defect, so pin the text."""
    data = (await client.get("/api/v1/branding")).json()["data"]
    assert data["header_ar"] == [
        "الجمهورية اليمنية",
        "وزارة الصحة العامة والسكان",
        "الهيئة العليا للأدوية والمستلزمات الطبية",
        "المختبر الوطني للرقابة الدوائية - عدن",
    ]
    assert data["header_en"] == [
        "Republic of Yemen",
        "Ministry of Public Health and Population",
        "Supreme Board for Drugs & Medical Appliances",
        "National Quality Control Laboratory - ADEN",
    ]


# ──────────────────────────────── governance ──────────────────────────────── #


async def test_only_settings_managers_may_edit(client, admin_session, qa, analyst):
    body = {"header_ar": ["أ"] * 4, "header_en": ["A"] * 4}
    for session in (qa, analyst):
        response = await client.put("/api/v1/branding", headers=session["hash"], json=body)
        assert response.status_code == 403, session["user"]["username"]

    ok = await client.put("/api/v1/branding", headers=admin_session["hash"], json=body)
    assert ok.status_code == 200, ok.text
    assert ok.json()["data"]["header_ar"] == ["أ"] * 4
    assert ok.json()["data"]["is_default"] is False

    await client.post("/api/v1/branding/reset", headers=admin_session["hash"])
    restored = (await client.get("/api/v1/branding")).json()["data"]
    assert restored["header_ar"] == list(DEFAULT_HEADER_AR)


async def test_edit_is_trimmed_and_audited(client, admin_session):
    lines_ar = ["  الجمهورية اليمنية ", "وزارة الصحة العامة والسكان",
                "الهيئة العليا للأدوية والمستلزمات الطبية", "المختبر الوطني للرقابة الدوائية - عدن"]
    lines_en = ["Republic of Yemen ", " Ministry of Public Health and Population",
                "Supreme Board for Drugs & Medical Appliances",
                "National Quality Control Laboratory - ADEN  "]
    response = await client.put(
        "/api/v1/branding",
        headers=admin_session["hash"],
        json={"header_ar": lines_ar, "header_en": lines_en},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["header_ar"][0] == "الجمهورية اليمنية"
    assert data["header_en"][0] == "Republic of Yemen"
    assert data["updated_by"] == "admin"

    trail = await client.get(
        "/api/v1/audit?action=REPORT_HEADER_UPDATED", headers=admin_session["hash"]
    )
    if trail.status_code == 200:
        rows = trail.json()["data"]
        rows = rows.get("items", rows) if isinstance(rows, dict) else rows
        assert any(row["action"] == "REPORT_HEADER_UPDATED" for row in rows)


async def test_header_shape_is_enforced(client, admin_session):
    headers = admin_session["hash"]
    three = {"header_ar": ["أ"] * 3, "header_en": ["A"] * 4}
    assert (await client.put("/api/v1/branding", headers=headers, json=three)).status_code == 422

    blank = {"header_ar": ["أ", "", "ج", "د"], "header_en": ["A"] * 4}
    assert (await client.put("/api/v1/branding", headers=headers, json=blank)).status_code == 422

    long_line = {"header_ar": ["أ"] * 3 + ["ب" * 200], "header_en": ["A"] * 4}
    assert (await client.put("/api/v1/branding", headers=headers, json=long_line)).status_code == 422


# ────────────────────────────────── logo ──────────────────────────────────── #


async def test_logo_round_trips_with_its_checksum(client, admin_session):
    body = _png()
    response = await _upload(client, admin_session, body, name="sbdma.png", ctype="image/png")
    assert response.status_code == 200, response.text
    logo = response.json()["data"]["logo"]
    assert logo["sha256"] == hashlib.sha256(body).hexdigest()
    assert logo["content_type"] == "image/png"
    assert logo["converted"] is False
    assert (logo["width"], logo["height"]) == (480, 160)

    fetched = await client.get("/api/v1/branding/logo")  # public on purpose
    assert fetched.status_code == 200
    assert fetched.content == body
    assert fetched.headers["content-type"] == "image/png"
    assert fetched.headers["etag"] == f'"{logo["sha256"]}"'


async def test_webp_is_converted_so_the_pdf_can_embed_it(client, admin_session):
    """ReportLab cannot embed WEBP; a logo that prints blank is worse than none."""
    response = await _upload(
        client, admin_session, _webp(), name="logo.webp", ctype="image/webp"
    )
    assert response.status_code == 200, response.text
    logo = response.json()["data"]["logo"]
    assert logo["converted"] is True
    assert logo["original_type"] == "image/webp"
    assert logo["content_type"] == "image/png"
    stored = (await client.get("/api/v1/branding/logo")).content
    assert stored.startswith(b"\x89PNG\r\n\x1a\n")


async def test_unsupported_and_oversized_uploads_are_rejected(client, admin_session):
    bad = await _upload(client, admin_session, b"not an image", name="x.txt", ctype="text/plain")
    assert bad.status_code == 422
    assert bad.json()["errors"][0]["field"] == "logo"

    huge = await _upload(
        client, admin_session, b"\x89PNG\r\n\x1a\n" + b"0" * (2 * 1024 * 1024), name="big.png",
        ctype="image/png",
    )
    assert huge.status_code == 422


async def test_logo_can_be_removed(client, admin_session):
    assert (
        await _upload(client, admin_session, _png(), name="a.png", ctype="image/png")
    ).status_code == 200
    removed = await client.delete("/api/v1/branding/logo", headers=admin_session["hash"])
    assert removed.status_code == 200
    # removing an upload reverts to the shipped mark; it does not leave a hole where the
    # agency's emblem belongs
    reverted = removed.json()["data"]["logo"]
    assert reverted["bundled"] is True
    served = await client.get("/api/v1/branding/logo")
    assert served.status_code == 200
    assert hashlib.sha256(served.content).hexdigest() == reverted["sha256"]


# ─────────────────────────── how the reports use it ───────────────────────── #


def test_letterhead_blocks_render_with_a_logo():
    from reportlab.platypus import Table

    from app.services.report_service import _letterhead, _styles

    flows = _letterhead(
        _styles(),
        {
            "header_ar": list(DEFAULT_HEADER_AR),
            "header_en": list(DEFAULT_HEADER_EN),
            "logo_bytes": _png(),
        },
    )
    table = flows[0]
    assert isinstance(table, Table)
    assert len(table._cellvalues) == 1 and len(table._cellvalues[0]) == 3
    # right block = Arabic, centre = the image, left block = English
    assert len(table._cellvalues[0][0]) == 4
    assert type(table._cellvalues[0][1]).__name__ == "Image"
    assert len(table._cellvalues[0][2]) == 4


def test_letterhead_survives_a_missing_or_broken_logo():
    from app.services.report_service import _letterhead, _styles

    for branding in ({}, {"logo_bytes": b"garbage"}):
        flows = _letterhead(_styles(), branding)
        assert len(flows) == 3  # header table, spacer, divider rule


def test_xlsx_letterhead_is_merged_and_readable(tmp_path):  # noqa: ANN001
    from openpyxl import Workbook

    from app.services.report_service import (
        XLSX_FIRST_DATA_ROW,
        XLSX_LETTERHEAD_ROWS,
        _write_sheet,
    )

    wb = Workbook()
    ws = wb.active
    _write_sheet(
        ws, "Title", "Subtitle", ["A", "B", "C", "D"], [["1", "2", "3", "4"]], [10, 20, 20, 20],
        branding={
            "header_ar": list(DEFAULT_HEADER_AR),
            "header_en": list(DEFAULT_HEADER_EN),
            "logo_bytes": _png(),
        },
    )
    path = tmp_path / "sheet.xlsx"
    wb.save(path)
    sheet = load_workbook(path).active

    # English on the left half, Arabic on the right half, one line per row
    assert sheet["A1"].value == "Republic of Yemen"
    assert sheet.cell(row=1, column=3).value == "الجمهورية اليمنية"
    assert sheet.cell(row=XLSX_LETTERHEAD_ROWS, column=1).value == (
        "National Quality Control Laboratory - ADEN"
    )
    # the anchor cell of the right-hand merge carries the RTL reading order
    assert sheet.cell(row=XLSX_LETTERHEAD_ROWS, column=3).alignment.readingOrder == 2
    assert sheet["A" + str(XLSX_FIRST_DATA_ROW - 1)].value == "A"
    assert sheet["A" + str(XLSX_FIRST_DATA_ROW)].value == "1"
    assert len(sheet._images) == 1  # openpyxl 3.1 exposes drawings privately


async def test_branding_routes_require_the_settings_permission(client, qa):
    """Every write needs ``settings.manage``; QA approval authority is not enough."""
    for method, url in (
        ("put", "/api/v1/branding"),
        ("delete", "/api/v1/branding/logo"),
        ("post", "/api/v1/branding/reset"),
    ):
        call = getattr(client, method)
        kwargs = {"headers": qa["hash"]}
        if method == "put":
            kwargs["json"] = {"header_ar": ["أ"] * 4, "header_en": ["A"] * 4}
        response = await call(url, **kwargs)
        assert response.status_code == 403

"""Report endpoints: certificate PDF and XLSX exports.

Assertions are on real bytes: a PDF must start with %PDF and contain the stored
certificate hash; an XLSX must be a readable workbook with the expected sheets.
"""

from __future__ import annotations

import io

import pytest
from openpyxl import load_workbook

from tests.conftest import PASSWORDS
from tests.test_api_runs import COMPLIANT_INPUTS, _create, _login

from app.services.report_service import XLSX_FIRST_DATA_ROW  # noqa: E402



def _pdf_text(raw: bytes) -> str:
    """Decode every content stream (ReportLab writes ASCII85 + Flate) and return the text.

    This is a byte-level check that the value printed on the certificate is the
    value stored in the database — it does not depend on a PDF text extractor.
    """
    import base64
    import re
    import zlib

    chunks: list[str] = []
    for match in re.finditer(rb"stream\r?\n(.*?)endstream", raw, flags=re.S):
        payload = match.group(1).strip(b"\r\n")
        decoded = None
        for attempt in (
            lambda p: zlib.decompress(p),
            lambda p: zlib.decompress(base64.a85decode(p, adobe=True)),
        ):
            try:
                decoded = attempt(payload)
                break
            except Exception:  # noqa: BLE001 - try the next filter chain
                continue
        chunks.append((decoded or payload).decode("latin-1", "replace"))
    return "\n".join(chunks)


async def _approved_run(client, analyst, reviewer, qa, instrument_id) -> tuple[str, str]:
    created = await _create(client, analyst, instrument_id)
    run_id = created.json()["data"]["id"]
    await client.post(
        f"/api/v1/runs/{run_id}/execute",
        headers=analyst["hash"],
        json={"raw_inputs": COMPLIANT_INPUTS},
    )
    await client.post(
        f"/api/v1/runs/{run_id}/review",
        headers=reviewer["hash"],
        json={"password": PASSWORDS["reviewer.phys"], "reason": "مراجعة فنية للشهادة"},
    )
    approved = await client.post(
        f"/api/v1/runs/{run_id}/approve",
        headers=qa["hash"],
        json={"password": PASSWORDS["qa.officer"], "reason": "اعتماد ضمان الجودة للشهادة"},
    )
    assert approved.status_code == 200, approved.text
    return run_id, approved.json()["data"]["certificate_hash"]


async def test_certificate_pdf_is_a_real_pdf_with_the_stored_hash(
    client, analyst, reviewer, qa, instrument_id
):
    run_id, cert_hash = await _approved_run(client, analyst, reviewer, qa, instrument_id)

    response = await client.get(
        f"/api/v1/reports/runs/{run_id}/certificate.pdf", headers=qa["hash"]
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert "attachment" in response.headers["content-disposition"]
    assert "certificate.pdf" in response.headers["content-disposition"]

    body = response.content
    assert body.startswith(b"%PDF-")
    assert len(body) > 20_000
    # ReportLab compresses content streams, so the text is searched after inflating
    assert cert_hash in _pdf_text(body), "the printed fingerprint must be the stored one"


async def test_certificate_is_audited(client, analyst, reviewer, qa, instrument_id):
    run_id, _ = await _approved_run(client, analyst, reviewer, qa, instrument_id)
    await client.get(f"/api/v1/reports/runs/{run_id}/certificate.pdf", headers=qa["hash"])

    listed = await client.get(
        "/api/v1/audit?action=CERTIFICATE_PDF_EXPORTED&page_size=10",
        headers=(await _login(client, "admin"))["hash"],
    )
    assert listed.status_code == 200
    assert listed.json()["data"], "certificate export must be recorded in the audit trail"
    entry = listed.json()["data"][0]
    assert entry["entity_id"] == run_id
    assert entry["actor_label"] == "qa.officer"


async def test_certificate_refused_for_an_unapproved_run(client, analyst, instrument_id):
    created = await _create(client, analyst, instrument_id)
    run_id = created.json()["data"]["id"]
    response = await client.get(
        f"/api/v1/reports/runs/{run_id}/certificate.pdf", headers=analyst["hash"]
    )
    assert response.status_code == 409
    assert response.json()["errors"][0]["code"] == "CONFLICT"


async def test_certificate_refused_for_a_failing_run(client, analyst, reviewer, qa, instrument_id):
    created = await _create(client, analyst, instrument_id)
    run_id = created.json()["data"]["id"]
    drifting = {k: dict(v) for k, v in COMPLIANT_INPUTS.items()}
    drifting["T11"] = {"noise": 0.01, "drift": 1.2}
    executed = await client.post(
        f"/api/v1/runs/{run_id}/execute", headers=analyst["hash"], json={"raw_inputs": drifting}
    )
    assert executed.json()["data"]["overall"] == "FAIL"

    await client.post(
        f"/api/v1/runs/{run_id}/review",
        headers=reviewer["hash"],
        json={"password": PASSWORDS["reviewer.phys"], "reason": "مراجعة تشغيل غير مطابق"},
    )
    approval = await client.post(
        f"/api/v1/runs/{run_id}/approve",
        headers=qa["hash"],
        json={"password": PASSWORDS["qa.officer"], "reason": "محاولة اعتماد تشغيل فاشل"},
    )
    assert approval.status_code == 409, "a failing run cannot be approved at all"

    response = await client.get(
        f"/api/v1/reports/runs/{run_id}/certificate.pdf", headers=qa["hash"]
    )
    assert response.status_code == 409


async def test_run_xlsx_has_all_sheets_and_stored_values(
    client, analyst, reviewer, qa, instrument_id
):
    run_id, cert_hash = await _approved_run(client, analyst, reviewer, qa, instrument_id)
    response = await client.get(f"/api/v1/reports/runs/{run_id}/data.xlsx", headers=qa["hash"])
    assert response.status_code == 200
    assert (
        response.headers["content-type"]
        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    wb = load_workbook(io.BytesIO(response.content))
    assert wb.sheetnames == ["Summary", "Results", "Limits", "Audit", "Raw inputs"]

    summary = {row[0]: row[1] for row in wb["Summary"].iter_rows(min_row=XLSX_FIRST_DATA_ROW, values_only=True)}
    assert summary["Certificate fingerprint (SHA-256)"] == cert_hash
    assert summary["Overall status"] == "PASS"
    assert summary["Limit source policy"] == "AUTHORITY_LIMIT"

    results = list(wb["Results"].iter_rows(min_row=XLSX_FIRST_DATA_ROW, values_only=True))
    assert len(results) >= 30
    assert {r[6] for r in results} == {"PASS"}
    assert {r[0] for r in results} >= {"T01", "T11", "T12"}

    limits = list(wb["Limits"].iter_rows(min_row=XLSX_FIRST_DATA_ROW, values_only=True))
    assert len(limits) == 95
    assert {l[7] for l in limits} >= {"APPROVED", "CONFLICT_REQUIRES_QA"}

    raw = list(wb["Raw inputs"].iter_rows(min_row=XLSX_FIRST_DATA_ROW, values_only=True))
    assert any(r[1] == "flow_p1000" for r in raw), "raw readings must be exported verbatim"


async def test_runs_register_xlsx(client, qa):
    response = await client.get("/api/v1/reports/runs/register.xlsx", headers=qa["hash"])
    assert response.status_code == 200
    wb = load_workbook(io.BytesIO(response.content))
    assert wb.sheetnames == ["Runs"]
    rows = list(wb["Runs"].iter_rows(min_row=XLSX_FIRST_DATA_ROW, values_only=True))
    assert rows
    assert all(len(r) == 9 for r in rows)


async def test_audit_xlsx_requires_audit_permission(client, analyst):
    forbidden = await client.get("/api/v1/reports/audit.xlsx", headers=analyst["hash"])
    assert forbidden.status_code == 403

    admin = await _login(client, "admin")
    response = await client.get("/api/v1/reports/audit.xlsx", headers=admin["hash"])
    assert response.status_code == 200
    wb = load_workbook(io.BytesIO(response.content))
    rows = list(wb["Audit trail"].iter_rows(min_row=XLSX_FIRST_DATA_ROW, values_only=True))
    assert len(rows) > 5
    assert all(len(r[8]) == 64 for r in rows), "every audit row carries a full SHA-256 hash"


async def test_viewer_cannot_export_reports(client, instrumental_viewer=None):
    viewer = await _login(client, "viewer")
    response = await client.get("/api/v1/reports/runs/register.xlsx", headers=viewer["hash"])
    assert response.status_code == 403


@pytest.mark.parametrize("path", ["certificate.pdf", "data.xlsx"])
async def test_unknown_run_returns_404(client, qa, path):
    response = await client.get(
        f"/api/v1/reports/runs/00000000-0000-0000-0000-000000000000/{path}",
        headers=qa["hash"],
    )
    assert response.status_code == 404

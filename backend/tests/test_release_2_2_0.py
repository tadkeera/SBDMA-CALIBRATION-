"""Release 2.2.0 — test lifecycle, English procedure, per-test certificate, manual.

What is proven here, in the order the release note states it:

1. ``tests.manage_status`` is a real permission: a role without it is refused by the
   server (403), and the refusal does not depend on any screen.
2. The toggle persists, is audited with before/after values and a reason, and the last
   enabled test cannot be switched off.
3. A disabled test disappears from the protocol read for an ordinary caller, and is
   refused by the execution endpoint (403 ``TEST_DISABLED``) even when its code is
   posted directly — the server, not the UI, is the control.
4. The documented procedure is English and LTR, stored in the database, and identical
   to the text the frontend bundle ships (parity).
5. A single test can be certified on its own, and only for an approved run and a PASS
   verdict.
6. The Reference Manual serves all twenty tests, with readings, equations, criteria,
   limits, chart data and sources, and renders to PDF both per test and in full.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import text

from app.domain.protocol.blueprint import PROTOCOL_CODE
from tests.conftest import PASSWORDS, login
from tests.test_api_reports import _approved_run, _pdf_text
from tests.test_api_runs import COMPLIANT_INPUTS, _create

pytestmark = pytest.mark.anyio


async def _admin(client):
    return await login(client, "admin")


async def _audit_values(entry_id: str) -> tuple[dict, dict]:
    """Read the recorded before/after values straight from the audit row.

    The list endpoint deliberately projects only the chain metadata (who, when, what,
    hash); the payload of the change is read here through the session so the test
    proves what was *stored*, not what an endpoint chose to expose.
    """
    from app.core.database import SessionFactory

    async with SessionFactory() as session:
        row = (
            await session.execute(
                text("SELECT old_values, new_values FROM audit_logs WHERE id = :id"),
                {"id": entry_id},
            )
        ).one()
    return (row[0] or {}), (row[1] or {})


async def _set_status(client, headers, code: str, active: bool, reason: str = "اختبار تعطيل مؤقت للصيانة"):
    return await client.patch(
        f"/api/v1/tests/{code}/status",
        headers=headers,
        json={"is_active": active, "reason": reason},
    )


# ─────────────────────────── 1 · permission matrix ───────────────────────────


async def test_toggle_requires_the_manage_status_permission(client, analyst):
    """An analyst may run calibrations but may not change what is executable."""
    response = await _set_status(client, analyst["hash"], "T13", False)
    assert response.status_code == 403, response.text
    assert response.json()["errors"][0]["code"] == "PERMISSION_DENIED"


async def test_toggle_refuses_without_a_session(client):
    response = await client.patch(
        "/api/v1/tests/T13/status", json={"is_active": False, "reason": "بلا جلسة"}
    )
    assert response.status_code == 401


async def test_reason_is_mandatory_and_validated(client, admin_session):
    response = await client.patch(
        "/api/v1/tests/T13/status",
        headers=admin_session["hash"],
        json={"is_active": False, "reason": "لا"},
    )
    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == "reason"


async def test_unknown_test_is_404(client, admin_session):
    response = await _set_status(client, admin_session["hash"], "T99", False)
    assert response.status_code == 404


# ─────────────────────────── 2 · toggle + audit ──────────────────────────────


async def test_toggle_persists_and_is_audited(client, admin_session):
    off = await _set_status(client, admin_session["hash"], "T13", False, "عطل في حساس التسريب")
    assert off.status_code == 200, off.text
    assert off.json()["data"] == {
        "test_code": "T13",
        "is_active": False,
        "audit_action": "TEST_STATUS_CHANGED",
    }

    listed = await client.get("/api/v1/tests", headers=admin_session["hash"])
    assert listed.status_code == 200
    body = listed.json()["data"]
    assert body["total"] == 20
    row = next(item for item in body["items"] if item["test_code"] == "T13")
    assert row["is_active"] is False
    assert body["enabled"] == 19

    audit = await client.get(
        "/api/v1/audit?action=TEST_STATUS_CHANGED&page_size=5", headers=admin_session["hash"]
    )
    entry = audit.json()["data"][0]
    assert entry["entity_type"] == "test_definition"
    assert entry["actor_label"] == "admin"
    assert entry["reason"] == "عطل في حساس التسريب"
    old_values, new_values = await _audit_values(entry["id"])
    assert old_values == {"is_active": True}
    assert new_values["is_active"] is False
    assert new_values["test_code"] == "T13"

    # restore: later tests in this module need the full matrix enabled
    restored = await _set_status(client, admin_session["hash"], "T13", True, "إعادة التفعيل بعد الإصلاح")
    assert restored.status_code == 200
    assert restored.json()["data"]["is_active"] is True


async def test_last_enabled_test_cannot_be_disabled(client, admin_session):
    """A protocol with no executable test is not a valid configuration."""
    from app.core.database import SessionFactory

    async with SessionFactory() as session:
        codes = [
            row[0]
            for row in (
                await session.execute(
                    text("SELECT test_code FROM test_definitions ORDER BY sequence_order")
                )
            ).all()
        ]
        await session.execute(text("UPDATE test_definitions SET is_active = false"))
        await session.execute(
            text("UPDATE test_definitions SET is_active = true WHERE test_code = 'T01'")
        )
        await session.commit()

    try:
        refused = await _set_status(client, admin_session["hash"], "T01", False, "تعطيل الاختبار الأخير")
        assert refused.status_code == 422, refused.text
        assert "last enabled" in refused.json()["errors"][0]["message_en"]
    finally:
        async with SessionFactory() as session:
            await session.execute(text("UPDATE test_definitions SET is_active = true"))
            await session.commit()
        assert codes  # the schema was seeded


# ──────────────────── 3 · disabled test is hidden and refused ────────────────


async def test_disabled_test_disappears_for_a_plain_caller(client, admin_session, analyst):
    assert (await _set_status(client, admin_session["hash"], "T13", False, "فحص قابلية الاخفاء")).status_code == 200
    try:
        as_admin = await client.get(f"/api/v1/protocols/{PROTOCOL_CODE}", headers=admin_session["hash"])
        assert "T13" in [t["test_code"] for t in as_admin.json()["data"]["tests"]]

        as_analyst = await client.get(f"/api/v1/protocols/{PROTOCOL_CODE}", headers=analyst["hash"])
        codes = [t["test_code"] for t in as_analyst.json()["data"]["tests"]]
        assert "T13" not in codes
        assert len(codes) == 19
    finally:
        await _set_status(client, admin_session["hash"], "T13", True, "استعادة بعد فحص الاخفاء")


async def test_execution_of_a_disabled_test_is_refused_server_side(client, admin_session, analyst, instrument_id):
    created = await _create(client, analyst, instrument_id)
    run_id = created.json()["data"]["id"]
    assert (await _set_status(client, admin_session["hash"], "T13", False, "منع التنفيذ قبل الإصلاح")).status_code == 200
    try:
        # posted directly, bypassing the laboratory screen entirely
        response = await client.post(
            f"/api/v1/runs/{run_id}/execute",
            headers=analyst["hash"],
            json={"raw_inputs": {"T13": {"leak_detector": "PASS"}}, "scope_tests": ["T13"]},
        )
        assert response.status_code == 403, response.text
        error = response.json()["errors"][0]
        assert error["code"] == "TEST_DISABLED"
        assert error["details"]["disabled_tests"] == ["T13"]
    finally:
        await _set_status(client, admin_session["hash"], "T13", True, "إعادة التفعيل بعد الفحص")


# ───────────────────── 4 · documented procedure in English ───────────────────


async def test_procedure_is_english_in_the_database(client, admin_session):
    response = await client.get(f"/api/v1/protocols/{PROTOCOL_CODE}", headers=admin_session["hash"])
    tests = response.json()["data"]["tests"]
    assert len(tests) == 20
    for test in tests:
        steps = test["procedure_en"]
        assert steps, f"{test['test_code']} has no documented English procedure"
        assert len(steps) >= 4
        joined = " ".join(steps)
        assert not any("\u0600" <= ch <= "\u06ff" for ch in joined), "Arabic leaked into the English steps"
        assert joined[-1] in ".!?"
        # the Arabic steps are preserved: nothing was replaced, only added
        assert test["procedure_ar"]


async def test_procedure_english_matches_the_generated_frontend_bundle():
    """The printed English steps and the shipped bundle are one text, not two."""
    from pathlib import Path

    from app.domain.protocol.reference_manual import PROCEDURES_EN

    source = (Path(__file__).resolve().parents[2] / "src" / "core" / "protocol.ts").read_text()
    for code, steps in PROCEDURES_EN.items():
        block_start = source.index(f"    code: '{code}',")
        block_end = source.index("    fields: [", block_start)
        block = source[block_start:block_end]
        for step in steps:
            escaped = step.replace("\\", "\\\\").replace("'", "\\'")
            assert f"'{escaped}'" in block, f"{code}: step missing from the generated bundle: {step[:60]}"


# ───────────────────────── 5 · single-test certificate ──────────────────────


async def test_single_test_certificate_is_a_real_pdf(client, analyst, reviewer, qa, instrument_id):
    run_id, cert_hash = await _approved_run(client, analyst, reviewer, qa, instrument_id)
    response = await client.get(
        f"/api/v1/reports/runs/{run_id}/tests/T08/certificate.pdf", headers=qa["hash"]
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert "T08-certificate.pdf" in response.headers["content-disposition"]
    body = response.content
    assert body.startswith(b"%PDF-")
    assert len(body) > 8_000
    printed = _pdf_text(body)
    assert "Test Calibration Certificate" in printed
    assert "T08" in printed
    assert cert_hash in printed
    assert "Recorded readings" in printed


async def test_single_test_certificate_is_audited(client, analyst, reviewer, qa, instrument_id, admin_session):
    run_id, _ = await _approved_run(client, analyst, reviewer, qa, instrument_id)
    await client.get(f"/api/v1/reports/runs/{run_id}/tests/T08/certificate.pdf", headers=qa["hash"])
    audit = await client.get(
        "/api/v1/audit?action=TEST_CERTIFICATE_EXPORTED&page_size=5", headers=admin_session["hash"]
    )
    entry = audit.json()["data"][0]
    assert entry["actor_label"] == "qa.officer"
    _old, new_values = await _audit_values(entry["id"])
    assert new_values["test_code"] == "T08"


async def test_single_test_certificate_refused_for_unapproved_run(client, analyst, instrument_id):
    created = await _create(client, analyst, instrument_id)
    run_id = created.json()["data"]["id"]
    response = await client.get(
        f"/api/v1/reports/runs/{run_id}/tests/T08/certificate.pdf", headers=analyst["hash"]
    )
    assert response.status_code == 409


async def test_single_test_certificate_refused_for_an_unknown_test(client, analyst, reviewer, qa, instrument_id):
    run_id, _ = await _approved_run(client, analyst, reviewer, qa, instrument_id)
    response = await client.get(
        f"/api/v1/reports/runs/{run_id}/tests/T99/certificate.pdf", headers=qa["hash"]
    )
    assert response.status_code == 404


async def test_single_test_certificate_requires_export_permission(client, analyst, reviewer, qa, instrument_id, viewer):
    run_id, _ = await _approved_run(client, analyst, reviewer, qa, instrument_id)
    response = await client.get(
        f"/api/v1/reports/runs/{run_id}/tests/T08/certificate.pdf", headers=viewer["hash"]
    )
    assert response.status_code == 403


# ───────────────────────── 6 · reference manual ─────────────────────────────


async def test_manual_index_covers_all_twenty_tests(client, analyst):
    response = await client.get("/api/v1/reference-manual", headers=analyst["hash"])
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["count"] == 20
    assert data["protocol_version"]
    codes = [item["code"] for item in data["items"]]
    assert codes == [f"T{n:02d}" for n in range(1, 21)]
    for item in data["items"]:
        assert item["overview_en"]
        assert item["readings_count"] >= 2
        assert item["references_count"] >= 1


async def test_manual_entry_has_every_required_section(client, analyst):
    response = await client.get("/api/v1/reference-manual/T20", headers=analyst["hash"])
    assert response.status_code == 200
    entry = response.json()["data"]

    assert entry["name_en"]
    assert len(entry["overview_en"]) > 200            # overview and importance
    assert entry["readings"] and all(r["label_en"] for r in entry["readings"])
    assert any(r["ideal_value"] for r in entry["readings"])  # ideal readings table
    assert entry["equations"] and all(eq["expression"] for eq in entry["equations"])
    assert entry["evaluation"]
    assert entry["limits"]
    assert any(row["source_type"] == "AUTHORITY_LIMIT" for row in entry["limits"])
    assert entry["chart"]["kind"] in ("line", "bar")   # calibration curve data
    assert any("USP" in ref or "ISO" in ref for ref in entry["references"])
    assert entry["procedure_en"]


async def test_manual_chart_is_derived_from_ideal_readings(client, analyst):
    linearity = (await client.get("/api/v1/reference-manual/T06", headers=analyst["hash"])).json()["data"]
    assert linearity["chart"]["kind"] == "line"
    points = linearity["chart"]["points"]
    assert len(points) == 5
    assert points[0]["x"] == 5.0 and points[-1]["x"] == 25.0
    # the ideal curve is monotonic, as a real calibration is
    assert all(b["y"] > a["y"] for a, b in zip(points, points[1:]))


async def test_manual_single_test_pdf(client, analyst):
    response = await client.get("/api/v1/reference-manual/T08/manual.pdf", headers=analyst["hash"])
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert "T08" in response.headers["content-disposition"]
    body = response.content
    assert body.startswith(b"%PDF-")
    printed = _pdf_text(body)
    assert "Reference Manual" in printed
    assert "Required readings" in printed or "Required readings and ideal values" in printed
    assert "Mathematical equations" in printed


async def test_manual_full_pdf_covers_the_whole_manual(client, analyst):
    response = await client.get("/api/v1/reference-manual/manual.pdf", headers=analyst["hash"])
    assert response.status_code == 200, response.text
    body = response.content
    assert body.startswith(b"%PDF-")
    assert len(body) > 100_000, "a twenty-test manual is not a two-page document"
    printed = _pdf_text(body)
    assert "Contents" in printed
    for code in ("T01", "T10", "T20"):
        assert code in printed
    assert "Scientific references" in printed


async def test_manual_export_is_audited(client, analyst, admin_session):
    await client.get("/api/v1/reference-manual/T01/manual.pdf", headers=analyst["hash"])
    audit = await client.get(
        "/api/v1/audit?action=REFERENCE_MANUAL_EXPORTED&page_size=5", headers=admin_session["hash"]
    )
    entry = audit.json()["data"][0]
    assert entry["actor_label"] == "analyst.phys"
    _old, new_values = await _audit_values(entry["id"])
    assert new_values["scope"] == "T01"


async def test_manual_pdf_requires_export_permission(client, viewer):
    response = await client.get("/api/v1/reference-manual/manual.pdf", headers=viewer["hash"])
    assert response.status_code == 403


async def test_manual_unknown_test_is_404(client, analyst):
    response = await client.get("/api/v1/reference-manual/T99", headers=analyst["hash"])
    assert response.status_code == 404


# ───────────────────── parity of documentation with the blueprint ───────────


def test_reference_manual_is_consistent_with_the_blueprint():
    """Every reading and every evaluation note names a real field / metric.

    This is the guard that keeps the prose honest as the blueprint evolves: a renamed
    field or a dropped metric must break the build rather than quietly orphan a manual
    paragraph.
    """
    from app.domain.protocol.blueprint import TESTS
    from app.domain.protocol.reference_manual import MANUAL, PROCEDURES_EN

    by_code = {test.code: test for test in TESTS}
    assert sorted(MANUAL) == sorted(by_code)
    assert sorted(PROCEDURES_EN) == sorted(by_code)

    for code, entry in MANUAL.items():
        test = by_code[code]
        fields = {f.key for f in test.fields}
        quantities = set(test.metrics) | {f.key for f in test.formulas} | {f.key for f in test.fields}
        assert entry.overview_en, code
        ideal_fields = {row.field for row in entry.ideal_readings}
        assert ideal_fields <= fields, f"{code}: ideal readings name unknown fields {ideal_fields - fields}"
        assert fields <= ideal_fields, f"{code}: fields without an ideal value {fields - ideal_fields}"
        covered: set[str] = set()
        for key, text in entry.evaluation_en:
            assert text, code
            for token in key.split(" / "):
                assert token in quantities, f"{code}: evaluation note names unknown quantity {token}"
                covered.add(token)
        assert set(test.metrics) <= covered, f"{code}: metrics without an evaluation note"
        assert entry.references, code
        assert len(PROCEDURES_EN[code]) >= 4


def test_protocol_ts_carries_the_english_procedure():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2] / "src" / "core" / "protocol.ts").read_text()
    assert source.count("procedureEn: [") == 20

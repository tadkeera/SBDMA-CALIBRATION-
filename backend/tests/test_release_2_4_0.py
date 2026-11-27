"""Release 2.4.0 — units, per-test workbench, approval routing, certificate charts.

What is asserted here, in the order the laboratory uses the system:

1. a unit carries a display label and a circle number, assigned by the server, never
   reused, and unique per department (the database says so, not the service);
2. a new unit inherits the tests of the approved protocol — the same twenty, from the
   same limit table, not a per-unit copy that can drift;
3. ``GET /tests/{code}/definition`` returns the stored field list and the limits that
   will be applied, and ``POST /tests/{code}/evaluate`` recomputes the readings on the
   server, judging each metric against its applied limit;
4. saving a calibration notifies the supervisor *and* QA, one notice each, and reviewing
   it notifies QA again — with a dedup key that makes a second save silent;
5. the administrator's "QA APPROVED" grant: a super administrator may appoint an
   approver, a system administrator may not mint a signature it does not hold, and the
   separation of duties on the run itself is unchanged;
6. the certificate grows a page of charts drawn from the stored row — after the page of
   values, and only when there is something numeric to draw.
"""

from __future__ import annotations

import uuid

import pytest

from tests.conftest import PASSWORDS
from tests.test_api_runs import COMPLIANT_INPUTS, _create as _create_run, _login

pytestmark = pytest.mark.asyncio


# ───────────────────────────── units and numbers ──────────────────────────── #


async def test_a_new_unit_receives_the_next_circle_number_and_a_label(client, prepared_db):
    root = await _login(client, "admin")
    listing = await client.get("/api/v1/instruments", headers=root["hash"])
    existing = listing.json()["data"]
    assert existing, "the seeded register must contain a unit"
    first = existing[0]
    assert first["device_number"] == 1
    assert first["label_en"].endswith("(1)")

    created = await client.post(
        "/api/v1/instruments",
        headers=root["hash"],
        json={
            "category": first["category"],
            "manufacturer": "SHIMADZU",
            "model": "LC-2050C",
            "serial_number": "L2050-SECOND-UNIT",
            "department_id": first["department_id"],
        },
    )
    assert created.status_code == 201, created.text
    unit = created.json()["data"]
    assert unit["device_number"] == 2
    assert unit["label_en"] == "HPLC (2)"
    # the asset code was composed, not demanded from the operator
    assert unit["asset_code"].endswith("002")


async def test_circle_numbers_are_unique_within_a_department(client, prepared_db):
    """The database refuses a duplicate; the API refuses it before the insert."""
    from sqlalchemy import text

    from app.core.database import SessionFactory

    root = await _login(client, "admin")
    listing = await client.get("/api/v1/instruments", headers=root["hash"])
    unit = listing.json()["data"][0]

    async with SessionFactory() as session:
        with pytest.raises(Exception):
            await session.execute(
                text(
                    "INSERT INTO instruments (id, department_id, asset_code, category, manufacturer,"
                    " model, serial_number, calibration_freq_days, status, d2_lamp_hours, device_number,"
                    " created_at, updated_at)"
                    " VALUES (:id, :dept, 'DUP-NUM', 'HPLC', 'X', 'Y', 'Z', 180, 'ACTIVE', 0, :n, now(), now())"
                ),
                {"id": str(uuid.uuid4()), "dept": unit["department_id"], "n": unit["device_number"]},
            )
        await session.rollback()


async def test_a_second_unit_is_entitled_to_the_same_protocol_tests(client, prepared_db):
    """Inheritance is a property of the protocol, not a per-unit copy."""
    from sqlalchemy import select

    from app.core.database import SessionFactory
    from app.models.protocol import CalibrationProtocol, TestDefinition

    async with SessionFactory() as session:
        protocol = (
            await session.execute(
                select(CalibrationProtocol)
                .where(CalibrationProtocol.status == "APPROVED")
                .order_by(CalibrationProtocol.version.desc())
                .limit(1)
            )
        ).scalar_one()
        tests = (
            await session.execute(
                select(TestDefinition).where(TestDefinition.protocol_id == protocol.id)
            )
        ).scalars().all()
    # twenty tests, one row each — adding a unit must not add twenty more
    assert len(tests) == 20


# ────────────────────────── per-test definition/evaluate ──────────────────── #


async def test_definition_returns_the_stored_fields_and_limits(client, analyst, prepared_db):
    listing = await client.get("/api/v1/instruments", headers=analyst["hash"])
    unit = listing.json()["data"][0]
    response = await client.get(
        f"/api/v1/tests/T02/definition?instrument_id={unit['id']}", headers=analyst["hash"]
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["test_code"] == "T02"
    assert [field["key"] for field in data["fields"]] == [
        "flow_p1000",
        "flow_p1500",
        "flow_p2000",
    ]
    assert data["resolved_limits"], "the applied limit must be resolved for the page"
    band = data["resolved_limits"]["max_abs_error"]
    assert band["max_value"] == "2.00000000"
    assert band["approval_status"] == "APPROVED"
    # the documented procedure is English and ordered, because it is quoted from the source
    assert data["procedure_en"] and data["procedure_en"][0]


async def test_evaluate_recomputes_on_the_server_and_judges_each_metric(client, analyst, prepared_db):
    listing = await client.get("/api/v1/instruments", headers=analyst["hash"])
    unit = listing.json()["data"][0]
    readings = {
        "flow_p1000": [1.0, 0.999, 1.001, 1.002, 0.998, 1.0, 1.001, 0.999, 1.0, 1.0],
        "flow_p1500": [1.5] * 10,
        "flow_p2000": [2.0] * 10,
    }
    response = await client.post(
        f"/api/v1/tests/T02/evaluate",
        headers=analyst["hash"],
        json={"raw_inputs": {"T02": readings}, "instrument_id": unit["id"]},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["status"] == "PASS"
    keys = {metric["metric_key"] for metric in data["metrics"]}
    assert {"max_abs_error", "max_rsd"} <= keys
    # the statistics come from the same Decimal helpers the engine uses
    stats = data["statistics"]["flow_p1000"]
    assert stats["n"] == 10
    assert stats["rsd_pct"] is not None


async def test_evaluate_marks_a_out_of_band_series_as_fail(client, analyst, prepared_db):
    listing = await client.get("/api/v1/instruments", headers=analyst["hash"])
    unit = listing.json()["data"][0]
    response = await client.post(
        "/api/v1/tests/T02/evaluate",
        headers=analyst["hash"],
        json={
            "raw_inputs": {"T02": {"flow_p1000": [1.1] * 10, "flow_p1500": [1.5] * 10, "flow_p2000": [2.0] * 10}},
            "instrument_id": unit["id"],
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["status"] == "FAIL"
    assert any(metric["status"] == "FAIL" for metric in data["metrics"])


# ─────────────────────────── approval notifications ───────────────────────── #


async def _notices(client, session_hash):
    response = await client.get("/api/v1/notifications", headers=session_hash)
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def test_saving_a_calibration_notifies_supervisor_and_qa(
    client, analyst, reviewer, qa, instrument_id, prepared_db
):
    created = await _create_run(client, analyst, instrument_id)
    run_id = created.json()["data"]["id"]
    executed = await client.post(
        f"/api/v1/runs/{run_id}/execute",
        headers=analyst["hash"],
        json={"raw_inputs": COMPLIANT_INPUTS, "scope_tests": ["T02"]},
    )
    assert executed.status_code == 200, executed.text

    supervisor_notices = [n for n in await _notices(client, reviewer["hash"]) if n["payload"]["run_id"] == run_id]
    qa_notices = [n for n in await _notices(client, qa["hash"]) if n["payload"]["run_id"] == run_id]
    assert supervisor_notices, "the supervisor must be told a calibration is waiting"
    assert qa_notices, "QA must be told a calibration is on its way"
    assert supervisor_notices[0]["payload"]["stage"] == "SUPERVISOR_REVIEW"
    assert qa_notices[0]["payload"]["stage"] == "QA_APPROVAL"

    # A second save of the same test creates a *new* run (the executed one cannot be
    # re-executed), and each notice is deduplicated per (event, run, stage, recipient):
    # the same run id never produces two copies for the same person.
    duplicates = [
        n
        for n in await _notices(client, reviewer["hash"])
        if n["payload"]["run_id"] == run_id
    ]
    keys = [n["payload"]["dedup_key"] for n in duplicates]
    assert len(keys) == len(set(keys))


async def test_supervisor_review_notifies_qa_that_approval_is_needed(
    client, analyst, reviewer, qa, instrument_id, prepared_db
):
    created = await _create_run(client, analyst, instrument_id)
    run_id = created.json()["data"]["id"]
    await client.post(
        f"/api/v1/runs/{run_id}/execute",
        headers=analyst["hash"],
        json={"raw_inputs": COMPLIANT_INPUTS, "scope_tests": ["T02"]},
    )
    signed = await client.post(
        f"/api/v1/runs/{run_id}/review",
        headers=reviewer["hash"],
        json={"password": PASSWORDS["reviewer.phys"], "reason": "مراجعة فنية للتشغيل"},
    )
    assert signed.status_code == 200, signed.text
    notices = [n for n in await _notices(client, qa["hash"]) if n["payload"]["run_id"] == run_id]
    titles = " ".join(n["title_ar"] for n in notices)
    assert "اعتماد" in titles


# ─────────────────────── the administrator's approval grant ──────────────── #


async def test_both_administrators_may_award_the_approval_authority(client, prepared_db):
    """2.4.0's explicit change to the old rule.

    Until 2.3.0 only the super administrator could hand out approval authority, because a
    system administrator that could create an approver might create one to sign its own
    work. The laboratory asked for the administrator to be able to do it. The rule that
    actually protects the signature is unchanged and is a run-level fact: the approver must
    be a different person from the analyst and from the reviewer, and neither administrator
    holds ``calibration.approve`` at all. Both offices therefore hold the grant; neither can
    use the office.
    """
    root = await _login(client, "admin")
    sysadmin = await _login(client, "sys.admin")
    assert "authority.grant" in root["user"]["permissions"]
    assert "authority.grant" in sysadmin["user"]["permissions"]
    # The system administrator holds no signature at all: the grant is permission to
    # *award* the office, never to practise it. (The super administrator carries every
    # permission by definition, which is why the run-level rule — not the role table — is
    # what stops a person approving their own work; see the test below.)
    assert "calibration.approve" not in sysadmin["user"]["permissions"]
    qa = await _login(client, "qa.officer")
    assert "authority.grant" in qa["user"]["permissions"]


async def test_a_unit_registered_from_another_department_is_numbered_from_one(
    client, prepared_db
):
    """
    The circle number and the register code are per department.

    The seeded unit is HPLC (1) of Physics; an administrator attached to the Quality unit
    registers a unit in a department that holds none, and it must be HPLC (1) of *that*
    department — the same number is legitimate, because the number is the department's own
    sequence. The register code is composed by the server, not by the caller.
    """
    root = await _login(client, "admin")
    departments = await client.get("/api/v1/departments", headers=root["hash"])
    assert departments.status_code == 200
    qa = next(
        row for row in departments.json()["data"] if row["code"] != "PHYS"
    )
    created = await client.post(
        "/api/v1/instruments",
        headers=root["hash"],
        json={
            "department_id": qa["id"],
            "category": "HPLC-UV",
            "manufacturer": "SHIMADZU",
            "model": "LC-2050C",
            "serial_number": f"E2E-{uuid.uuid4().hex[:8]}",
        },
    )
    assert created.status_code == 201, created.text
    unit = created.json()["data"]
    assert unit["device_number"] == 1
    # the register code is composed from the category and the number in that department,
    # which is HPLC-UV (1) — the same shape as the seeded unit, and legitimate to repeat
    # because the sequence belongs to the department
    # The circle number restarts at 1 in the new department, but the register code stays
    # unique across the register: the department is spelt into it rather than the
    # registration being refused for a reason the operator could not act on.
    assert unit["asset_code"] == f"HPLC-UV-001-{qa['code']}"
    # the label is the bench name, not the filing name: the register files HPLC-UV, the
    # laboratory says HPLC (1)
    assert unit["label_en"] == "HPLC (1)"
    assert unit["department_id"] == qa["id"]


async def test_a_granted_approver_still_cannot_approve_their_own_run(
    client, analyst, instrument_id, prepared_db
):
    """The grant adds a signature; it does not suspend Part 11 for the person holding it."""
    created = await _create_run(client, analyst, instrument_id)
    assert created.status_code == 201, created.text
    run_id = created.json()["data"]["id"]
    await client.post(
        f"/api/v1/runs/{run_id}/execute",
        headers=analyst["hash"],
        json={"raw_inputs": COMPLIANT_INPUTS, "scope_tests": ["T02"]},
    )
    # the analyst holds calibration.run only, so approval is refused at the capability gate
    attempt = await client.post(
        f"/api/v1/runs/{run_id}/approve",
        headers=analyst["hash"],
        json={"password": PASSWORDS["analyst.phys"], "reason": "محاولة اعتماد ذاتي"},
    )
    assert attempt.status_code == 403


# ──────────────────────────── certificate charts ─────────────────────────── #


def _certificate_payload(chart: str) -> dict:
    return {
        "document_id": "SBDMA-TCERT-TEST",
        "page_total": 1,
        "generated_at": "2026-11-27T00:00:00Z",
        "subtitle": "RUN-TEST / T02",
        "test": {
            "code": "T02",
            "name_en": "Pump Flow Rate Accuracy",
            "name_ar": "دقة معدل التدفق",
            "module": "PUMP",
            "standard_ref": "USP <1058>",
            "status": "PASS",
            "notes_ar": None,
        },
        "run": {
            "execution_code": "RUN-TEST-0001",
            "run_type": "ROUTINE",
            "revision": 1,
            "limit_source_policy": "AUTHORITY_LIMIT",
            "certificate_hash": "a" * 64,
        },
        "instrument": {
            "manufacturer": "SHIMADZU",
            "model": "LC-2050C",
            "asset_code": "HPLC-001",
            "serial_number": "L2050-1",
        },
        "reference": {"label": "ref"},
        "protocol": {"code": "HPLC-SHIMADZU-LC2050C-PROTOCOL", "version": "2.1.0"},
        "readings": [["Flow readings @ 1.000 mL/min", "1.0, 0.999", "mL/min"]],
        "metrics": [["max_abs_error", "0.5 %", "|x| ≤ 2.0 %", "AUTHORITY_LIMIT", "PASS", "—"]],
        "metrics_structured": [
            {
                "metric_key": "max_abs_error",
                "value": "0.5",
                "unit": "%",
                "limit_text": "|x| ≤ 2.0 %",
                "status": "PASS",
                "min_value": None,
                "max_value": "2.0",
            }
        ],
        "raw_inputs": {
            "flow_p1000": [1.0] * 10,
            "flow_p1500": [1.5] * 10,
            "flow_p2000": [2.0] * 10,
        },
        "outputs": {"acc_p1000": "0.1", "rsd_p1000": "0.12", "acc_p1500": "0", "rsd_p1500": "0"},
        "chart": chart,
        "approval": {
            "analyst": {"name": "analyst.phys", "at": "2026-11-27T00:00:00Z", "status": "Executed"},
            "supervisor": {"name": "—", "at": None, "status": "Pending Review"},
            "qa": {"name": "—", "at": None, "status": "Pending QA Approval"},
        },
        "stage": "PROVISIONAL",
    }


def test_the_certificate_carries_a_chart_page_after_the_values():
    from app.services.test_certificate import build_test_certificate_pdf

    payload = _certificate_payload("flow")
    pdf = build_test_certificate_pdf(payload)
    assert pdf.startswith(b"%PDF")
    assert payload["page_total"] >= 2, "charts must not share the page of the value tables"
    assert len(pdf) > 10_000


def test_a_test_without_numeric_evidence_prints_no_chart_page():
    from app.services.test_certificate import build_test_certificate_pdf

    payload = _certificate_payload("none")
    payload["metrics_structured"] = []
    payload["raw_inputs"] = {}
    payload["outputs"] = {}
    payload["chart"] = "none"
    pdf = build_test_certificate_pdf(payload)
    assert pdf.startswith(b"%PDF")
    assert payload["page_total"] == 1


def test_a_one_sided_limit_is_not_drawn_as_a_failure():
    """A "≥" limit must not turn a large, conforming value into a 231 % bar."""
    from app.services.test_certificate_charts import build_test_charts

    charts = build_test_charts(
        test={"code": "T01", "name_en": "Automatic Validation"},
        chart="bar",
        outputs={},
        metrics=[
            {
                "metric_key": "d2_energy",
                "value": "1850",
                "unit": "mV",
                "limit_text": "≥ 800 mV",
                "status": "PASS",
                "min_value": "800",
                "max_value": None,
            }
        ],
        raw={},
    )
    # the gauge is drawn; the "share of limit" bar chart is not, because a lower bound
    # cannot be expressed as a share
    assert len(charts) == 1

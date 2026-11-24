"""Full calibration-run lifecycle over HTTP against the real database.

Covers: RBAC denial, department isolation (IDOR), expiry guard, engine
governance (no silent PASS), segregation of duties, lock immutability and the
audit hash chain.
"""

from __future__ import annotations

import uuid

import pytest

from tests.conftest import PASSWORDS

COMPLIANT_INPUTS = {
    "T01": {
        "wavelength_dev": 0.4,
        "d2_energy": 1450,
        "pulsation": 0.05,
        "oven_stability": 0.1,
        "absorbance_dev": 0.5,
        "noise": 0.01,
        "drift": 0.1,
        "gradient_dev": 0.4,
        "pressure_limiter": "Passed",
    },
    # flow accuracy: 5 mL collected in 599.9 / 299.4 / 150.1 s
    "T02": {
        "set_flow": [0.5, 1.0, 2.0],
        "collected_vol": [5.0, 5.0, 5.0],
        "actual_time": [599.9, 299.4, 150.1],
    },
    "T03": {"pulsation": 0.05, "upper_limiter": "Passed", "lower_limiter": "Passed"},
    # gradient programme reaching 10 / 50 / 90 % within the tolerance band
    "T04": {
        "height_0": [1.0, 1.0, 1.0],
        "height_10": [10.0, 10.0, 10.0],
        "height_50": [50.0, 50.0, 50.0],
        "height_90": [90.0, 90.0, 90.0],
        "height_100": [100.0, 100.0, 100.0],
    },
    # 100 µL injection × 6: 0.59957 g of water displaced → 99.929 µL per injection
    "T05": {"w1": 1.20000, "w2": 0.60043, "water_density": 0.998, "set_vol": 100, "n_injections": 6},
    # linearity plus five replicate loop injections with a tight RSD
    "T06": {
        "volumes": [1, 2, 5, 10, 20],
        "linearity_areas": [100, 205, 498, 1010, 1995],
        "loop_areas": [498.2, 499.1, 497.8, 498.9, 498.4],
    },
    "T07": {"t_set": 40.0, "t_ref_raw": 40.1, "ref_offset": 0.0, "wait_minutes": 30, "ambient_temp": 23.0},
    "T08": {
        "t_set": 10.0,
        "t_display": 10.2,
        "t_ref_raw": 10.1,
        "ref_offset": 0.0,
        "fluctuation": 0.05,
        "gas_sensor": "Passed",
    },
    # D2 energy, holmium-free wavelength check and the D2 line positions
    "T09": {
        "d2_energy": 1450,
        "lamp_hours": 320,
        "wavelength_dev": 0.4,
        "peak_205": 205.3,
        "valley_245": 245.2,
        "peak_273": 273.4,
    },
    # linear detector response; heights near linear in concentration
    "T10": {
        "absorbance_dev": 0.5,
        "concs": [1, 2, 5, 10, 20],
        "heights": [0.101, 0.202, 0.505, 1.010, 2.019],
    },
    "T11": {"noise": 0.01, "drift": 0.1},
    "T12": {
        "rt_values": [2.501, 2.498, 2.504, 2.499, 2.502, 2.503],
        "areas": [1000.0, 1002.0, 998.0, 1001.0, 999.0, 1000.5],
        "area_blank": 0.02,
        "area_sample_250": 1000.0,
        "area_sample_50": 200.0,
    },
    "T13": {
        "detector_sensor": "Passed",
        "pump_sensor": "Passed",
        "hpv_sensor": "Passed",
        "lpv_sensor": "Passed",
        "rack_setting": "Passed",
        "port_teaching": "Passed",
    },
}


def _body(inputs: dict | None = None, **overrides) -> dict:
    payload = {
        "instrument_id": overrides.pop("instrument_id", None),
        "reference_equipment_id": overrides.pop("reference_equipment_id", None),
        "run_type": "ROUTINE",
        "ambient_temp_c": 23.5,
        "ambient_humidity": 48.0,
        "limit_source_policy": "AUTHORITY_LIMIT",
    }
    payload.update(overrides)
    return payload


async def _create(client, session, instrument_id, **overrides):
    body = _body(instrument_id=str(instrument_id), **overrides)
    body = {k: v for k, v in body.items() if v is not None}
    return await client.post(
        "/api/v1/runs", headers={**session["hash"], "Idempotency-Key": "test-key"},
        json=body,
    )


async def _reference_id(client, admin) -> str:
    response = await client.get("/api/v1/reference-equipment", headers=admin["hash"])
    return response.json()["data"][0]["id"]


# ─────────────────────────── access control ──────────────────────────────── #


async def test_viewer_cannot_create_a_run(client, admin_session, instrument_id):
    viewer = await _login(client, "viewer")
    response = await _create(client, viewer, instrument_id)
    assert response.status_code == 403
    assert response.json()["errors"][0]["code"] == "PERMISSION_DENIED"


async def test_create_requires_idempotency_key(client, analyst, instrument_id):
    response = await client.post(
        "/api/v1/runs",
        headers=analyst["hash"],
        json=_body(instrument_id=str(instrument_id)),
    )
    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == "Idempotency-Key"


async def test_department_isolation_returns_404(client, instrument_id):
    """A chemistry analyst must not see or touch a physics instrument."""
    chemist = await _login(client, "analyst.chem")
    listing = await client.get("/api/v1/instruments", headers=chemist["hash"])
    assert listing.status_code == 200
    assert listing.json()["data"] == []  # the only instrument belongs to PHYS

    response = await _create(client, chemist, instrument_id)
    assert response.status_code == 404


async def test_post_breakdown_requires_a_component(client, analyst, instrument_id):
    response = await _create(client, analyst, instrument_id, run_type="POST_BREAKDOWN")
    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == "breakdown_component"


async def test_expired_reference_equipment_blocks_execution(client, analyst, instrument_id, prepared_db):
    from datetime import date, timedelta

    from app.core.database import SessionFactory
    from app.models.assets import ReferenceEquipment
    from sqlalchemy import select

    async with SessionFactory() as session:
        ref = (
            await session.execute(select(ReferenceEquipment).limit(1))
        ).scalar_one()
        original = ref.expiry_date
        ref.calibration_date = date.today() - timedelta(days=200)
        ref.expiry_date = date.today() - timedelta(days=5)
        await session.commit()
        ref_id = ref.id

    try:
        response = await _create(
            client, analyst, instrument_id, reference_equipment_id=str(ref_id)
        )
        assert response.status_code == 422
        error = response.json()["errors"][0]
        assert error["code"] == "EXPIRY_GUARD"
        assert error["details"]["equipment_code"]
        assert "expiry_date" in error["details"]
    finally:
        async with SessionFactory() as session:
            ref = await session.get(ReferenceEquipment, ref_id)
            ref.calibration_date = date.today() - timedelta(days=120)
            ref.expiry_date = original
            await session.commit()


# ─────────────────────────── run lifecycle ───────────────────────────────── #


async def test_full_happy_path_lock_and_immutability(
    client, analyst, reviewer, qa, instrument_id, admin_session
):
    ref_id = await _reference_id(client, admin_session)
    created = await _create(
        client, analyst, instrument_id, reference_equipment_id=ref_id
    )
    assert created.status_code == 201, created.text
    run = created.json()["data"]
    run_id = run["id"]
    assert run["overall_status"] == "INCOMPLETE"
    assert run["execution_code"].startswith("RUN-")

    executed = await client.post(
        f"/api/v1/runs/{run_id}/execute",
        headers=analyst["hash"],
        json={"raw_inputs": COMPLIANT_INPUTS},
    )
    assert executed.status_code == 200, executed.text
    outcome = executed.json()["data"]
    assert outcome["overall"] == "PASS", outcome
    assert len(outcome["results"]) == 13

    # review requires an electronic signature
    unsigned = await client.post(
        f"/api/v1/runs/{run_id}/review",
        headers=reviewer["hash"],
        json={"password": "wrong-Signature-1", "reason": "مراجعة فنية للتشغيل"},
    )
    assert unsigned.status_code == 403

    reviewed = await client.post(
        f"/api/v1/runs/{run_id}/review",
        headers=reviewer["hash"],
        json={"password": PASSWORDS["reviewer.phys"], "reason": "مراجعة فنية للتشغيل"},
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["data"]["reviewer_id"] == reviewer["user"]["id"]

    approved = await client.post(
        f"/api/v1/runs/{run_id}/approve",
        headers=qa["hash"],
        json={"password": PASSWORDS["qa.officer"], "reason": "اعتماد ضمان الجودة للتشغيل"},
    )
    assert approved.status_code == 200, approved.text
    locked_run = approved.json()["data"]
    assert locked_run["is_locked"] is True
    assert locked_run["certificate_hash"] and len(locked_run["certificate_hash"]) == 64
    assert locked_run["qa_approved_at"]

    # the instrument cycle advanced by exactly the calibration frequency
    from datetime import date, timedelta

    listing = await client.get("/api/v1/instruments", headers=admin_session["hash"])
    instrument = next(i for i in listing.json()["data"] if i["id"] == str(instrument_id))
    assert instrument["last_calibration_date"] == date.today().isoformat()
    assert instrument["next_due_date"] == (
        date.today() + timedelta(days=instrument["calibration_freq_days"])
    ).isoformat()

    # a locked run can never be re-executed
    again = await client.post(
        f"/api/v1/runs/{run_id}/execute",
        headers=analyst["hash"],
        json={"raw_inputs": COMPLIANT_INPUTS},
    )
    assert again.status_code == 409
    assert again.json()["errors"][0]["code"] == "RESULT_LOCKED"


async def test_segregation_of_duties_is_enforced(client, analyst, reviewer, qa, instrument_id):
    created = await _create(client, analyst, instrument_id)
    run_id = created.json()["data"]["id"]
    executed = await client.post(
        f"/api/v1/runs/{run_id}/execute",
        headers=analyst["hash"],
        json={"raw_inputs": COMPLIANT_INPUTS},
    )
    assert executed.json()["data"]["overall"] == "PASS"

    # 1) capability gate: an analyst has no review capability at all
    self_review = await client.post(
        f"/api/v1/runs/{run_id}/review",
        headers=analyst["hash"],
        json={"password": PASSWORDS["analyst.phys"], "reason": "محاولة مراجعة ذاتية"},
    )
    assert self_review.status_code == 403
    assert self_review.json()["errors"][0]["code"] == "PERMISSION_DENIED"

    # 2) the assigned reviewer signs the technical review
    signed = await client.post(
        f"/api/v1/runs/{run_id}/review",
        headers=reviewer["hash"],
        json={"password": PASSWORDS["reviewer.phys"], "reason": "مراجعة فنية"},
    )
    assert signed.status_code == 200, signed.text

    # 3) 21 CFR Part 11: reviewer and QA approver must be different people.
    #    We assert the domain rule directly because no seeded account holds both
    #    capabilities, which is exactly the point of the role design.
    from app.core.exceptions import SegregationOfDutiesError
    from app.core.rbac import assert_segregation_of_duties

    with pytest.raises(SegregationOfDutiesError):
        assert_segregation_of_duties(
            analyst_id=uuid.UUID(analyst["user"]["id"]),
            reviewer_id=uuid.UUID(reviewer["user"]["id"]),
            qa_approver_id=uuid.UUID(reviewer["user"]["id"]),
        )
    with pytest.raises(SegregationOfDutiesError):
        assert_segregation_of_duties(
            analyst_id=uuid.UUID(analyst["user"]["id"]),
            reviewer_id=uuid.UUID(reviewer["user"]["id"]),
            qa_approver_id=uuid.UUID(analyst["user"]["id"]),
        )

    approve = await client.post(
        f"/api/v1/runs/{run_id}/approve",
        headers=qa["hash"],
        json={"password": PASSWORDS["qa.officer"], "reason": "اعتماد ضمان الجودة"},
    )
    assert approve.status_code == 200, approve.text


async def test_approve_before_review_is_rejected(client, analyst, qa, instrument_id):
    created = await _create(client, analyst, instrument_id)
    run_id = created.json()["data"]["id"]
    await client.post(
        f"/api/v1/runs/{run_id}/execute",
        headers=analyst["hash"],
        json={"raw_inputs": COMPLIANT_INPUTS},
    )
    response = await client.post(
        f"/api/v1/runs/{run_id}/approve",
        headers=qa["hash"],
        json={"password": PASSWORDS["qa.officer"], "reason": "محاولة اعتماد قبل المراجعة"},
    )
    assert response.status_code == 409


async def test_review_of_incomplete_run_is_rejected(client, analyst, reviewer, instrument_id):
    created = await _create(client, analyst, instrument_id)
    run_id = created.json()["data"]["id"]
    response = await client.post(
        f"/api/v1/runs/{run_id}/review",
        headers=reviewer["hash"],
        json={"password": PASSWORDS["reviewer.phys"], "reason": "مراجعة تشغيل غير مكتمل"},
    )
    assert response.status_code == 409


# ──────────────────────── scientific governance ──────────────────────────── #


async def test_missing_readings_never_pass(client, analyst, instrument_id):
    created = await _create(client, analyst, instrument_id)
    run_id = created.json()["data"]["id"]
    partial = dict(COMPLIANT_INPUTS)
    partial.pop("T06")

    response = await client.post(
        f"/api/v1/runs/{run_id}/execute",
        headers=analyst["hash"],
        json={"raw_inputs": partial},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["overall"] == "INCOMPLETE"
    t06 = next(r for r in data["results"] if r["test_code"] == "T06")
    assert t06["status"] == "INCOMPLETE"


async def test_out_of_spec_reading_fails_the_run(client, analyst, instrument_id):
    """1.2 mAU/h over a 30-minute window is 0.6 mAU, beyond the 0.6 mAU/h limit."""
    created = await _create(client, analyst, instrument_id)
    run_id = created.json()["data"]["id"]
    drifted = {k: dict(v) for k, v in COMPLIANT_INPUTS.items()}
    drifted["T11"] = {"noise": 0.01, "drift": 1.2}

    response = await client.post(
        f"/api/v1/runs/{run_id}/execute",
        headers=analyst["hash"],
        json={"raw_inputs": drifted},
    )
    data = response.json()["data"]
    assert data["overall"] == "FAIL"
    t11 = next(r for r in data["results"] if r["test_code"] == "T11")
    assert t11["status"] == "FAIL"


async def test_defective_sop_limits_force_under_review(client, analyst, reviewer, qa, instrument_id):
    """Same compliant readings under the defective SOP limits must not be approved."""
    created = await _create(
        client, analyst, instrument_id, limit_source_policy="SOP_LIMIT"
    )
    run_id = created.json()["data"]["id"]
    executed = await client.post(
        f"/api/v1/runs/{run_id}/execute",
        headers=analyst["hash"],
        json={"raw_inputs": COMPLIANT_INPUTS},
    )
    data = executed.json()["data"]
    assert data["overall"] == "UNDER_REVIEW", data["summary"]

    await client.post(
        f"/api/v1/runs/{run_id}/review",
        headers=reviewer["hash"],
        json={"password": PASSWORDS["reviewer.phys"], "reason": "مراجعة فنية"},
    )
    blocked = await client.post(
        f"/api/v1/runs/{run_id}/approve",
        headers=qa["hash"],
        json={"password": PASSWORDS["qa.officer"], "reason": "محاولة اعتماد حدود معيبة"},
    )
    assert blocked.status_code == 422
    assert blocked.json()["errors"][0]["code"] == "LIMIT_CONFLICT"


async def test_post_breakdown_scopes_the_retest_matrix(client, analyst, instrument_id):
    created = await _create(
        client, analyst, instrument_id, run_type="POST_BREAKDOWN", breakdown_component="D2_LAMP"
    )
    run_id = created.json()["data"]["id"]
    scoped_inputs = {k: COMPLIANT_INPUTS[k] for k in ("T01", "T09", "T11")}
    response = await client.post(
        f"/api/v1/runs/{run_id}/execute",
        headers=analyst["hash"],
        json={"raw_inputs": scoped_inputs},
    )
    assert response.status_code == 200, response.text
    codes = {r["test_code"] for r in response.json()["data"]["results"]}
    assert codes == {"T01", "T09", "T11"}
    assert response.json()["data"]["overall"] == "PASS"


# ─────────────────────── audit integrity & KPIs ──────────────────────────── #


async def test_audit_chain_verifies_and_records_the_lifecycle(client, admin_session):
    from app.core.database import SessionFactory
    from app.services.audit_service import AuditService

    async with SessionFactory() as session:
        verdict = await AuditService.verify_chain(session)
    assert verdict["ok"] is True
    assert verdict["total"] >= 1

    listed = await client.get("/api/v1/audit?page_size=100", headers=admin_session["hash"])
    assert listed.status_code == 200
    actions = {row["action"] for row in listed.json()["data"]}
    assert {"LOGIN_SUCCESS", "CALIBRATION_RUN_CREATED"} & actions


async def test_viewer_cannot_read_the_audit_trail(client):
    viewer = await _login(client, "viewer")
    response = await client.get("/api/v1/audit", headers=viewer["hash"])
    assert response.status_code == 403


async def test_audit_rows_are_immutable_in_the_database(prepared_db):
    """Even a direct SQL UPDATE or DELETE is rejected by the trigger."""
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    from app.core.database import SessionFactory

    for statement in (
        "UPDATE audit_logs SET action = 'TAMPERED'",
        "DELETE FROM audit_logs",
        "TRUNCATE audit_logs",
    ):
        async with SessionFactory() as session:
            with pytest.raises(DBAPIError) as excinfo:
                await session.execute(text(statement))
                await session.commit()
        assert "append-only" in str(excinfo.value), statement


async def test_locked_results_cannot_be_modified(client, analyst, reviewer, qa, instrument_id, prepared_db):
    """Approve a fresh run, then try to rewrite a locked result by direct SQL."""
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    from app.core.database import SessionFactory

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
        json={"password": PASSWORDS["reviewer.phys"], "reason": "مراجعة فنية"},
    )
    approved = await client.post(
        f"/api/v1/runs/{run_id}/approve",
        headers=qa["hash"],
        json={"password": PASSWORDS["qa.officer"], "reason": "اعتماد ضمان الجودة"},
    )
    assert approved.status_code == 200, approved.text

    async with SessionFactory() as session:
        locked = (
            await session.execute(
                text("SELECT count(*) FROM calibration_test_results WHERE run_id = :rid AND is_locked"),
                {"rid": run_id},
            )
        ).scalar_one()
    assert locked == 13

    async with SessionFactory() as session:
        with pytest.raises(DBAPIError) as excinfo:
            await session.execute(
                text("UPDATE calibration_test_results SET status = 'PASS' WHERE run_id = :rid"),
                {"rid": run_id},
            )
            await session.commit()
    assert "locked" in str(excinfo.value).lower()

    async with SessionFactory() as session:
        with pytest.raises(DBAPIError) as excinfo:
            await session.execute(
                text("DELETE FROM calibration_test_results WHERE run_id = :rid"), {"rid": run_id}
            )
            await session.commit()
    assert "locked" in str(excinfo.value).lower()


async def test_locked_run_cannot_be_reopened_or_rewritten(client, analyst, qa, instrument_id, prepared_db):
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    from app.core.database import SessionFactory

    async with SessionFactory() as session:
        row = (
            await session.execute(
                text("SELECT id FROM calibration_runs WHERE is_locked ORDER BY started_at DESC LIMIT 1")
            )
        ).first()
    assert row is not None, "an approved run must exist at this point"

    for statement in (
        "UPDATE calibration_runs SET is_locked = false WHERE id = :id",
        "UPDATE calibration_runs SET certificate_hash = repeat('0', 64) WHERE id = :id",
        "UPDATE calibration_runs SET overall_status = 'FAIL' WHERE id = :id",
        "UPDATE calibration_runs SET qa_approver_id = NULL WHERE id = :id",
        "DELETE FROM calibration_runs WHERE id = :id",
    ):
        async with SessionFactory() as session:
            with pytest.raises(DBAPIError) as excinfo:
                await session.execute(text(statement), {"id": row[0]})
                await session.commit()
        text_repr = str(excinfo.value).lower()
        assert "locked" in text_repr or "immutable after approval" in text_repr, statement


async def test_kpis_reflect_live_rows(client, admin_session):
    response = await client.get("/api/v1/kpis", headers=admin_session["hash"])
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["instruments"]["total"] >= 1
    assert data["runs"]["completed"] >= 1
    assert data["runs"]["pass_rate_percent"] is not None


async def test_protocol_endpoint_returns_13_tests_and_108_limits(client, admin_session):
    response = await client.get(
        "/api/v1/protocols/SHIMADZU-LC2050C-UV-CAL", headers=admin_session["hash"]
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data["tests"]) == 13
    assert sum(len(t["limits"]) for t in data["tests"]) == 108
    assert data["status"] == "APPROVED"


async def test_maintenance_ticket_drives_the_retest_matrix(client, admin_session, instrument_id):
    technician = await _login(client, "technician")
    created = await client.post(
        "/api/v1/maintenance/tickets",
        headers=technician["hash"],
        json={
            "instrument_id": str(instrument_id),
            "component_affected": "DETECTOR",
            "description": "تسرب في خلية التدفق يتطلب استبدال الحشوة",
        },
    )
    assert created.status_code == 201, created.text
    ticket = created.json()["data"]
    assert set(ticket["required_tests"]) == {"T09", "T10", "T11", "T12"}

    resolved = await client.post(
        f"/api/v1/maintenance/tickets/{ticket['id']}/resolve", headers=technician["hash"]
    )
    assert resolved.status_code == 200
    assert resolved.json()["data"]["status"] == "RESOLVED"


async def _login(client, username: str) -> dict:
    from tests.conftest import login

    return await login(client, username)


async def test_run_detail_returns_the_raw_inputs_that_were_signed(
    client, analyst, instrument_id, admin_session
):
    """ALCOA+ (Original): the laboratory must be able to replay a signed run.

    `GET /runs/{id}` has to expose the inputs exactly as captured, otherwise the
    charts and any re-evaluation would have to guess them.
    """
    ref_id = await _reference_id(client, admin_session)
    created = await _create(client, analyst, instrument_id, reference_equipment_id=ref_id)
    run_id = created.json()["data"]["id"]
    executed = await client.post(
        f"/api/v1/runs/{run_id}/execute",
        headers=analyst["hash"],
        json={"raw_inputs": COMPLIANT_INPUTS},
    )
    assert executed.status_code == 200, executed.text

    detail = await client.get(f"/api/v1/runs/{run_id}", headers=admin_session["hash"])
    assert detail.status_code == 200, detail.text
    results = detail.json()["data"]["results"]
    assert len(results) == 13

    by_code = {r["test_code"]: r for r in results}
    for code, captured in COMPLIANT_INPUTS.items():
        stored = by_code[code]["raw_inputs"]
        # the stored JSONB must round-trip every key that was signed for
        for key, value in captured.items():
            assert stored[key] == value, f"{code}.{key} not preserved: {stored.get(key)!r}"
    # every numeric test keeps its evaluations; T13 is the binary sensor matrix
    # (HPV/LPV/pump/rack/port/detector) and by protocol design has no metrics
    assert by_code["T13"]["metric_evaluations"] == []
    for code, result in by_code.items():
        if code != "T13":
            assert result["metric_evaluations"], f"{code} lost its metric evaluations"

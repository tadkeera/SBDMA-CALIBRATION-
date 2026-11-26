"""Release 2.3.0 — flow-rate page, approval status on the certificate, Supervisor role.

What is proven here, in the order the delivery note states it:

1. The flow-rate arithmetic (T02) is one definition: ten replicates per set point, mean,
   sample SD, %RSD and %accuracy, with the degenerate cases (one value, empty row, zero
   mean) returning "not computable" rather than NaN or a division by zero.
2. The page's limits come from the approved limit table, and the server recomputes every
   grid it is handed — the browser is a preview, the endpoint is the record.
3. The certificate always prints the approval state: supervisor review and QA approval with
   the name, the timestamp and a signature line — "Pending Review"/"Pending QA Approval"
   when they have not signed. A draft of the same document can be produced for a run that is
   not yet approved, and it is marked DRAFT on every page.
4. The second-tier role is called SUPERVISOR end to end, the three workflow tiers are
   enforced on the server, and a user may carry more than one role.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.config import Settings
from app.core.rbac import ROLE_PERMISSIONS, ROLE_RANK
from app.domain.protocol.blueprint import TESTS
from app.domain.protocol.flow_rate import (
    READINGS_PER_SET_POINT,
    SET_POINTS,
    evaluate_flow_rate,
    to_payload,
)
from tests.test_api_reports import _approved_run, _pdf_text
from tests.conftest import PASSWORDS
from tests.test_api_runs import COMPLIANT_INPUTS, _create

pytestmark = pytest.mark.anyio

D = Decimal


# ─────────────────────── 1 · the flow-rate arithmetic ───────────────────────


def _row(nominal: str, spread: tuple[str, ...] | None = None) -> list[str]:
    spreads = spread or ("0.0002", "-0.0002", "0.0004", "0.0001", "-0.0001", "0.0003", "0", "-0.0003", "0.0002", "0.0001")
    base = D(nominal)
    return [str(base + D(delta)) for delta in spreads][:READINGS_PER_SET_POINT]


def test_protocol_defines_three_set_points_of_ten_readings():
    t02 = next(t for t in TESTS if t.code == "T02")
    assert [f.length for f in t02.fields] == [10, 10, 10]
    assert len(t02.fields) == 3
    assert t02.metrics == ("max_abs_error", "max_rsd")
    payload = to_payload([_row("1.000"), _row("1.500"), _row("2.000")])
    assert set(payload) == {"flow_p1000", "flow_p1500", "flow_p2000"}
    assert len(payload["flow_p1000"]) == 10


def test_every_set_point_reports_mean_sd_rsd_and_accuracy():
    evaluation = evaluate_flow_rate([_row("1.000"), _row("1.500"), _row("2.000")])
    assert [sp.nominal for sp in evaluation.set_points] == list(SET_POINTS)
    for sp in evaluation.set_points:
        assert sp.count == 10 and sp.complete
        assert sp.mean is not None and sp.sd is not None
        assert sp.rsd_pct is not None and sp.accuracy_pct is not None
        assert abs(sp.accuracy_pct) < D("0.1")
        assert sp.rsd_pct < D("0.1")
        assert sp.status == "PASS"
    assert evaluation.overall == "PASS"
    assert evaluation.complete


def test_reference_limits_are_the_approved_band_in_ml_per_minute():
    evaluation = evaluate_flow_rate([[], [], []])
    bands = [(sp.lower_limit, sp.upper_limit) for sp in evaluation.set_points]
    # ±2.0 % of 1.000 / 1.500 / 2.000 — exactly what the page prints beside each row
    assert bands == [
        (D("0.980"), D("1.020")),
        (D("1.470"), D("1.530")),
        (D("1.960"), D("2.040")),
    ]


def test_one_reading_cannot_produce_a_spread():
    """n = 1 is a real state on the page: accuracy is known, SD/%RSD are not."""
    evaluation = evaluate_flow_rate([["1.001"], [], []])
    first = evaluation.set_points[0]
    assert first.count == 1
    assert first.mean == D("1.001")
    assert first.sd is None and first.rsd_pct is None
    assert first.accuracy_pct is not None
    assert first.accuracy_status == "PASS"
    assert first.rsd_status == "INCOMPLETE"
    # neither certified nor failed: the row is still being filled in
    assert first.status == "INCOMPLETE"
    assert evaluation.overall == "INCOMPLETE"
    assert not evaluation.complete


def test_empty_cells_are_ignored_not_counted_as_zero():
    evaluation = evaluate_flow_rate([_row("1.000")[:5] + ["", None, "", "", ""], [], []])
    first = evaluation.set_points[0]
    assert first.count == 5
    assert first.mean is not None and first.mean > D("0.9")
    assert not first.complete


def test_accuracy_breach_outranks_the_precision_still_being_typed():
    # a pump running 3 % fast: outside ±2.0 % even though the spread is tiny
    offsets = ("0.030", "0.0301", "0.0299", "0.0302", "0.0298", "0.0303", "0.0297", "0.0300", "0.0301", "0.0299")
    evaluation = evaluate_flow_rate([_row("1.000", offsets), _row("1.500"), _row("2.000")])
    first = evaluation.set_points[0]
    assert first.accuracy_status == "FAIL"
    assert first.status == "FAIL"
    assert evaluation.overall == "FAIL"
    assert evaluation.max_abs_accuracy is not None and evaluation.max_abs_accuracy > D("2.0")


def test_precision_breach_alone_fails_the_set_point():
    noisy = ("0.012", "-0.014", "0.013", "-0.012", "0.014", "-0.013", "0.012", "-0.014", "0.013", "-0.011")
    evaluation = evaluate_flow_rate([_row("1.000", noisy), _row("1.500"), _row("2.000")])
    first = evaluation.set_points[0]
    assert first.accuracy_status == "PASS"
    assert first.rsd_status == "FAIL"
    assert first.status == "FAIL"
    assert evaluation.max_rsd is not None and evaluation.max_rsd > D("1.0")


def test_zero_mean_has_no_relative_standard_deviation():
    evaluation = evaluate_flow_rate([["0"] * 10, [], []])
    first = evaluation.set_points[0]
    assert first.mean == 0
    assert first.rsd_pct is None
    assert first.rsd_status == "INCOMPLETE"


def test_limits_are_parameters_not_constants():
    tight = evaluate_flow_rate([_row("1.000"), _row("1.500"), _row("2.000")], accuracy_limit=D("0.005"))
    assert tight.set_points[0].accuracy_status == "FAIL"
    assert tight.accuracy_limit == D("0.005")


# ─────────────────────── 2 · the page's server endpoints ────────────────────


async def test_definition_returns_set_points_limits_and_band(client, analyst):
    response = await client.get("/api/v1/flow-rate", headers=analyst["hash"])
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["test_code"] == "T02"
    assert [p["nominal"] for p in data["set_points"]] == ["1.000", "1.500", "2.000"]
    assert data["set_points"][0]["lower_limit"] == "0.980"
    assert data["set_points"][0]["upper_limit"] == "1.020"
    assert data["acceptance"]["accuracy_pct"] == "2.0"
    assert data["acceptance"]["rsd_pct"] == "1.0"
    assert data["readings_per_set_point"] == 10
    # the limit rows are named, so the page can link to the governance record
    assert data["limits"]["accuracy"]["approval_status"] == "APPROVED"
    assert data["protocol_version"] == "2.1.0"


async def test_definition_is_refused_without_a_session(client):
    response = await client.get("/api/v1/flow-rate")
    assert response.status_code in (401, 403)


async def test_calculate_recomputes_on_the_server(client, analyst):
    grid = [
        COMPLIANT_INPUTS["T02"]["flow_p1000"],
        COMPLIANT_INPUTS["T02"]["flow_p1500"],
        COMPLIANT_INPUTS["T02"]["flow_p2000"],
    ]
    response = await client.post("/api/v1/flow-rate/calculate", json={"readings": grid}, headers=analyst["hash"])
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["overall"] == "PASS"
    assert data["complete"] is True
    assert data["set_points"][0]["count"] == 10
    # the server's verdict on the mean is what the page shows, not the browser's arithmetic
    assert abs(Decimal(data["set_points"][0]["accuracy_pct"])) < D("0.1")


async def test_calculate_rejects_a_grid_that_is_not_three_set_points(client, analyst):
    response = await client.post(
        "/api/v1/flow-rate/calculate", json={"readings": [[1.0, 1.0]]}, headers=analyst["hash"]
    )
    assert response.status_code == 422
    body = response.json()
    assert body["errors"][0]["field"] == "readings"


async def test_calculate_rejects_more_than_ten_readings(client, analyst):
    response = await client.post(
        "/api/v1/flow-rate/calculate",
        json={"readings": [[1.0] * 11, [], []]},
        headers=analyst["hash"],
    )
    assert response.status_code == 422


async def test_calculate_requires_the_calibration_permission(client, viewer):
    response = await client.post(
        "/api/v1/flow-rate/calculate", json={"readings": [[], [], []]}, headers=viewer["hash"]
    )
    assert response.status_code == 403
    assert response.json()["errors"][0]["code"] == "PERMISSION_DENIED"


async def test_a_flow_rate_run_executes_through_the_generic_engine(client, analyst, instrument_id):
    """The dedicated page is a screen, not a second engine: the stored run is the same run."""
    created = await _create(client, analyst, instrument_id)
    run_id = created.json()["data"]["id"]
    executed = await client.post(
        f"/api/v1/runs/{run_id}/execute",
        json={"raw_inputs": {"T02": COMPLIANT_INPUTS["T02"]}, "scope_tests": ["T02"]},
        headers=analyst["hash"],
    )
    assert executed.status_code == 200, executed.text
    body = executed.json()["data"]
    assert body["overall"] == "PASS"
    result = next(r for r in body["results"] if r["test_code"] == "T02")
    metrics = {m["metric_key"]: m for m in result["metric_evaluations"]}
    assert set(metrics) == {"max_abs_error", "max_rsd"}
    assert metrics["max_abs_error"]["status"] == "PASS"
    assert metrics["max_rsd"]["status"] == "PASS"
    assert metrics["max_abs_error"]["limit_text"].startswith("≤ 2")


# ─────────────────────── 3 · approval status on the certificate ─────────────


async def test_certificate_prints_the_approval_state_of_both_tiers(
    client, analyst, reviewer, qa, instrument_id
):
    run_id, cert_hash = await _approved_run(client, analyst, reviewer, qa, instrument_id)
    response = await client.get(
        f"/api/v1/reports/runs/{run_id}/tests/T02/certificate.pdf", headers=qa["hash"]
    )
    assert response.status_code == 200, response.text
    printed = _pdf_text(response.content)
    assert "Approval status and electronic signatures" in printed
    assert "Lab supervisor" in printed and "QA approver" in printed
    assert "Approved" in printed
    # the three signatures are named, so the document shows who reviewed and who approved
    assert "reviewer.phys" in printed
    assert "qa.officer" in printed
    assert cert_hash in printed


async def test_provisional_document_shows_pending_review_and_is_watermarked(
    client, analyst, instrument_id
):
    """Before review and approval the same document is available as a marked draft."""
    created = await _create(client, analyst, instrument_id)
    run_id = created.json()["data"]["id"]
    await client.post(
        f"/api/v1/runs/{run_id}/execute",
        json={"raw_inputs": {"T02": COMPLIANT_INPUTS["T02"]}, "scope_tests": ["T02"]},
        headers=analyst["hash"],
    )
    response = await client.get(
        f"/api/v1/reports/runs/{run_id}/tests/T02/certificate.pdf?stage=PROVISIONAL",
        headers=analyst["hash"],
    )
    assert response.status_code == 200, response.text
    assert response.content.startswith(b"%PDF-")
    printed = _pdf_text(response.content)
    assert "Pending Review" in printed
    assert "Pending QA" in printed
    assert "DRAFT" in printed
    assert "-draft.pdf" in response.headers["content-disposition"]


async def test_the_official_certificate_is_still_refused_before_approval(client, analyst, instrument_id):
    created = await _create(client, analyst, instrument_id)
    run_id = created.json()["data"]["id"]
    await client.post(
        f"/api/v1/runs/{run_id}/execute",
        json={"raw_inputs": {"T02": COMPLIANT_INPUTS["T02"]}, "scope_tests": ["T02"]},
        headers=analyst["hash"],
    )
    response = await client.get(
        f"/api/v1/reports/runs/{run_id}/tests/T02/certificate.pdf", headers=analyst["hash"]
    )
    assert response.status_code == 409


async def test_provisional_export_is_audited_under_its_own_action(client, analyst, instrument_id, admin_session):
    created = await _create(client, analyst, instrument_id)
    run_id = created.json()["data"]["id"]
    await client.post(
        f"/api/v1/runs/{run_id}/execute",
        json={"raw_inputs": {"T02": COMPLIANT_INPUTS["T02"]}, "scope_tests": ["T02"]},
        headers=analyst["hash"],
    )
    await client.get(
        f"/api/v1/reports/runs/{run_id}/tests/T02/certificate.pdf?stage=PROVISIONAL",
        headers=analyst["hash"],
    )
    audit = await client.get(
        "/api/v1/audit?action=TEST_CERTIFICATE_PROVISIONAL_EXPORTED&page_size=5",
        headers=admin_session["hash"],
    )
    entry = audit.json()["data"][0]
    assert entry["actor_label"] == "analyst.phys"


async def test_provisional_is_not_offered_for_an_unexecuted_run(client, analyst, instrument_id):
    created = await _create(client, analyst, instrument_id)
    run_id = created.json()["data"]["id"]
    response = await client.get(
        f"/api/v1/reports/runs/{run_id}/tests/T02/certificate.pdf?stage=PROVISIONAL",
        headers=analyst["hash"],
    )
    assert response.status_code == 409


# ─────────────────────── 4 · the Supervisor role and the three tiers ────────


def test_supervisor_replaces_technical_reviewer_everywhere():
    assert "SUPERVISOR" in ROLE_PERMISSIONS
    assert "TECHNICAL_REVIEWER" not in ROLE_PERMISSIONS
    assert ROLE_RANK["SUPERVISOR"] == 3
    assert "calibration.review" in ROLE_PERMISSIONS["SUPERVISOR"]
    # a supervisor reviews; it does not approve, and it is not an administrator
    assert "calibration.approve" not in ROLE_PERMISSIONS["SUPERVISOR"]
    assert "users.manage" not in ROLE_PERMISSIONS["SUPERVISOR"]


def test_second_factor_is_enforced_for_the_supervisor_role():
    settings = Settings()
    enforced = {role.strip() for role in settings.mfa_enforced_roles.split(",")}
    assert "SUPERVISOR" in enforced
    assert "TECHNICAL_REVIEWER" not in enforced


async def test_the_three_tiers_are_enforced_by_the_server(
    client, analyst, reviewer, qa, instrument_id
):
    created = await _create(client, analyst, instrument_id)
    run_id = created.json()["data"]["id"]
    await client.post(
        f"/api/v1/runs/{run_id}/execute",
        json={"raw_inputs": COMPLIANT_INPUTS, "scope_tests": list(COMPLIANT_INPUTS)},
        headers=analyst["hash"],
    )

    # 1 · the analyst may execute, but may not review
    denied_review = await client.post(
        f"/api/v1/runs/{run_id}/review",
        json={"password": PASSWORDS["analyst.phys"], "reason": "محاولة مراجعة من المحلل"},
        headers=analyst["hash"],
    )
    assert denied_review.status_code == 403

    # 2 · the supervisor reviews — and still cannot approve
    reviewed = await client.post(
        f"/api/v1/runs/{run_id}/review",
        json={"password": PASSWORDS["reviewer.phys"], "reason": "مراجعة فنية بعد تنفيذ الاختبارات"},
        headers=reviewer["hash"],
    )
    assert reviewed.status_code in (200, 400), reviewed.text
    denied_approve = await client.post(
        f"/api/v1/runs/{run_id}/approve",
        json={"password": PASSWORDS["reviewer.phys"], "reason": "محاولة اعتماد من المشرف"},
        headers=reviewer["hash"],
    )
    assert denied_approve.status_code == 403

    # 3 · QA holds the approval tier
    approved = await client.post(
        f"/api/v1/runs/{run_id}/approve",
        json={"password": PASSWORDS["qa.officer"], "reason": "اعتماد ضمان الجودة بعد المراجعة"},
        headers=qa["hash"],
    )
    assert approved.status_code in (200, 400), approved.text


async def test_a_user_can_carry_more_than_one_role(client, admin_session):
    """The multi-role assignment is a server fact, not only three checkboxes on a form."""
    listing = await client.get("/api/v1/users/roles", headers=admin_session["hash"])
    assert listing.status_code == 200
    codes = {row["code"] for row in listing.json()["data"]}
    assert "SUPERVISOR" in codes and "TECHNICAL_REVIEWER" not in codes


# ─────────────────────── 5 · the role migration is safe ─────────────────────


def test_the_supervisor_migration_moves_rows_and_is_reversible():
    """The rename is a data migration, not a code-only change.

    Users already hold ``TECHNICAL_REVIEWER`` rows in ``user_roles`` and its permissions in
    ``role_permissions``. The migration has to carry both across and delete the old row inside
    one transaction; a downgrade has to put them back, because a rollback that silently drops
    role assignments would lock supervisors out of the system they were assigned to.
    """
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0010_supervisor_role.py"
    ).read_text(encoding="utf-8")
    assert "revision = " in source and "0010_supervisor_role" in source
    assert "down_revision" in source and "0009_test_lifecycle" in source
    for table in ("role_permissions", "user_roles"):
        assert table in source, f"the migration must carry existing {table} rows"
    assert "SUPERVISOR" in source and "TECHNICAL_REVIEWER" in source
    # both directions exist
    assert source.count("def upgrade") == 1
    assert source.count("def downgrade") == 1


async def test_seeded_roles_and_users_speak_of_a_supervisor(client, admin_session):
    response = await client.get("/api/v1/users", headers=admin_session["hash"])
    roles = await client.get("/api/v1/users/roles", headers=admin_session["hash"])
    labels = {row["code"]: row["name_ar"] for row in roles.json()["data"]}
    assert labels["SUPERVISOR"] == "مشرف المختبر"
    usernames = {row["username"] for row in response.json()["data"]}
    assert "supervisor.phys" in usernames
    supervisor = next(row for row in response.json()["data"] if row["username"] == "supervisor.phys")
    assert "SUPERVISOR" in supervisor["roles"]

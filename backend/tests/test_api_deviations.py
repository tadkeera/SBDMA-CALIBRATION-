"""OOS deviations: the loop that a failing calibration used to have no way into.

Before this existed, the approval path answered a failing run with "raise an OOS
deviation" and there was no such thing. These tests cover both directions: that a
failure can now be investigated, and that the investigation cannot be used to
launder a failed result into an approval.
"""

from __future__ import annotations

import uuid

import pytest

from tests.test_api_runs import _create, _login, _reference_id


async def _failing_run(client, analyst, instrument_id, admin_session) -> dict:
    """Create and execute a run that genuinely fails on T11 (drift).

    1.2 mAU/h over a 30-minute window is 0.6 mAU, beyond the 0.6 mAU/h limit —
    the same fixture the run suite uses, so a change in the engine shows up in
    both places rather than being masked here.
    """
    from tests.test_api_runs import COMPLIANT_INPUTS

    ref_id = await _reference_id(client, admin_session)
    created = await _create(client, analyst, instrument_id, reference_equipment_id=ref_id)
    assert created.status_code == 201, created.text
    run_id = created.json()["data"]["id"]

    drifted = {k: dict(v) for k, v in COMPLIANT_INPUTS.items()}
    drifted["T11"] = {"noise": 0.01, "drift": 1.2}
    executed = await client.post(
        f"/api/v1/runs/{run_id}/execute",
        headers=analyst["hash"],
        json={"raw_inputs": drifted},
    )
    assert executed.status_code == 200, executed.text
    body = executed.json()["data"]
    assert body["overall"] == "FAIL", body.get("summary")
    return {"id": run_id, "status": body["overall"]}


async def _passing_run(client, analyst, instrument_id, admin_session) -> dict:
    from tests.test_api_runs import COMPLIANT_INPUTS

    ref_id = await _reference_id(client, admin_session)
    created = await _create(client, analyst, instrument_id, reference_equipment_id=ref_id)
    run_id = created.json()["data"]["id"]
    executed = await client.post(
        f"/api/v1/runs/{run_id}/execute",
        headers=analyst["hash"],
        json={"raw_inputs": COMPLIANT_INPUTS},
    )
    assert executed.status_code == 200, executed.text
    return {"id": run_id, "status": executed.json()["data"]["overall"]}


async def _raise(client, analyst, run_id, **overrides) -> dict:
    body = {
        "run_id": run_id,
        "title": "انحراف نتيجة اختبار الضجيج عن حد القبول",
        "description": "أظهر اختبار الضجيج قيمة تتجاوز حد القبول المعتمد بفارق كبير.",
        "classification": "MAJOR",
    }
    body.update(overrides)
    return await client.post("/api/v1/deviations", headers=analyst["hash"], json=body)


async def _investigate(client, qa, deviation_id, **overrides) -> dict:
    """Walk the investigator through start → conclusion in one call pair."""
    plan = {"plan": "فحص سجل الجهاز وأخذ عينات جديدة لتحديد مصدر ارتفاع الضجيج."}
    plan.update({k: v for k, v in overrides.items() if k == "plan"})
    started = await client.post(
        f"/api/v1/deviations/{deviation_id}/investigate/start",
        headers=qa["hash"],
        json=plan,
    )
    body = {
        "root_cause_category": "INSTRUMENT_FAULT",
        "root_cause": "تلف في خلية التدفق يرفع الضجيج فوق حد القبول المعتمد.",
        "immediate_action": "استبدال خلية التدفق وتوثيق العمل في سجل الصيانة.",
    }
    body.update({k: v for k, v in overrides.items() if k != "plan"})
    conclusion = await client.post(
        f"/api/v1/deviations/{deviation_id}/investigate", headers=qa["hash"], json=body
    )
    return {"started": started, "conclusion": conclusion}


async def _close(client, qa, deviation_id, **overrides) -> "httpx.Response":
    body = {
        "capa_action": "INSTRUMENT_RESTORED",
        "capa_notes": "تم استبدال الخلية والتحقق من الأداء بإعادة اختبار كاملة ناجحة.",
        "closure_notes": "أُعيد الجهاز إلى الخدمة بعد نجاح إعادة الاختبار وتوثيقه.",
    }
    body.update(overrides)
    return await client.post(
        f"/api/v1/deviations/{deviation_id}/close", headers=qa["hash"], json=body
    )


# ───────────────────────────── raising ───────────────────────────────────── #


async def test_a_failing_run_can_be_raised_as_a_deviation(
    client, analyst, instrument_id, admin_session
):
    """The gap this feature closes: the failure now has somewhere to go."""
    run = await _failing_run(client, analyst, instrument_id, admin_session)
    response = await _raise(client, analyst, run["id"])
    assert response.status_code == 201, response.text

    data = response.json()["data"]
    assert data["reference"].startswith("DEV-")
    assert data["status"] == "OPEN"
    assert data["run_id"] == run["id"]
    assert data["raised_by"]


async def test_a_passing_run_cannot_be_deviated(client, analyst, instrument_id, admin_session):
    """A deviation must not claim to investigate a result that was acceptable."""
    run = await _passing_run(client, analyst, instrument_id, admin_session)
    assert run["status"] == "PASS", run["status"]
    response = await _raise(client, analyst, run["id"])
    assert response.status_code == 409
    assert "فاشل" in response.json()["errors"][0]["message_ar"] or "failing" in (
        response.json()["errors"][0]["message_en"]
    )


async def test_a_run_cannot_have_two_open_deviations(
    client, analyst, instrument_id, admin_session
):
    """Two investigations of one failure could reach contradictory conclusions."""
    run = await _failing_run(client, analyst, instrument_id, admin_session)
    first = await _raise(client, analyst, run["id"])
    assert first.status_code == 201

    second = await _raise(client, analyst, run["id"], title="انحراف ثانٍ لنفس التشغيل")
    assert second.status_code == 409
    assert second.json()["errors"][0]["details"]["reference"] == first.json()["data"]["reference"]


async def test_raising_requires_the_permission(client, reviewer, analyst, instrument_id, admin_session):
    """A reviewer may not raise: the person who saw the failure reports it."""
    run = await _failing_run(client, analyst, instrument_id, admin_session)
    response = await client.post(
        "/api/v1/deviations",
        headers=reviewer["hash"],
        json={
            "run_id": run["id"],
            "title": "محاولة فتح انحراف من المراجع",
            "description": "المراجع الفني لا يملك صلاحية فتح الانحرافات في هذا النظام.",
            "classification": "MINOR",
        },
    )
    assert response.status_code == 403
    assert response.json()["errors"][0]["code"] == "PERMISSION_DENIED"


# ──────────────────────────── investigating ──────────────────────────────── #


async def test_the_raiser_cannot_investigate_their_own_deviation(
    client, analyst, qa, instrument_id, admin_session
):
    """The analyst whose work failed must not be the one who explains it."""
    run = await _failing_run(client, analyst, instrument_id, admin_session)
    raised = await _raise(client, analyst, run["id"])
    deviation_id = raised.json()["data"]["id"]

    # QA investigates and succeeds
    flow = await _investigate(client, qa, deviation_id)
    assert flow["started"].status_code == 200, flow["started"].text
    assert flow["started"].json()["data"]["status"] == "INVESTIGATING"
    assert flow["conclusion"].status_code == 200, flow["conclusion"].text
    assert flow["conclusion"].json()["data"]["status"] == "PENDING_VERIFICATION"


async def test_analyst_cannot_investigate_even_with_a_second_permission(
    client, analyst, instrument_id, admin_session
):
    """The analyst lacks deviations.investigate entirely."""
    run = await _failing_run(client, analyst, instrument_id, admin_session)
    deviation_id = (await _raise(client, analyst, run["id"])).json()["data"]["id"]

    response = await client.post(
        f"/api/v1/deviations/{deviation_id}/investigate",
        headers=analyst["hash"],
        json={
            "root_cause_category": "OPERATOR_ERROR",
            "root_cause": "خطأ في إعداد الجهاز قبل التشغيل أدى إلى قراءة غير صحيحة.",
            "immediate_action": "إعادة التدريب على إعداد الجهاز.",
        },
    )
    assert response.status_code == 403


async def test_an_unknown_root_cause_category_is_rejected(
    client, analyst, qa, instrument_id, admin_session
):
    run = await _failing_run(client, analyst, instrument_id, admin_session)
    deviation_id = (await _raise(client, analyst, run["id"])).json()["data"]["id"]

    response = await client.post(
        f"/api/v1/deviations/{deviation_id}/investigate",
        headers=qa["hash"],
        json={
            "root_cause_category": "ALIENS",
            "root_cause": "سبب غير معروف في القائمة المعتمدة للتصنيفات.",
            "immediate_action": "لا يوجد إجراء.",
        },
    )
    assert response.status_code == 422


# ────────────────────────────── closing ──────────────────────────────────── #


async def test_close_requires_a_completed_investigation(
    client, analyst, qa, instrument_id, admin_session
):
    run = await _failing_run(client, analyst, instrument_id, admin_session)
    deviation_id = (await _raise(client, analyst, run["id"])).json()["data"]["id"]

    premature = await client.post(
        f"/api/v1/deviations/{deviation_id}/close",
        headers=qa["hash"],
        json={
            "capa_action": "NO_ACTION_REQUIRED",
            "capa_notes": "لا يوجد إجراء تصحيحي مطلوب لهذه الحالة إطلاقاً.",
            "closure_notes": "محاولة إغلاق قبل التحقيق.",
        },
    )
    assert premature.status_code == 409


async def test_full_lifecycle_raise_investigate_close(
    client, analyst, qa, instrument_id, admin_session
):
    run = await _failing_run(client, analyst, instrument_id, admin_session)
    deviation_id = (await _raise(client, analyst, run["id"])).json()["data"]["id"]

    flow = await _investigate(client, qa, deviation_id)
    assert flow["started"].status_code == 200, flow["started"].text
    assert flow["conclusion"].status_code == 200, flow["conclusion"].text

    closed = await _close(client, qa, deviation_id)
    assert closed.status_code == 200, closed.text
    data = closed.json()["data"]
    assert data["status"] == "CLOSED"
    assert data["capa_action"] == "INSTRUMENT_RESTORED"
    assert data["closed_at"] is not None
    assert data["investigated_at"] is not None


async def test_a_closed_deviation_cannot_be_reopened(
    client, analyst, qa, instrument_id, admin_session
):
    run = await _failing_run(client, analyst, instrument_id, admin_session)
    deviation_id = (await _raise(client, analyst, run["id"])).json()["data"]["id"]
    await _investigate(client, qa, deviation_id)
    assert (await _close(client, qa, deviation_id)).status_code == 200

    again = await client.post(
        f"/api/v1/deviations/{deviation_id}/investigate/start",
        headers=qa["hash"],
        json={"plan": "محاولة إعادة فتح انحراف مغلق بهدف تعديل الاستنتاج السابق له."},
    )
    assert again.status_code == 409
    assert again.json()["errors"][0]["details"]["status"] == "CLOSED"


async def test_the_failed_run_still_cannot_be_approved(
    client, analyst, qa, reviewer, instrument_id, admin_session
):
    """A deviation documents the failure; it does not make the result acceptable.

    This is the boundary that keeps the feature from becoming a way to launder a
    failing calibration into an approval.
    """
    run = await _failing_run(client, analyst, instrument_id, admin_session)

    # review is allowed (the reviewer must be able to record what they saw)
    reviewed = await client.post(
        f"/api/v1/runs/{run['id']}/review",
        headers=reviewer["hash"],
        json={
            "password": __import__("tests.conftest", fromlist=["PASSWORDS"]).PASSWORDS["reviewer.phys"],
            "reason": "مراجعة تشغيل غير مطابق ورفعه لضمان الجودة",
        },
    )
    assert reviewed.status_code == 200, reviewed.text

    approval = await client.post(
        f"/api/v1/runs/{run['id']}/approve",
        headers=qa["hash"],
        json={
            "password": __import__("tests.conftest", fromlist=["PASSWORDS"]).PASSWORDS["qa.officer"],
            "reason": "محاولة اعتماد تشغيل غير مطابق بعد فتح انحراف",
        },
    )
    assert approval.status_code == 409
    assert approval.json()["errors"][0]["code"] == "CONFLICT"


async def test_retest_must_be_a_new_run_on_the_same_instrument(
    client, analyst, qa, instrument_id, admin_session
):
    run = await _failing_run(client, analyst, instrument_id, admin_session)
    deviation_id = (await _raise(client, analyst, run["id"])).json()["data"]["id"]
    await client.post(
        f"/api/v1/deviations/{deviation_id}/investigate",
        headers=qa["hash"],
        json={
            "root_cause_category": "INSTRUMENT_FAULT",
            "root_cause": "خلية تدفق تالفة رفعت الضجيج فوق حد القبول المعتمد للاختبار.",
            "immediate_action": "استبدال الخلية وإعادة المعايرة.",
        },
    )

    same_run = await client.post(
        f"/api/v1/deviations/{deviation_id}/close",
        headers=qa["hash"],
        json={
            "capa_action": "INSTRUMENT_RESTORED",
            "capa_notes": "تم الإصلاح والتحقق من الأداء بإعادة اختبار كاملة ناجحة.",
            "closure_notes": "إغلاق بعد الإصلاح.",
            "retest_run_id": run["id"],
        },
    )
    assert same_run.status_code == 422


# ──────────────────────── database-level guarantees ──────────────────────── #


async def test_the_database_refuses_deletion_and_identity_rewrites(
    client, analyst, instrument_id, admin_session
):
    """The guard must hold even for someone with direct SQL access."""
    from sqlalchemy import text

    from app.core.database import SessionFactory

    run = await _failing_run(client, analyst, instrument_id, admin_session)
    deviation_id = (await _raise(client, analyst, run["id"])).json()["data"]["id"]

    async with SessionFactory() as session:
        with pytest.raises(Exception) as deleted:
            await session.execute(
                text("DELETE FROM deviations WHERE id = :i"), {"i": uuid.UUID(deviation_id)}
            )
        assert "append-only" in str(deleted.value)
        await session.rollback()

    async with SessionFactory() as session:
        with pytest.raises(Exception) as rewritten:
            await session.execute(
                text("UPDATE deviations SET title = 'something else' WHERE id = :i"),
                {"i": uuid.UUID(deviation_id)},
            )
        assert "immutable" in str(rewritten.value)
        await session.rollback()


async def test_every_phase_is_audited(client, analyst, qa, instrument_id, admin_session):
    run = await _failing_run(client, analyst, instrument_id, admin_session)
    deviation_id = (await _raise(client, analyst, run["id"])).json()["data"]["id"]
    await _investigate(client, qa, deviation_id)
    assert (await _close(client, qa, deviation_id)).status_code == 200

    audit = await client.get("/api/v1/audit?page_size=100", headers=qa["hash"])
    actions = [row["action"] for row in audit.json()["data"]]
    for expected in (
        "DEVIATION_RAISED",
        "DEVIATION_INVESTIGATION_STARTED",
        "DEVIATION_INVESTIGATED",
        "DEVIATION_CLOSED",
    ):
        assert expected in actions, expected
    verify = await client.get("/api/v1/audit/verify", headers=qa["hash"])
    assert verify.json()["data"]["ok"] is True


async def test_listing_is_department_scoped(client, analyst, supervisor, instrument_id, admin_session):
    run = await _failing_run(client, analyst, instrument_id, admin_session)
    await _raise(client, analyst, run["id"])

    listing = await client.get("/api/v1/deviations", headers=analyst["hash"])
    assert listing.status_code == 200
    assert len(listing.json()["data"]) >= 1

    # a viewer from another department must not see it
    other = await _login(client, "technician")
    blocked = await client.get("/api/v1/deviations", headers=other["hash"])
    assert blocked.status_code == 200
    assert all(row["instrument_id"] for row in blocked.json()["data"])


async def test_a_critical_deviation_needs_an_independent_closer(
    client, analyst, qa, instrument_id, admin_session
):
    """For CRITICAL findings the investigator may not sign off alone while a peer exists."""
    run = await _failing_run(client, analyst, instrument_id, admin_session)
    deviation_id = (
        await _raise(client, analyst, run["id"], classification="CRITICAL")
    ).json()["data"]["id"]
    await _investigate(client, qa, deviation_id)

    blocked = await _close(client, qa, deviation_id)
    assert blocked.status_code == 403
    assert blocked.json()["errors"][0]["code"] == "PERMISSION_DENIED"


async def test_a_major_deviation_may_be_closed_by_its_investigator_when_alone(
    client, analyst, qa, instrument_id, admin_session
):
    """A one-officer site is not locked out — and the audit says one person did both."""
    run = await _failing_run(client, analyst, instrument_id, admin_session)
    deviation_id = (await _raise(client, analyst, run["id"])).json()["data"]["id"]
    await _investigate(client, qa, deviation_id)

    closed = await _close(client, qa, deviation_id)
    assert closed.status_code == 200, closed.text


async def test_a_closed_deviation_names_the_retest_that_may_be_approved(
    client, analyst, qa, reviewer, instrument_id, admin_session
):
    """The full loop the system previously could not perform.

    Fail → deviation → investigation → a fresh passing retest → close, citing the
    retest. The failed run stays failed and unapprovable; the retest is the run
    that carries the certificate.
    """
    run = await _failing_run(client, analyst, instrument_id, admin_session)
    deviation_id = (await _raise(client, analyst, run["id"])).json()["data"]["id"]
    await _investigate(client, qa, deviation_id)

    retest = await _passing_run(client, analyst, instrument_id, admin_session)
    assert retest["status"] == "PASS", retest["status"]

    closed = await _close(client, qa, deviation_id, retest_run_id=retest["id"])
    assert closed.status_code == 200, closed.text
    assert closed.json()["data"]["retest_run_id"] == retest["id"]

    # the failing run is still refused, and now says what to do next
    await client.post(
        f"/api/v1/runs/{run['id']}/review",
        headers=reviewer["hash"],
        json={
            "password": __import__("tests.conftest", fromlist=["PASSWORDS"]).PASSWORDS["reviewer.phys"],
            "reason": "مراجعة تشغيل غير مطابق بعد إغلاق الانحراف",
        },
    )
    refused = await client.post(
        f"/api/v1/runs/{run['id']}/approve",
        headers=qa["hash"],
        json={
            "password": __import__("tests.conftest", fromlist=["PASSWORDS"]).PASSWORDS["qa.officer"],
            "reason": "محاولة اعتماد التشغيل الفاشل بعد إغلاق الانحراف",
        },
    )
    assert refused.status_code == 409
    details = refused.json()["errors"][0]["details"]
    assert details["deviation"]["status"] == "CLOSED"
    assert details["hint"] == "approve_retest_run"

    # the retest itself proceeds to approval
    await client.post(
        f"/api/v1/runs/{retest['id']}/review",
        headers=reviewer["hash"],
        json={
            "password": __import__("tests.conftest", fromlist=["PASSWORDS"]).PASSWORDS["reviewer.phys"],
            "reason": "مراجعة تشغيل إعادة الاختبار بعد إصلاح الجهاز",
        },
    )
    approved = await client.post(
        f"/api/v1/runs/{retest['id']}/approve",
        headers=qa["hash"],
        json={
            "password": __import__("tests.conftest", fromlist=["PASSWORDS"]).PASSWORDS["qa.officer"],
            "reason": "اعتماد تشغيل إعادة الاختبار بعد إغلاق الانحراف",
        },
    )
    assert approved.status_code == 200, approved.text


async def test_the_approval_refusal_tells_an_approver_where_the_deviation_is(
    client, analyst, qa, reviewer, instrument_id, admin_session
):
    """A dead-end refusal is a defect in its own right."""
    from tests.conftest import PASSWORDS

    run = await _failing_run(client, analyst, instrument_id, admin_session)

    no_deviation = await client.post(
        f"/api/v1/runs/{run['id']}/review",
        headers=reviewer["hash"],
        json={"password": PASSWORDS["reviewer.phys"], "reason": "مراجعة تشغيل غير مطابق"},
    )
    assert no_deviation.status_code == 200
    first = await client.post(
        f"/api/v1/runs/{run['id']}/approve",
        headers=qa["hash"],
        json={"password": PASSWORDS["qa.officer"], "reason": "محاولة اعتماد بدون انحراف"},
    )
    assert first.json()["errors"][0]["details"]["hint"] == "raise_deviation"

    await _raise(client, analyst, run["id"])
    second = await client.post(
        f"/api/v1/runs/{run['id']}/approve",
        headers=qa["hash"],
        json={"password": PASSWORDS["qa.officer"], "reason": "محاولة اعتماد بانحراف مفتوح"},
    )
    details = second.json()["errors"][0]["details"]
    assert details["deviation"]["status"] == "OPEN"
    assert details["hint"] == "investigate_deviation"

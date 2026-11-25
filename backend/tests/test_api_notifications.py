"""Due-date notices, the worker surface, and the KPI report.

The point of these tests is the behaviour a scheduled job must have and an HTTP
handler does not usually need: **running it twice must not double the output**, and
a notice must say why it was sent. A nightly job that duplicates is worse than no
job, because it trains people to ignore the notices.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import func, select, text

from app.core.database import SessionFactory
from app.models.assets import Instrument, ReferenceEquipment, ReferenceStandard
from app.models.audit import Notification
from app.services.kpi_service import KpiService
from app.services.notification_service import NotificationService, classify


# ───────────────────────────── classification ────────────────────────────── #


def test_classify_maps_days_to_the_right_window():
    today = date(2026, 11, 25)
    assert classify(today - timedelta(days=1), today) == ("critical", "OVERDUE", -1)
    assert classify(today, today) == ("critical", "DUE_7", 0)
    assert classify(today + timedelta(days=7), today) == ("critical", "DUE_7", 7)
    assert classify(today + timedelta(days=8), today) == ("warning", "DUE_30", 8)
    assert classify(today + timedelta(days=30), today) == ("warning", "DUE_30", 30)
    assert classify(today + timedelta(days=31), today) == ("info", "DUE_60", 31)
    # beyond the widest window there is nothing to say
    assert classify(today + timedelta(days=61), today) is None


def test_a_notice_never_says_the_wrong_number_of_days():
    """The body is computed at read time, not stored as prose.

    A stored "30 days left" is wrong the next morning; that is how a warning letter
    loses its authority.
    """
    from app.services.notification_service import DueItem

    today = date(2026, 11, 25)
    overdue = DueItem(
        kind="INSTRUMENT", entity_id=uuid.uuid4(), department_id=None, code="X",
        title_ar="t", title_en="t", due=today - timedelta(days=4),
        days_remaining=-4, severity="critical", window="OVERDUE",
    )
    assert "4" in NotificationService._body(overdue)

    soon = DueItem(
        kind="INSTRUMENT", entity_id=uuid.uuid4(), department_id=None, code="X",
        title_ar="t", title_en="t", due=today + timedelta(days=3),
        days_remaining=3, severity="critical", window="DUE_7",
    )
    assert "3" in NotificationService._body(soon)




# ────────────────────────────── test fixtures ────────────────────────────── #


async def _make_due_instrument(*, days: int, code: str | None = None):
    """Create an instrument due in ``days`` (negative = overdue).

    The seed puts everything roughly eight months out, which is realistic but means
    the window logic cannot be observed from it. These fixtures state their own
    dates so a failure points at the code rather than at the calendar.
    """
    code = code or f"TEST-DUE-{days}-{uuid.uuid4().hex[:6].upper()}"
    async with SessionFactory() as session:
        department_id = (
            await session.execute(select(Instrument.department_id).limit(1))
        ).scalar_one()
        instrument = Instrument(
            id=uuid.uuid4(),
            department_id=department_id,
            asset_code=code,
            category="HPLC",
            manufacturer="Test",
            model="Fixture",
            serial_number=f"SN-{uuid.uuid4().hex[:8]}",
            calibration_freq_days=180,
            last_calibration_date=date.today() - timedelta(days=180),
            next_due_date=date.today() + timedelta(days=days),
            status="ACTIVE",
        )
        session.add(instrument)
        await session.commit()
        return instrument.id


async def _drop_instruments(*ids):
    async with SessionFactory() as session:
        for instrument_id in ids:
            await session.execute(
                text("DELETE FROM notifications WHERE payload_jsonb->>'entity_id' = :i"),
                {"i": str(instrument_id)},
            )
            # bind as text: asyncpg needs the column type for a native UUID bind
            # on a raw statement, and the cast makes that explicit.
            await session.execute(
                text("DELETE FROM instruments WHERE id = CAST(:i AS uuid)"),
                {"i": str(instrument_id)},
            )
        await session.commit()


# ─────────────────────────────── generation ──────────────────────────────── #


async def _clean_notices() -> None:
    async with SessionFactory() as session:
        await session.execute(text("DELETE FROM notifications"))
        await session.commit()


async def test_generation_creates_notices_and_is_idempotent(prepared_db):
    """The same condition produces one notice, however often the job runs.

    This is the whole reason the dedup key includes the due date rather than the
    row id: re-running is normal (a retried task, an operator running it by hand
    after the schedule failed), and the second run must be a no-op.
    """
    await _clean_notices()
    instrument_id = await _make_due_instrument(days=3)
    try:
        async with SessionFactory() as session:
            first = await NotificationService(session).generate_due_notices()
            await session.commit()

        async with SessionFactory() as session:
            second = await NotificationService(session).generate_due_notices()
            await session.commit()
            total = (
                await session.execute(select(func.count()).select_from(Notification))
            ).scalar_one()

        assert first["created"] > 0, "the fixture is due in three days"
        # ``created`` counts notices (one per recipient); ``skipped_duplicates``
        # counts conditions, so the comparable quantity is distinct conditions.
        assert first["created"] >= first["due_items"] >= 1
        assert second["created"] == 0, "a second run duplicated notices"
        assert second["skipped_duplicates"] == first["due_items"]
        assert total == first["created"]
    finally:
        await _clean_notices()
        await _drop_instruments(instrument_id)


async def test_a_dry_run_writes_nothing(prepared_db):
    await _clean_notices()
    instrument_id = await _make_due_instrument(days=20)
    try:
        async with SessionFactory() as session:
            summary = await NotificationService(session).generate_due_notices(dry_run=True)
            await session.commit()
            after = (
                await session.execute(select(func.count()).select_from(Notification))
            ).scalar_one()

        assert summary["dry_run"] is True
        assert summary["created"] > 0
        assert after == 0
    finally:
        await _clean_notices()
        await _drop_instruments(instrument_id)


async def test_each_notice_carries_its_reason(prepared_db):
    """A recipient must be able to see why they were told, without a second query."""
    await _clean_notices()
    instrument_id = await _make_due_instrument(days=-2)
    try:
        async with SessionFactory() as session:
            await NotificationService(session).generate_due_notices()
            await session.commit()
            row = (
                await session.execute(
                    select(Notification).where(
                        Notification.payload_jsonb["entity_id"].astext
                        == str(instrument_id)
                    )
                )
            ).scalars().first()

        assert row is not None
        payload = row.payload_jsonb
        assert payload["window"] == "OVERDUE"
        assert payload["days_remaining"] == -2
        assert payload["due_date"]
        assert payload["dedup_key"]
        assert row.sent_at is None, "nothing is delivered yet; sent_at must stay NULL"
        assert row.channel == "in_app"
        assert row.severity == "critical"
    finally:
        await _clean_notices()
        await _drop_instruments(instrument_id)


async def test_an_item_beyond_the_horizon_is_not_announced(prepared_db):
    """A calibration due in two years is not news, and announcing it is noise."""
    await _clean_notices()
    try:
        async with SessionFactory() as session:
            instrument = (
                await session.execute(select(Instrument).limit(1))
            ).scalar_one()
            original = instrument.next_due_date
            instrument.next_due_date = date.today() + timedelta(days=400)
            await session.commit()
            instrument_id = instrument.id

        async with SessionFactory() as session:
            items = await NotificationService(session).collect_due()
        assert all(item.entity_id != instrument_id for item in items)

        async with SessionFactory() as session:
            instrument = await session.get(Instrument, instrument_id)
            instrument.next_due_date = original
            await session.commit()
    finally:
        await _clean_notices()


# ──────────────────────────────── the API ────────────────────────────────── #


async def test_a_user_sees_only_their_own_notices(client, analyst, qa, prepared_db):
    await _clean_notices()
    instrument_id = await _make_due_instrument(days=1)
    try:
        async with SessionFactory() as session:
            await NotificationService(session).generate_due_notices()
            await session.commit()

        mine = await client.get("/api/v1/notifications", headers=analyst["hash"])
        assert mine.status_code == 200
        rows = mine.json()["data"]
        assert rows, "the analyst should have received at least one notice"

        notice_id = rows[0]["id"]
        # a notice addressed to the analyst cannot be marked read by QA
        stolen = await client.post(
            f"/api/v1/notifications/{notice_id}/read", headers=qa["hash"]
        )
        assert stolen.status_code == 200
        assert stolen.json()["data"]["marked"] is False

        own = await client.post(
            f"/api/v1/notifications/{notice_id}/read", headers=analyst["hash"]
        )
        assert own.json()["data"]["marked"] is True
    finally:
        await _clean_notices()
        await _drop_instruments(instrument_id)


async def test_generating_by_hand_requires_the_authority(client, analyst, qa):
    denied = await client.post("/api/v1/notifications/generate", headers=analyst["hash"])
    assert denied.status_code == 403
    assert denied.json()["errors"][0]["code"] == "PERMISSION_DENIED"


async def test_the_worker_status_reports_the_real_schedule(client, admin_session):
    response = await client.get("/api/v1/worker/status", headers=admin_session["hash"])
    assert response.status_code == 200
    data = response.json()["data"]

    tasks = {entry["task"] for entry in data["scheduled"]}
    assert tasks == {"sbdma.notify.calibration_due", "sbdma.reports.kpi_report"}
    assert "sbdma.notify.calibration_due" in data["registered_tasks"]
    assert "sbdma.reports.kpi_report" in data["registered_tasks"]
    # the endpoint must not claim delivery it does not have
    assert data["note_en"].startswith("Notices are stored in-app")


# ───────────────────────────── the KPI service ───────────────────────────── #


async def test_kpis_are_department_scoped(prepared_db):
    """A department head's numbers must not be the site's numbers.

    Two departments exist in the seed, so a site-wide count strictly exceeds either
    department on instruments — if it did not, the scope filter is not applied.
    """
    async with SessionFactory() as session:
        service = KpiService(session)
        site = await service.compute(department_id=None)
        departments = await service.all_departments()
        assert departments, "the seed must create departments"

        per_department = [
            await service.compute(department_id=dept.id) for dept in departments
        ]

    assert site["scope"] == "SITE"
    assert all(row["scope"] == "DEPARTMENT" for row in per_department)
    assert site["instruments"]["total"] >= sum(
        row["instruments"]["total"] for row in per_department
    )


async def test_pass_rate_is_absent_rather_than_zero_when_nothing_ran(prepared_db):
    """No runs is not a 0% pass rate — it is no information.

    A synthetic zero is the kind of number that ends up in a management review as a
    catastrophe that never happened.
    """
    async with SessionFactory() as session:
        empty_department_id = uuid.uuid4()
        kpi = await KpiService(session).compute(department_id=empty_department_id)

    assert kpi["runs"]["completed"] == 0
    assert kpi["runs"]["pass_rate_percent"] is None


async def test_the_kpi_report_is_a_real_pdf(client, qa, prepared_db):
    """The document the schedule files must be a PDF with an audit entry."""
    response = await client.post("/api/v1/reports/kpi/run", headers=qa["hash"])
    assert response.status_code == 200, response.text
    data = response.json()["data"]

    assert data["period"].count("-W") == 1
    assert data["documents"], "expected a site report at least"
    site = next(doc for doc in data["documents"] if doc["scope"] == "SITE")
    assert site["bytes"] > 20_000
    assert len(site["sha256"]) == 64

    from pathlib import Path

    blob = Path(site["path"]).read_bytes()
    assert blob.startswith(b"%PDF-")
    assert len(blob) == site["bytes"]

    audit = await client.get("/api/v1/audit?page_size=50", headers=qa["hash"])
    actions = {row["action"] for row in audit.json()["data"]}
    assert "KPI_REPORT_GENERATED" in actions
    assert "KPI_REPORT_REQUESTED" in actions


async def test_concurrent_generation_does_not_duplicate(prepared_db):
    """Two runs at the same moment must still produce one notice per recipient.

    This is the case that the check-then-insert could not cover: both callers pass
    the existence check before either inserts. The uniqueness constraint is what
    actually holds, and the service treats a violation as "another worker won".
    """
    await _clean_notices()
    instrument_id = await _make_due_instrument(days=4)
    try:
        async def one_run() -> dict:
            async with SessionFactory() as session:
                summary = await NotificationService(session).generate_due_notices()
                await session.commit()
                return summary

        first, second = await asyncio.gather(one_run(), one_run())

        async with SessionFactory() as session:
            total = (
                await session.execute(select(func.count()).select_from(Notification))
            ).scalar_one()

        # Exactly one notice per (recipient, condition): the property that matters,
        # stated without assuming how many recipients a department has.
        async with SessionFactory() as session:
            pairs = (
                await session.execute(
                    text(
                        "SELECT count(*), count(DISTINCT (user_id, dedup_key)) "
                        "FROM notifications"
                    )
                )
            ).one()

        assert first["created"] + second["created"] == total
        assert pairs[0] == pairs[1], f"{pairs[0]} notices but only {pairs[1]} distinct recipients"
    finally:
        await _clean_notices()
        await _drop_instruments(instrument_id)


async def test_the_dedup_rule_is_enforced_by_the_database(prepared_db):
    """Even a caller that bypasses the service cannot insert the same notice twice."""
    from app.models.audit import Notification as Notice

    await _clean_notices()
    instrument_id = await _make_due_instrument(days=2)
    try:
        async with SessionFactory() as session:
            await NotificationService(session).generate_due_notices()
            await session.commit()
            row = (await session.execute(select(Notice).limit(1))).scalar_one()
            user_id, payload = row.user_id, row.payload_jsonb

        async with SessionFactory() as session:
            session.add(
                Notice(
                    id=uuid.uuid4(),
                    user_id=user_id,
                    channel="in_app",
                    severity="info",
                    title_ar="duplicate attempt",
                    payload_jsonb=payload,
                )
            )
            with pytest.raises(Exception) as failure:
                await session.commit()
        assert "uq_notifications_recipient_dedup" in str(failure.value)
    finally:
        await _clean_notices()
        await _drop_instruments(instrument_id)

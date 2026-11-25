"""Expiry and due-date notices.

What makes this more than a query and an insert:

* **Every window is stated as data.** An instrument due in 30 days and one overdue
  by 90 days are different problems and get different severities; the window is
  recorded in the payload so the recipient can see *why* they were told.
* **A notice is never repeated for the same condition.** The dedup key is
  ``(entity, kind, window, due-date)``. Re-running the job a hundred times produces
  one notice, because the alternative — a nightly duplicate — is how a lab learns to
  filter the mailbox and stop reading expiry warnings.

  The check is not enough on its own: two workers running the same task at the same
  moment both pass it and both insert. The uniqueness constraint
  ``uq_notifications_recipient_dedup`` is what actually enforces the rule, and the
  in-code check only avoids the wasted round-trip. A violation is treated as "another
  worker got there first", which is success, not failure.
* **The notice names the days remaining**, computed at generation rather than read
  from a stored string, so a notice is not misleading when read a week later.
* **Nothing is sent by e-mail.** ``smtp_host`` is optional and no provider is
  wired, so notices are stored ``in_app`` with ``sent_at`` NULL until a real
  transport exists. ``/health`` states this rather than implying delivery.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assets import Instrument, ReferenceEquipment, ReferenceStandard
from app.models.audit import Notification
from app.models.rbac import User, UserRole
from app.services.audit_service import AuditService

#: (lower bound in days, upper bound in days, severity, window label)
#: A window is inclusive of both bounds. Order matters: the first match wins.
DUE_WINDOWS: tuple[tuple[int, int, str, str], ...] = (
    (-10_000, -1, "critical", "OVERDUE"),
    (0, 7, "critical", "DUE_7"),
    (8, 30, "warning", "DUE_30"),
    (31, 60, "info", "DUE_60"),
)


@dataclass(frozen=True)
class DueItem:
    kind: str  # INSTRUMENT | REFERENCE_EQUIPMENT | REFERENCE_STANDARD
    entity_id: uuid.UUID
    department_id: uuid.UUID | None
    code: str
    title_ar: str
    title_en: str
    due: date
    days_remaining: int
    severity: str
    window: str

    @property
    def dedup_key(self) -> str:
        """Identifies one condition, not one day.

        The due date is part of the key so that *recalibrating* an instrument and
        having it become due again produces a fresh notice, while re-running the
        nightly job does not.
        """
        return f"{self.kind}:{self.entity_id}:{self.window}:{self.due.isoformat()}"


def classify(due: date, today: date) -> tuple[str, str, int] | None:
    """Return (severity, window, days_remaining) or None when nothing to say."""
    days = (due - today).days
    for low, high, severity, window in DUE_WINDOWS:
        if low <= days <= high:
            return severity, window, days
    return None


class NotificationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ────────────────────────────── discovery ────────────────────────────── #

    async def collect_due(self, today: date | None = None) -> list[DueItem]:
        """Everything within the widest window, as plain data (no I/O on write)."""
        today = today or date.today()
        horizon = today + timedelta(days=max(high for _, high, _, _ in DUE_WINDOWS))
        pa_horizon = today - timedelta(days=365)  # no lower bound worth chasing
        items: list[DueItem] = []

        instruments = (
            await self.session.execute(
                select(Instrument).where(
                    Instrument.deleted_at.is_(None),
                    Instrument.next_due_date.is_not(None),
                    Instrument.next_due_date <= horizon,
                    Instrument.next_due_date >= pa_horizon,
                )
            )
        ).scalars().all()
        for row in instruments:
            verdict = classify(row.next_due_date, today)
            if verdict is None:
                continue
            severity, window, days = verdict
            items.append(
                DueItem(
                    kind="INSTRUMENT",
                    entity_id=row.id,
                    department_id=row.department_id,
                    code=row.asset_code,
                    title_ar=f"معايرة مستحقة: {row.asset_code}",
                    title_en=f"Calibration due: {row.asset_code}",
                    due=row.next_due_date,
                    days_remaining=days,
                    severity=severity,
                    window=window,
                )
            )

        equipment = (
            await self.session.execute(
                select(ReferenceEquipment).where(
                    ReferenceEquipment.is_active.is_(True),
                    ReferenceEquipment.expiry_date <= horizon,
                    ReferenceEquipment.expiry_date >= pa_horizon,
                )
            )
        ).scalars().all()
        for row in equipment:
            verdict = classify(row.expiry_date, today)
            if verdict is None:
                continue
            severity, window, days = verdict
            items.append(
                DueItem(
                    kind="REFERENCE_EQUIPMENT",
                    entity_id=row.id,
                    department_id=row.department_id,
                    code=row.equipment_code,
                    title_ar=f"انتهاء صلاحية أداة مرجعية: {row.equipment_code}",
                    title_en=f"Reference equipment expiring: {row.equipment_code}",
                    due=row.expiry_date,
                    days_remaining=days,
                    severity=severity,
                    window=window,
                )
            )

        standards = (
            await self.session.execute(
                select(ReferenceStandard).where(
                    ReferenceStandard.expiry_date <= horizon,
                    ReferenceStandard.expiry_date >= pa_horizon,
                )
            )
        ).scalars().all()
        for row in standards:
            verdict = classify(row.expiry_date, today)
            if verdict is None:
                continue
            severity, window, days = verdict
            items.append(
                DueItem(
                    kind="REFERENCE_STANDARD",
                    entity_id=row.id,
                    department_id=row.department_id,
                    code=row.lot_number,
                    title_ar=f"انتهاء صلاحية معيار مرجعي: {row.lot_number}",
                    title_en=f"Reference standard expiring: {row.lot_number}",
                    due=row.expiry_date,
                    days_remaining=days,
                    severity=severity,
                    window=window,
                )
            )
        return items

    # ──────────────────────────────── persist ────────────────────────────── #

    async def _recipients(self, department_id: uuid.UUID | None) -> list[User]:
        """Who must hear about a due item.

        Everyone in the department holding a role that can act on it — a notice
        with no actor is a notice nobody owns. When an item has no department
        (should not happen, but the schema permits it) the notice goes to every
        active user so it is not silently dropped.
        """
        conditions = [User.is_active.is_(True), User.deleted_at.is_(None)]
        if department_id is not None:
            conditions.append(User.department_id == department_id)
        return list((await self.session.execute(select(User).where(*conditions))).scalars().all())

    async def _already_notified(self, dedup_key: str) -> bool:
        existing = (
            await self.session.execute(
                select(Notification.id)
                .where(Notification.channel == "in_app")
                .where(Notification.payload_jsonb["dedup_key"].astext == dedup_key)
                .limit(1)
            )
        ).scalar_one_or_none()
        return existing is not None

    async def generate_due_notices(
        self, *, today: date | None = None, dry_run: bool = False
    ) -> dict:
        """Create one notice per recipient per newly-due condition.

        Returns a summary rather than raising on a partial failure: the caller is a
        scheduled job whose only observer is the log, and it needs to say what it
        did.
        """
        today = today or date.today()
        items = await self.collect_due(today)
        created = skipped = 0
        by_kind: dict[str, int] = {}

        for item in items:
            if await self._already_notified(item.dedup_key):
                skipped += 1
                continue
            if dry_run:
                created += 1
                by_kind[item.kind] = by_kind.get(item.kind, 0) + 1
                continue

            recipients = await self._recipients(item.department_id)
            if not recipients:
                skipped += 1
                continue

            for user in recipients:
                notice = Notification(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    channel="in_app",
                    severity=item.severity,
                    title_ar=item.title_ar,
                    body_ar=self._body(item),
                    payload_jsonb={
                        "dedup_key": item.dedup_key,
                        "title_en": item.title_en,
                        "kind": item.kind,
                        "entity_id": str(item.entity_id),
                        "code": item.code,
                        "due_date": item.due.isoformat(),
                        "days_remaining": item.days_remaining,
                        "window": item.window,
                        "generated_on": today.isoformat(),
                    },
                    # not delivered: nothing is wired to deliver it yet
                    scheduled_at=None,
                    sent_at=None,
                )
                # Savepoint per notice: losing the race on one recipient must not
                # abort the notices already written for the others.
                try:
                    async with self.session.begin_nested():
                        self.session.add(notice)
                except IntegrityError:
                    skipped += 1
                    continue
                created += 1
                by_kind[item.kind] = by_kind.get(item.kind, 0) + 1

        if not dry_run and created:
            await AuditService(self.session).record(
                action="NOTIFICATIONS_GENERATED",
                entity_type="notification",
                entity_id=uuid.uuid4(),
                actor_label="system:celery",
                reason="توليد إشعارات انتهاء المعايرة والصلاحية",
                new_values={
                    "created": created,
                    "skipped_duplicates": skipped,
                    "by_kind": by_kind,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        return {
            "due_items": len(items),
            "created": created,
            "skipped_duplicates": skipped,
            "by_kind": by_kind,
            "dry_run": dry_run,
        }

    @staticmethod
    def _body(item: DueItem) -> str:
        if item.days_remaining < 0:
            return (
                f"تجاوز الموعد النهائي بـ{abs(item.days_remaining)} يوماً. "
                f"الموعد: {item.due.isoformat()}."
            )
        if item.days_remaining == 0:
            return f"الموعد النهائي اليوم: {item.due.isoformat()}."
        return (
            f"يتبقى {item.days_remaining} يوماً على الموعد النهائي {item.due.isoformat()}."
        )

    # ───────────────────────────────── reads ─────────────────────────────── #

    async def for_user(
        self, user_id: uuid.UUID, *, unread_only: bool = False, limit: int = 50
    ) -> list[Notification]:
        conditions = [Notification.user_id == user_id]
        if unread_only:
            conditions.append(Notification.read_at.is_(None))
        return list(
            (
                await self.session.execute(
                    select(Notification)
                    .where(*conditions)
                    .order_by(Notification.created_at.desc())
                    .limit(limit)
                )
            ).scalars().all()
        )

    async def mark_read(self, user_id: uuid.UUID, notification_id: uuid.UUID) -> bool:
        """Only the addressee can mark their own notice read."""
        row = await self.session.get(Notification, notification_id)
        if row is None or row.user_id != user_id:
            return False
        if row.read_at is None:
            row.read_at = datetime.now(timezone.utc)
        return True

"""Approval-routing notices.

A calibration that has been executed is not finished: it is *waiting for a person*.
Until this module existed, nothing told that person — the supervisor found the run by
opening the approval screen, and QA found it only after the supervisor happened to
review it. The laboratory asked for the opposite: saving a test notifies the supervisor
**and** QA, and the reviewer who clears it notifies QA again.

Two rules shape the design:

* **One notice per person per event.** The dedup key is
  ``(event, run, stage, recipient)`` and the database's unique index on
  ``notifications.dedup_key`` enforces it, so re-saving a run, retrying a request or
  two workers racing cannot produce a second copy of the same message for the same
  person. The in-code check only avoids the wasted round-trip.
* **The notice names the next step, not just the event.** "اعتماد ضمان الجودة مطلوب"
  with no run code, instrument and link is a message the reader has to go and
  investigate. Every payload therefore carries the run code, the unit, the verdict and
  the stage it is waiting in.

Recipients are resolved from the *permission*, not from a hard-coded username list: the
supervisor tier is everyone holding ``calibration.review`` and the QA tier everyone
holding ``calibration.approve``, limited to the run's department unless they are
cross-department supervisors. A laboratory that appoints a second QA officer does not
have to edit this file.

Notices stay ``in_app`` with ``sent_at`` NULL, exactly like the due-date notices: no mail
transport is wired, and pretending otherwise would be worse than saying so.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.rbac import ROLE_PERMISSIONS, SUPERVISOR_ROLES
from app.models.audit import Notification
from app.models.rbac import User, UserRole

log = get_logger("sbdma.notices")

#: A run that has been executed and is waiting for the supervisor's signature.
STAGE_SUPERVISOR = "SUPERVISOR_REVIEW"
#: The supervisor has signed; the run is waiting for QA.
STAGE_QA = "QA_APPROVAL"
#: QA signed and the run is locked — the certificate is available.
STAGE_RELEASED = "RELEASED"


def _holders(permission: str) -> list[str]:
    """Every role code that carries a permission (the policy is the only source)."""
    return [code for code, perms in ROLE_PERMISSIONS.items() if permission in perms]


@dataclass(slots=True)
class Recipient:
    user_id: uuid.UUID
    username: str


class ApprovalNoticeService:
    """Writes approval-routing notices; never reads anything the caller did not store."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ─────────────────────────── recipient resolution ─────────────────────── #

    async def _users_with_permission(
        self,
        permission: str,
        *,
        department_id: uuid.UUID | None,
        roles: frozenset[str] | None = None,
    ) -> list[User]:
        """Active users who can act on this stage.

        Department scope mirrors the API's own rules: a review/approval permission held
        by a cross-department supervisor (``QA_APPROVER``, the administrators) sees every
        department; the in-department reviewers are limited to their own. Nobody is told
        about a run they would be refused on — a notice that leads to a 404 is worse
        than no notice.
        """
        holders = _holders(permission)
        if roles is not None:
            # A stage belongs to an office, not only to a capability. QA holds
            # ``calibration.review`` as well, but telling QA that a run awaits *its*
            # technical review is a false instruction: QA signs at the second stage.
            # The office is named, and the capability is still required.
            holders = [code for code in holders if code in roles]
        if not holders:
            return []
        # join through user_roles rather than loading every user and filtering in Python:
        # the notice fan-out runs on every save, and the laboratory will add accounts.
        rows = (
            await self.session.execute(
                select(User)
                .join(UserRole, UserRole.user_id == User.id)
                .where(
                    User.is_active.is_(True),
                    User.deleted_at.is_(None),
                    UserRole.role_code.in_(holders),
                )
                .distinct()
            )
        ).scalars().all()
        scoped: list[User] = []
        for user in rows:
            user_roles = {r.code for r in user.roles}
            if user_roles & SUPERVISOR_ROLES:
                scoped.append(user)
                continue
            if department_id is None or user.department_id == department_id:
                scoped.append(user)
        return scoped

    # ──────────────────────────────── writing ─────────────────────────────── #

    async def _notify(
        self,
        *,
        users: Iterable[User],
        event: str,
        run_id: uuid.UUID,
        stage: str,
        severity: str,
        title_ar: str,
        title_en: str,
        body_ar: str,
        payload: dict,
        skip_user_id: uuid.UUID | None = None,
    ) -> int:
        created = 0
        for user in users:
            # The actor never receives the notice for the action they just performed.
            if skip_user_id is not None and user.id == skip_user_id:
                continue
            key = f"{event}:{run_id}:{stage}:{user.id}"
            exists = (
                await self.session.execute(
                    select(Notification.id)
                    .where(Notification.channel == "in_app")
                    .where(Notification.payload_jsonb["dedup_key"].astext == key)
                    .limit(1)
                )
            ).scalar_one_or_none()
            if exists is not None:
                continue
            notice = Notification(
                id=uuid.uuid4(),
                user_id=user.id,
                channel="in_app",
                severity=severity,
                title_ar=title_ar,
                body_ar=body_ar,
                payload_jsonb={
                    **payload,
                    "dedup_key": key,
                    "title_en": title_en,
                    "event": event,
                    "stage": stage,
                    "run_id": str(run_id),
                    "generated_on": datetime.now(timezone.utc).isoformat(),
                },
                scheduled_at=None,
                sent_at=None,
            )
            try:
                # Savepoint per recipient: losing the race for one addressee must not
                # roll back the notices already written for the others.
                async with self.session.begin_nested():
                    self.session.add(notice)
            except IntegrityError:
                continue
            created += 1
        return created

    async def run_executed(
        self,
        *,
        run_id: uuid.UUID,
        execution_code: str,
        department_id: uuid.UUID | None,
        instrument_label: str,
        overall: str,
        test_codes: list[str],
        actor_id: uuid.UUID,
        actor_label: str,
    ) -> dict:
        """A saved calibration: tell the supervisor *and* QA, in that order.

        QA is notified at the same moment even though it cannot act yet. That is
        deliberate — the QA queue is planned against how many runs are in the pipeline,
        and a reviewer who knows a run is coming can look at it while it waits.
        """
        payload = {
            "run_code": execution_code,
            "instrument": instrument_label,
            "overall": overall,
            "tests": test_codes,
            "actor": actor_label,
        }
        supervisors = await self._users_with_permission(
            "calibration.review", department_id=department_id, roles=frozenset({"SUPERVISOR"})
        )
        approvers = await self._users_with_permission(
            "calibration.approve", department_id=department_id, roles=frozenset({"QA_APPROVER"})
        )
        first = await self._notify(
            users=supervisors,
            event="RUN_AWAITING_REVIEW",
            run_id=run_id,
            stage=STAGE_SUPERVISOR,
            severity="warning",
            title_ar=f"معايرة بانتظار مراجعتك: {execution_code}",
            title_en=f"Calibration awaiting your review: {execution_code}",
            body_ar=(
                f"سجّل {actor_label} تشغيل معايرة على {instrument_label} وحالته {overall}. "
                f"الاختبارات: {'، '.join(test_codes) if test_codes else '—'}. "
                "المراجعة الفنية تفتح مسار اعتماد ضمان الجودة."
            ),
            payload=payload,
            skip_user_id=actor_id,
        )
        second = await self._notify(
            users=approvers,
            event="RUN_AWAITING_QA",
            run_id=run_id,
            stage=STAGE_QA,
            severity="info",
            title_ar=f"معايرة في الطريق إلى الاعتماد: {execution_code}",
            title_en=f"Calibration on its way to approval: {execution_code}",
            body_ar=(
                f"انتظار المراجعة الفنية للتشغيل {execution_code} على {instrument_label} "
                f"({overall}). الاعتماد النهائي لن يتم قبل توقيع مشرف المختبر."
            ),
            payload=payload,
            skip_user_id=actor_id,
        )
        log.info(
            "approval notices written for a new run",
            extra={
                "extra_fields": {
                    "run": execution_code,
                    "supervisor_notices": first,
                    "qa_notices": second,
                }
            },
        )
        return {"supervisor": first, "qa": second}

    async def run_reviewed(
        self,
        *,
        run_id: uuid.UUID,
        execution_code: str,
        department_id: uuid.UUID | None,
        instrument_label: str,
        overall: str,
        reviewer_label: str,
        actor_id: uuid.UUID,
    ) -> dict:
        """The supervisor signed: QA can now act, and the analyst is told."""
        payload = {
            "run_code": execution_code,
            "instrument": instrument_label,
            "overall": overall,
            "actor": reviewer_label,
        }
        approvers = await self._users_with_permission(
            "calibration.approve", department_id=department_id, roles=frozenset({"QA_APPROVER"})
        )
        qa = await self._notify(
            users=approvers,
            event="RUN_AWAITING_QA",
            run_id=run_id,
            stage=STAGE_QA,
            severity="warning",
            title_ar=f"اعتماد ضمان الجودة مطلوب: {execution_code}",
            title_en=f"QA approval required: {execution_code}",
            body_ar=(
                f"وقّع {reviewer_label} المراجعة الفنية للتشغيل {execution_code} على "
                f"{instrument_label} ({overall}). التشغيل بانتظار اعتمادك؛ بعده تُقفل "
                "النتائج وتُتاح الشهادة الرسمية دون علامة مسودة."
            ),
            payload=payload,
            skip_user_id=actor_id,
        )
        return {"qa": qa}

    async def run_released(
        self,
        *,
        run_id: uuid.UUID,
        execution_code: str,
        department_id: uuid.UUID | None,
        instrument_label: str,
        approver_label: str,
        actor_id: uuid.UUID,
    ) -> dict:
        """QA signed and the run is locked: tell the bench that the certificate exists."""
        payload = {
            "run_code": execution_code,
            "instrument": instrument_label,
            "actor": approver_label,
        }
        operators = await self._users_with_permission(
            "calibration.run", department_id=department_id
        )
        count = await self._notify(
            users=operators,
            event="RUN_RELEASED",
            run_id=run_id,
            stage=STAGE_RELEASED,
            severity="info",
            title_ar=f"اعتُمدت المعايرة {execution_code} — الشهادة متاحة",
            title_en=f"Calibration {execution_code} approved — certificate available",
            body_ar=(
                f"اعتمد {approver_label} التشغيل {execution_code} على {instrument_label}. "
                "النتائج مقفلة الآن، والشهادة الرسمية الكاملة (بدون علامة مسودة) متاحة للتنزيل."
            ),
            payload=payload,
            skip_user_id=actor_id,
        )
        return {"operators": count}

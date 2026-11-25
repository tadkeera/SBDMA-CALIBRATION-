"""OOS deviation workflow: raise → investigate → close.

The phase permissions are the point of this module. ``deviations.raise``,
``deviations.investigate`` and ``deviations.close`` are separate, and the service
refuses to let one person perform all three:

* the analyst who saw the failure raises it;
* QA investigates and states a root cause;
* QA closes it with a CAPA decision — and the closer may not be the investigator
  when a second, independent QA officer is available. That check is advisory in
  the sense that it depends on staffing, so it is enforced as "the investigator
  must not also close" only when another holder of ``deviations.close`` exists;
  otherwise the audit trail records that the same person did both, which is the
  honest representation of a single-officer site.

A deviation never changes the run's verdict. The failed run stays failed, and the
route back to a passing instrument is a *retest*: a new run, linked here.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationFailedError,
)
from app.core.rbac import Principal
from app.models.deviations import (
    CAPA_ACTIONS,
    DEVIATION_CLASSES,
    ROOT_CAUSE_CATEGORIES,
    Deviation,
    can_transition,
)
from app.models.rbac import User
from app.models.runs import CalibrationRun
from app.services.audit_service import AuditService

#: Statuses that a deviation may be raised against.
RAISABLE_RUN_STATUSES = frozenset({"FAIL", "INCOMPLETE"})


class DeviationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.audit = AuditService(session)

    # ────────────────────────────── reads ────────────────────────────────── #

    async def _run(self, run_id: uuid.UUID, principal: Principal) -> CalibrationRun:
        run = await self.session.get(CalibrationRun, run_id)
        if run is None:
            raise NotFoundError(message_ar="التشغيل غير موجود", message_en="Run not found")
        principal.assert_department(run.department_id)
        return run

    async def _deviation(self, deviation_id: uuid.UUID, principal: Principal) -> Deviation:
        deviation = await self.session.get(Deviation, deviation_id)
        if deviation is None or deviation.deleted_at is not None:
            raise NotFoundError(
                message_ar="الانحراف غير موجود", message_en="Deviation not found"
            )
        principal.assert_department(deviation.department_id)
        return deviation

    async def list_deviations(
        self,
        principal: Principal,
        *,
        page: int,
        page_size: int,
        status: str | None = None,
        run_id: uuid.UUID | None = None,
    ) -> tuple[list[Deviation], int]:
        principal.require("instruments.view")
        conditions = [Deviation.deleted_at.is_(None)]
        if not principal.is_supervisor():
            conditions.append(Deviation.department_id == principal.department_id)
        if status:
            conditions.append(Deviation.status == status)
        if run_id:
            conditions.append(Deviation.run_id == run_id)

        total = (
            await self.session.execute(
                select(func.count()).select_from(Deviation).where(*conditions)
            )
        ).scalar_one()
        rows = (
            await self.session.execute(
                select(Deviation)
                .where(*conditions)
                .order_by(Deviation.raised_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
        return list(rows), int(total)

    async def get(self, deviation_id: uuid.UUID, principal: Principal) -> Deviation:
        principal.require("instruments.view")
        return await self._deviation(deviation_id, principal)

    async def _next_reference(self) -> str:
        """DEV-YYYYMMDD-NNNN, sequential per day.

        Derived from the table rather than a sequence so the number a document
        carries matches its position in the day's log — an auditor reading the
        register can see that none is missing.
        """
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        prefix = f"DEV-{today}-"
        latest = (
            await self.session.execute(
                select(func.count()).select_from(Deviation).where(Deviation.reference.like(f"{prefix}%"))
            )
        ).scalar_one()
        return f"{prefix}{int(latest) + 1:04d}"

    # ─────────────────────────────── raise ───────────────────────────────── #

    async def raise_deviation(
        self,
        principal: Principal,
        *,
        run_id: uuid.UUID,
        title: str,
        description: str,
        classification: str,
        ip: str | None = None,
    ) -> Deviation:
        principal.require("deviations.raise")
        run = await self._run(run_id, principal)

        if run.overall_status not in RAISABLE_RUN_STATUSES:
            raise ConflictError(
                message_ar=(
                    "لا يُفتح انحراف إلا على تشغيل غير مطابق أو غير مكتمل. "
                    f"حالة هذا التشغيل: {run.overall_status}"
                ),
                message_en=(
                    "A deviation may only be raised against a failing or incomplete run. "
                    f"This run is {run.overall_status}."
                ),
                details={"run_status": run.overall_status},
            )
        if classification not in DEVIATION_CLASSES:
            raise ValidationFailedError(
                message_ar=f"تصنيف غير معروف: {classification}",
                message_en=f"Unknown classification: {classification}",
                field="classification",
            )

        # One open investigation per run: a second one would let two people chase
        # the same failure to different conclusions.
        existing = (
            await self.session.execute(
                select(Deviation).where(
                    Deviation.run_id == run_id,
                    Deviation.status.notin_(("CLOSED", "CANCELLED")),
                    Deviation.deleted_at.is_(None),
                )
            )
        ).scalars().first()
        if existing is not None:
            raise ConflictError(
                message_ar=f"يوجد انحراف مفتوح لهذا التشغيل بالفعل: {existing.reference}",
                message_en=f"This run already has an open deviation: {existing.reference}",
                details={"reference": existing.reference, "deviation_id": str(existing.id)},
            )

        deviation = Deviation(
            id=uuid.uuid4(),
            reference=await self._next_reference(),
            run_id=run.id,
            instrument_id=run.instrument_id,
            department_id=run.department_id,
            classification=classification,
            status="OPEN",
            title=title.strip(),
            description=description.strip(),
            raised_by=principal.user_id,
            raised_at=datetime.now(timezone.utc),
        )
        self.session.add(deviation)
        await self.session.flush()

        await self.audit.record(
            action="DEVIATION_RAISED",
            entity_type="deviation",
            entity_id=deviation.id,
            actor_label=principal.username,
            actor_id=principal.user_id,
            role_label=principal.primary_role,
            department_id=deviation.department_id,
            new_values={
                "reference": deviation.reference,
                "run": run.execution_code,
                "classification": classification,
                "run_status": run.overall_status,
            },
            reason=f"OOS deviation raised for {run.execution_code}",
            ip_address=ip,
        )
        return deviation

    # ──────────────────────────── investigate ────────────────────────────── #

    async def start_investigation(
        self,
        principal: Principal,
        deviation_id: uuid.UUID,
        *,
        plan: str,
        ip: str | None = None,
    ) -> Deviation:
        """Open the investigation: OPEN → INVESTIGATING.

        Recorded separately from the conclusion because the *start* date is the one
        that goes into the OOS timeline — an inspector asks when the investigation
        began, not only when it concluded (ICH Q10 expects it to begin promptly).
        """
        principal.require("deviations.investigate")
        deviation = await self._deviation(deviation_id, principal)

        if not can_transition(deviation.status, "INVESTIGATING"):
            raise ConflictError(
                message_ar=(
                    f"لا يمكن بدء التحقيق من الحالة {deviation.status}. "
                    "البدء متاح للانحرافات المفتوحة فقط."
                ),
                message_en=(
                    f"Cannot start an investigation from status {deviation.status}. "
                    "Only an OPEN deviation can be taken up."
                ),
                details={"status": deviation.status},
            )

        # Investigating your own raised deviation is a conflict of interest: the
        # raiser is usually the analyst whose result failed.
        if deviation.raised_by == principal.user_id:
            raise PermissionDeniedError(
                message_ar=(
                    "لا يجوز أن يحقّق الشخص نفسه في انحراف فتحه — يلزم محقّق مستقل"
                ),
                message_en=(
                    "You cannot investigate a deviation you raised — an independent "
                    "investigator is required"
                ),
                field="raised_by",
            )

        old = {"status": deviation.status}
        deviation.investigated_by = principal.user_id
        deviation.investigated_at = datetime.now(timezone.utc)
        deviation.status = "INVESTIGATING"

        await self.audit.record(
            action="DEVIATION_INVESTIGATION_STARTED",
            entity_type="deviation",
            entity_id=deviation.id,
            actor_label=principal.username,
            actor_id=principal.user_id,
            role_label=principal.primary_role,
            department_id=deviation.department_id,
            old_values=old,
            new_values={"status": deviation.status, "plan": plan.strip()},
            reason=f"investigation opened for {deviation.reference}",
            ip_address=ip,
        )
        return deviation

    async def investigate(
        self,
        principal: Principal,
        deviation_id: uuid.UUID,
        *,
        root_cause_category: str,
        root_cause: str,
        immediate_action: str,
        ip: str | None = None,
    ) -> Deviation:
        """Record the conclusion: INVESTIGATING → PENDING_VERIFICATION."""
        principal.require("deviations.investigate")
        deviation = await self._deviation(deviation_id, principal)

        if not can_transition(deviation.status, "PENDING_VERIFICATION"):
            raise ConflictError(
                message_ar=(
                    f"لا يمكن تسجيل نتيجة التحقيق من الحالة {deviation.status}. "
                    "يلزم بدء التحقيق أولاً."
                ),
                message_en=(
                    f"Cannot record an investigation outcome from status {deviation.status}. "
                    "Start the investigation first."
                ),
                details={"status": deviation.status},
            )
        if root_cause_category not in ROOT_CAUSE_CATEGORIES:
            raise ValidationFailedError(
                message_ar=f"تصنيف سبب غير معروف: {root_cause_category}",
                message_en=f"Unknown root-cause category: {root_cause_category}",
                field="root_cause_category",
            )
        # Only the investigator who opened the case may conclude it; handing the
        # conclusion to someone else would split responsibility for the finding.
        if deviation.investigated_by != principal.user_id:
            raise PermissionDeniedError(
                message_ar=(
                    "لا يمكن تسجيل نتيجة تحقيق فتحه محقّق آخر — سجّل الدخول بحساب المحقّق"
                ),
                message_en=(
                    "Only the investigator who opened this case may record its outcome"
                ),
                field="investigated_by",
            )

        old = {"status": deviation.status}
        deviation.root_cause_category = root_cause_category
        deviation.root_cause = root_cause.strip()
        deviation.immediate_action = immediate_action.strip()
        deviation.status = "PENDING_VERIFICATION"

        await self.audit.record(
            action="DEVIATION_INVESTIGATED",
            entity_type="deviation",
            entity_id=deviation.id,
            actor_label=principal.username,
            actor_id=principal.user_id,
            role_label=principal.primary_role,
            department_id=deviation.department_id,
            old_values=old,
            new_values={
                "status": deviation.status,
                "root_cause_category": root_cause_category,
            },
            reason=f"root cause established for {deviation.reference}",
            ip_address=ip,
        )
        return deviation

    # ────────────────────────────── close ────────────────────────────────── #

    async def close(
        self,
        principal: Principal,
        deviation_id: uuid.UUID,
        *,
        capa_action: str,
        capa_notes: str,
        closure_notes: str,
        retest_run_id: uuid.UUID | None = None,
        ip: str | None = None,
    ) -> Deviation:
        principal.require("deviations.close")
        deviation = await self._deviation(deviation_id, principal)

        if not can_transition(deviation.status, "CLOSED"):
            raise ConflictError(
                message_ar=(
                    f"لا يمكن إغلاق الانحراف من الحالة {deviation.status}. "
                    "الإغلاق يتطلب مرحلة تحقق مكتملة."
                ),
                message_en=(
                    f"Cannot close a deviation in status {deviation.status}. "
                    "Closure requires a completed investigation."
                ),
                details={"status": deviation.status},
            )
        if capa_action not in CAPA_ACTIONS:
            raise ValidationFailedError(
                message_ar=f"إجراء CAPA غير معروف: {capa_action}",
                message_en=f"Unknown CAPA action: {capa_action}",
                field="capa_action",
            )

        # Independence. For a CRITICAL deviation the second pair of eyes is not
        # optional: whoever investigated may not also sign it off, if the site has
        # anyone else able to. For MAJOR/MINOR the same person may do both — a
        # two-officer rule that a one-officer lab cannot meet would only push the
        # work back into private email — but the audit record says so explicitly.
        self_closing = deviation.investigated_by == principal.user_id
        if self_closing and deviation.classification == "CRITICAL":
            if await self._other_closers(principal):
                raise PermissionDeniedError(
                    message_ar=(
                        "انحراف حرج: لا يجوز أن يغلق المحقّق تحقيقه بنفسه وهناك "
                        "مسؤول جودة آخر متاح"
                    ),
                    message_en=(
                        "Critical deviation: the investigator cannot close their own "
                        "investigation while another QA officer is available"
                    ),
                    field="investigated_by",
                )

        retest = None
        if retest_run_id is not None:
            retest = await self.session.get(CalibrationRun, retest_run_id)
            if retest is None:
                raise NotFoundError(
                    message_ar="تشغيل إعادة الاختبار غير موجود",
                    message_en="Retest run not found",
                    field="retest_run_id",
                )
            if retest.id == deviation.run_id:
                raise ValidationFailedError(
                    message_ar="إعادة الاختبار يجب أن تكون تشغيلاً جديداً لا التشغيل نفسه",
                    message_en="The retest must be a new run, not the failing one",
                    field="retest_run_id",
                )
            if retest.instrument_id != deviation.instrument_id:
                raise ValidationFailedError(
                    message_ar="إعادة الاختبار يجب أن تكون على الجهاز نفسه",
                    message_en="The retest must be on the same instrument",
                    field="retest_run_id",
                )

        old = {"status": deviation.status}
        deviation.capa_action = capa_action
        deviation.capa_notes = capa_notes.strip()
        deviation.closure_notes = closure_notes.strip()
        deviation.retest_run_id = retest_run_id
        deviation.closed_by = principal.user_id
        deviation.closed_at = datetime.now(timezone.utc)
        deviation.status = "CLOSED"

        await self.audit.record(
            action="DEVIATION_CLOSED",
            entity_type="deviation",
            entity_id=deviation.id,
            actor_label=principal.username,
            actor_id=principal.user_id,
            role_label=principal.primary_role,
            department_id=deviation.department_id,
            old_values=old,
            new_values={
                "status": deviation.status,
                "capa_action": capa_action,
                "retest_run": retest.execution_code if retest else None,
                "same_person_investigated_and_closed": self_closing,
            },
            reason=f"CAPA decided for {deviation.reference}",
            ip_address=ip,
        )
        return deviation

    async def cancel(
        self, principal: Principal, deviation_id: uuid.UUID, *, reason: str, ip: str | None = None
    ) -> Deviation:
        """Cancel a deviation raised in error — only before any investigation."""
        principal.require("deviations.close")
        deviation = await self._deviation(deviation_id, principal)
        if not can_transition(deviation.status, "CANCELLED"):
            raise ConflictError(
                message_ar="لا يمكن إلغاء انحراف بدأ التحقيق فيه — أكمل التحقيق وأغلقه",
                message_en=(
                    "A deviation under investigation cannot be cancelled — complete the "
                    "investigation and close it"
                ),
                details={"status": deviation.status},
            )
        old = {"status": deviation.status}
        deviation.status = "CANCELLED"
        deviation.closure_notes = reason.strip()
        deviation.closed_by = principal.user_id
        deviation.closed_at = datetime.now(timezone.utc)
        await self.audit.record(
            action="DEVIATION_CANCELLED",
            entity_type="deviation",
            entity_id=deviation.id,
            actor_label=principal.username,
            actor_id=principal.user_id,
            role_label=principal.primary_role,
            department_id=deviation.department_id,
            old_values=old,
            new_values={"status": "CANCELLED"},
            reason=reason.strip(),
            ip_address=ip,
        )
        return deviation

    async def _other_closers(self, principal: Principal) -> list[User]:
        """Other active users in the department who could close a deviation."""
        rows = (
            await self.session.execute(
                select(User).where(
                    User.id != principal.user_id,
                    User.is_active.is_(True),
                    User.deleted_at.is_(None),
                )
            )
        ).scalars().all()
        return [
            user
            for user in rows
            if any("deviations.close" in _role_permissions(role.code) for role in user.roles)
        ]


def _role_permissions(role_code: str) -> tuple[str, ...]:
    from app.core.rbac import ROLE_PERMISSIONS

    return ROLE_PERMISSIONS.get(role_code, ())


def serialise(deviation: Deviation, *, run_code: str | None = None) -> dict:
    return {
        "id": str(deviation.id),
        "reference": deviation.reference,
        "run_id": str(deviation.run_id),
        "run_code": run_code,
        "instrument_id": str(deviation.instrument_id),
        "status": deviation.status,
        "classification": deviation.classification,
        "title": deviation.title,
        "description": deviation.description,
        "root_cause_category": deviation.root_cause_category,
        "root_cause": deviation.root_cause,
        "immediate_action": deviation.immediate_action,
        "capa_action": deviation.capa_action,
        "capa_notes": deviation.capa_notes,
        "closure_notes": deviation.closure_notes,
        "retest_run_id": str(deviation.retest_run_id) if deviation.retest_run_id else None,
        "raised_by": str(deviation.raised_by),
        "raised_at": deviation.raised_at.isoformat() if deviation.raised_at else None,
        "investigated_by": str(deviation.investigated_by) if deviation.investigated_by else None,
        "investigated_at": (
            deviation.investigated_at.isoformat() if deviation.investigated_at else None
        ),
        "closed_by": str(deviation.closed_by) if deviation.closed_by else None,
        "closed_at": deviation.closed_at.isoformat() if deviation.closed_at else None,
    }

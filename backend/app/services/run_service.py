"""Calibration run lifecycle: create, execute, review, approve, lock.

Ordering of guards (all server-side, deny-by-default):
  1. capability          — calibration.run / .review / .approve
  2. department scope    — IDOR protection, 404 semantics
  3. expiry guard        — reference equipment must be in date
  4. protocol completeness — every in-scope mandatory test must be present
  5. engine governance   — conflicted limits escalate to UNDER_REVIEW
  6. segregation of duty — analyst / reviewer / QA must be distinct
  7. lock immutability   — approved results can never change again
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ConflictError,
    ExpiryGuardError,
    LimitGovernanceError,
    LockedResultError,
    NotFoundError,
    PermissionDeniedError,
    SegregationOfDutiesError,
    ValidationFailedError,
)
from app.core.logging import get_logger
from app.core.rbac import Principal, assert_segregation_of_duties
from app.core.security import certificate_fingerprint, verify_password
from app.domain.protocol.blueprint import tests_for_component
from app.domain.scoring.engine import (
    FAIL,
    INCOMPLETE,
    PASS,
    UNDER_REVIEW,
    RunOutcome,
    execute_run,
    serialise_outputs,
)
from app.models.assets import Instrument, ReferenceEquipment
from app.models.protocol import AcceptanceLimit, CalibrationProtocol, FormulaDefinition, TestDefinition
from app.models.rbac import User
from app.models.runs import CalibrationRun, CalibrationTestResult
from app.services.audit_service import AuditService

log = get_logger("sbdma.runs")


class RunService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.audit = AuditService(session)

    # ────────────────────────────── helpers ──────────────────────────────── #

    async def _instrument(self, instrument_id: uuid.UUID, principal: Principal) -> Instrument:
        instrument = await self.session.get(Instrument, instrument_id)
        if instrument is None or instrument.deleted_at is not None:
            raise NotFoundError(
                message_ar="الجهاز غير موجود", message_en="Instrument not found"
            )
        principal.assert_department(instrument.department_id)
        return instrument

    async def _active_protocol(self, category: str) -> CalibrationProtocol:
        stmt = (
            select(CalibrationProtocol)
            .where(
                CalibrationProtocol.instrument_category == category,
                CalibrationProtocol.status == "APPROVED",
            )
            .order_by(CalibrationProtocol.version.desc())
            .limit(1)
        )
        protocol = (await self.session.execute(stmt)).scalar_one_or_none()
        if protocol is None:
            raise ConflictError(
                message_ar="لا يوجد بروتوكول معتمد لهذه الفئة من الأجهزة",
                message_en="No approved protocol exists for this instrument category",
            )
        return protocol

    async def _get_run(self, run_id: uuid.UUID, principal: Principal) -> CalibrationRun:
        run = await self.session.get(CalibrationRun, run_id)
        if run is None:
            raise NotFoundError(message_ar="التشغيل غير موجود", message_en="Run not found")
        principal.assert_department(run.department_id)
        return run

    @staticmethod
    def _execution_code(sequence: int) -> str:
        today = date.today().strftime("%Y%m%d")
        return f"RUN-{today}-{sequence:04d}"

    async def _next_sequence(self) -> int:
        today = date.today()
        count = (
            await self.session.execute(
                select(func.count()).select_from(CalibrationRun).where(
                    func.date(CalibrationRun.started_at) == today
                )
            )
        ).scalar_one()
        return int(count) + 1

    # ─────────────────────────────── create ──────────────────────────────── #

    async def create_run(
        self,
        *,
        principal: Principal,
        instrument_id: uuid.UUID,
        reference_equipment_id: uuid.UUID | None,
        run_type: str,
        ambient_temp_c: float | None,
        ambient_humidity: float | None,
        limit_source_policy: str,
        breakdown_component: str | None,
        ip: str | None = None,
    ) -> CalibrationRun:
        principal.require("calibration.run")
        instrument = await self._instrument(instrument_id, principal)

        if instrument.status == "OUT_OF_SERVICE":
            raise ConflictError(
                message_ar="الجهاز خارج الخدمة ولا يمكن تشغيل معايرة عليه",
                message_en="Instrument is out of service and cannot be calibrated",
            )

        if run_type == "POST_BREAKDOWN":
            if not breakdown_component:
                raise ValidationFailedError(
                    message_ar="المكوّن المتعطل مطلوب لتشغيل ما بعد الأعطال",
                    message_en="The failed component is required for a post-breakdown run",
                    field="breakdown_component",
                )
            if not tests_for_component(breakdown_component):
                raise ValidationFailedError(
                    message_ar="المكوّن المتعطل غير معروف",
                    message_en="Unknown failed component",
                    field="breakdown_component",
                )

        # Expiry guard — server-side, plus a database trigger as defence in depth.
        if reference_equipment_id is not None:
            ref = await self.session.get(ReferenceEquipment, reference_equipment_id)
            if ref is None:
                raise NotFoundError(
                    message_ar="الأداة المرجعية غير موجودة", message_en="Reference item not found"
                )
            principal.assert_department(ref.department_id)
            if ref.expiry_date < date.today():
                raise ExpiryGuardError(
                    details={
                        "equipment_code": ref.equipment_code,
                        "expiry_date": ref.expiry_date.isoformat(),
                    },
                    message_ar=(
                        f"الأداة المرجعية {ref.equipment_code} منتهية الصلاحية "
                        f"منذ {ref.expiry_date.isoformat()} — التشغيل ممنوع"
                    ),
                    message_en=(
                        f"Reference item {ref.equipment_code} expired on "
                        f"{ref.expiry_date.isoformat()} — execution blocked"
                    ),
                )

        protocol = await self._active_protocol(instrument.category)
        sequence = await self._next_sequence()

        run = CalibrationRun(
            id=uuid.uuid4(),
            execution_code=self._execution_code(sequence),
            department_id=instrument.department_id,
            instrument_id=instrument.id,
            protocol_id=protocol.id,
            reference_equipment_id=reference_equipment_id,
            run_type=run_type,
            ambient_temp_c=Decimal(str(ambient_temp_c)) if ambient_temp_c is not None else None,
            ambient_humidity=Decimal(str(ambient_humidity)) if ambient_humidity is not None else None,
            limit_source_policy=limit_source_policy,
            overall_status="INCOMPLETE",
            analyst_id=principal.user_id,
            breakdown_component=breakdown_component,
            started_at=datetime.now(timezone.utc),
        )
        self.session.add(run)
        await self.session.flush()

        await self.audit.record(
            action="CALIBRATION_RUN_CREATED",
            entity_type="calibration_run",
            entity_id=run.id,
            actor_label=principal.username,
            actor_id=principal.user_id,
            role_label=principal.primary_role,
            department_id=run.department_id,
            new_values={
                "execution_code": run.execution_code,
                "instrument": instrument.asset_code,
                "run_type": run_type,
                "policy": limit_source_policy,
            },
            reason="بدء تشغيل معايرة وفق البروتوكول المعتمد",
            ip_address=ip,
        )
        return run

    # ────────────────────────────── execute ──────────────────────────────── #

    async def _load_protocol_assets(
        self, protocol_id: uuid.UUID
    ) -> tuple[list[TestDefinition], dict[uuid.UUID, Any], list[AcceptanceLimit], dict[tuple[str, str, str], str]]:
        tests = (
            await self.session.execute(
                select(TestDefinition)
                .where(TestDefinition.protocol_id == protocol_id)
                .order_by(TestDefinition.sequence_order)
            )
        ).scalars().all()
        if not tests:
            raise ConflictError(
                message_ar="البروتوكول لا يحتوي على اختبارات معرّفة",
                message_en="The protocol has no test definitions",
            )

        formulas = (
            await self.session.execute(
                select(FormulaDefinition).where(
                    FormulaDefinition.test_definition_id.in_([t.id for t in tests]),
                    FormulaDefinition.is_active.is_(True),
                )
            )
        ).scalars().all()

        limits = (
            await self.session.execute(
                select(AcceptanceLimit).where(
                    AcceptanceLimit.test_definition_id.in_([t.id for t in tests])
                )
            )
        ).scalars().all()

        # Build the pure-domain view: TestSpec + LimitSpec
        from app.domain.protocol.blueprint import FieldSpec, FormulaSpec, LimitSpec, TestSpec

        domain_tests: list[TestSpec] = []
        formula_by_test: dict[uuid.UUID, list[FormulaDefinition]] = {}
        for f in formulas:
            formula_by_test.setdefault(f.test_definition_id, []).append(f)

        code_by_test_id: dict[uuid.UUID, str] = {}
        for t in tests:
            code_by_test_id[t.id] = t.test_code
            schema = t.input_schema_jsonb or {}
            fields = tuple(
                FieldSpec(
                    key=f["key"],
                    label_ar=f.get("label_ar", f["key"]),
                    label_en=f.get("label_en", f["key"]),
                    type=f.get("type", "number"),
                    unit=f.get("unit"),
                    length=f.get("length"),
                    options=tuple(f["options"]) if f.get("options") else None,
                    required=f.get("required", True),
                )
                for f in schema.get("fields", [])
            )
            specs = tuple(
                FormulaSpec(
                    key=fd.formula_key,
                    expression=fd.expression_text,
                    description_ar=fd.description_ar,
                    description_en=fd.description_en,
                    decimals=fd.rounding_decimals,
                )
                for fd in formula_by_test.get(t.id, [])
            )
            metrics = tuple(schema.get("metrics", []))
            domain_tests.append(
                TestSpec(
                    code=t.test_code,
                    sequence=t.sequence_order,
                    name_ar=t.name_ar,
                    name_en=t.name_en,
                    module=t.module,
                    standard=t.standard_ref,
                    procedure_ar=tuple(t.procedure_ar or ()),
                    fields=fields,
                    formulas=specs,
                    metrics=metrics,
                    chart=(t.chart_config_jsonb or {}).get("type", "none"),
                    mandatory=t.is_mandatory,
                )
            )

        domain_limits: list[LimitSpec] = []
        limit_id_lookup: dict[tuple[str, str, str], str] = {}
        for lim in limits:
            code = code_by_test_id[lim.test_definition_id]
            domain_limits.append(
                LimitSpec(
                    test_code=code,
                    metric_key=lim.metric_key,
                    source_type=lim.source_type,
                    operator=lim.operator,
                    min_value=lim.min_value,
                    max_value=lim.max_value,
                    unit=lim.unit,
                    approval_status=lim.approval_status,
                    note_ar=lim.note_ar,
                    flagged=lim.flagged,
                )
            )
            limit_id_lookup[(code, lim.metric_key, lim.source_type)] = str(lim.id)

        return domain_tests, {t.id: t for t in tests}, domain_limits, limit_id_lookup

    async def execute_run(
        self,
        *,
        run_id: uuid.UUID,
        principal: Principal,
        raw_inputs: dict[str, dict[str, Any]],
        scope_tests: list[str] | None,
        ip: str | None = None,
    ) -> tuple[CalibrationRun, RunOutcome]:
        principal.require("calibration.run")
        run = await self._get_run(run_id, principal)

        if run.is_locked:
            raise LockedResultError()
        if run.analyst_id != principal.user_id and not principal.is_supervisor():
            raise PermissionDeniedError(
                message_ar="لا يمكنك تنفيذ تشغيل بدأه محلل آخر",
                message_en="You cannot execute a run started by another analyst",
            )
        if run.overall_status not in ("INCOMPLETE",):
            raise ConflictError(
                message_ar="تم تنفيذ هذا التشغيل مسبقاً — أنشئ تشغيلاً جديداً أو أعد فتحه وفق الإجراء",
                message_en="This run was already executed — create a new run or reopen per SOP",
            )

        domain_tests, test_by_id, domain_limits, limit_id_lookup = await self._load_protocol_assets(
            run.protocol_id
        )

        # scope: post-breakdown restricts to the mandatory retest matrix
        if run.run_type == "POST_BREAKDOWN" and run.breakdown_component:
            required = set(tests_for_component(run.breakdown_component))
            if scope_tests:
                required |= set(scope_tests)
            scoped = [t for t in domain_tests if t.code in required or t.code == "T01"]
        elif scope_tests:
            unknown = set(scope_tests) - {t.code for t in domain_tests}
            if unknown:
                raise ValidationFailedError(
                    message_ar=f"أكواد اختبار غير معروفة: {', '.join(sorted(unknown))}",
                    message_en="Unknown test codes",
                    field="scope_tests",
                )
            scoped = [t for t in domain_tests if t.code in scope_tests]
        else:
            scoped = list(domain_tests)

        missing_payloads = [t.code for t in scoped if t.mandatory and t.code not in raw_inputs]
        # The scoring engine is CPU-bound: seventy-five formulas evaluated at thirty
        # significant digits, with no I/O at all. Run in a thread, because on the
        # event loop it stalls every other reader in the process — measured at ~1 s
        # per execution during the load test, during which the whole API stopped
        # answering. Nothing here touches the session, so the thread is safe.
        outcome = await asyncio.to_thread(
            execute_run,
            tests=scoped,
            raw_inputs=raw_inputs,
            limits=domain_limits,
            policy_source=run.limit_source_policy,
            limit_id_lookup=limit_id_lookup,
        )

        # Replace any previous partial results (safe: run is not locked yet)
        await self.session.execute(
            CalibrationTestResult.__table__.delete().where(CalibrationTestResult.run_id == run.id)
        )

        for result in outcome.results:
            definition = next(t for t in domain_tests if t.code == result.test_code)
            db_test = next(t for t in test_by_id.values() if t.test_code == result.test_code)
            first_limit = result.metric_evaluations[0] if result.metric_evaluations else None
            self.session.add(
                CalibrationTestResult(
                    id=uuid.uuid4(),
                    run_id=run.id,
                    test_definition_id=db_test.id,
                    test_code=result.test_code,
                    applied_limit_id=uuid.UUID(first_limit.applied_limit_id)
                    if first_limit and first_limit.applied_limit_id
                    else None,
                    applied_limit_source=first_limit.applied_source if first_limit else None,
                    raw_inputs_jsonb=raw_inputs.get(result.test_code, {}),
                    calculated_outputs_jsonb=serialise_outputs(result.outputs),
                    metric_evaluations_jsonb=[e.as_dict() for e in result.metric_evaluations],
                    data_source="MANUAL",
                    status=result.status,
                    notes_ar=result.notes_ar,
                    is_locked=False,
                )
            )

        run.overall_status = outcome.overall
        run.completed_at = datetime.now(timezone.utc)
        run.revision += 1

        await self.audit.record(
            action="CALIBRATION_RUN_EXECUTED",
            entity_type="calibration_run",
            entity_id=run.id,
            actor_label=principal.username,
            actor_id=principal.user_id,
            role_label=principal.primary_role,
            department_id=run.department_id,
            new_values={
                "overall": outcome.overall,
                "summary": outcome.summary(),
                "policy": run.limit_source_policy,
                "tests_in_scope": [t.code for t in scoped],
                "missing_payloads": missing_payloads,
            },
            reason="تنفيذ محرك المعايرة على القراءات الخام",
            ip_address=ip,
        )
        await self.session.flush()

        if outcome.overall == FAIL:
            log.warning(
                "calibration run failed (OOS)",
                extra={"extra_fields": {"run": run.execution_code, "summary": outcome.summary()}},
            )
        return run, outcome

    # ──────────────────────────── review / approve ───────────────────────── #

    async def _assert_signature(self, principal: Principal, password: str) -> None:
        user = await self.session.get(User, principal.user_id)
        if user is None:
            raise NotFoundError()
        valid, _ = verify_password(password, user.password_hash)
        if not valid:
            raise PermissionDeniedError(
                message_ar="كلمة المرور غير صحيحة — التوقيع الإلكتروني مرفوض",
                message_en="Incorrect password — electronic signature rejected",
            )

    async def review(
        self,
        *,
        run_id: uuid.UUID,
        principal: Principal,
        password: str,
        reason: str,
        ip: str | None = None,
    ) -> CalibrationRun:
        principal.require("calibration.review")
        run = await self._get_run(run_id, principal)
        if run.is_locked:
            raise LockedResultError()
        if run.overall_status == "INCOMPLETE":
            raise ConflictError(
                message_ar="لا يمكن مراجعة تشغيل غير مكتمل — نفّذ Run Calibration أولاً",
                message_en="An incomplete run cannot be reviewed — execute it first",
            )
        if run.reviewer_id is not None:
            raise ConflictError(
                message_ar="تم توقيع المراجعة الفنية لهذا التشغيل مسبقاً",
                message_en="This run already carries a technical review signature",
            )
        assert_segregation_of_duties(
            analyst_id=run.analyst_id, reviewer_id=principal.user_id, qa_approver_id=None
        )
        await self._assert_signature(principal, password)

        run.reviewer_id = principal.user_id
        run.reviewed_at = datetime.now(timezone.utc)
        run.revision += 1

        await self.audit.record(
            action="RUN_TECHNICAL_REVIEW_SIGNED",
            entity_type="calibration_run",
            entity_id=run.id,
            actor_label=principal.username,
            actor_id=principal.user_id,
            role_label=principal.primary_role,
            department_id=run.department_id,
            new_values={"reviewer": principal.username, "signed_at": run.reviewed_at.isoformat()},
            reason=reason,
            ip_address=ip,
        )
        await self.session.flush()
        return run

    async def _deviation_context(self, run: CalibrationRun) -> dict:
        """Tell the approver what already exists for this failure.

        Without this the refusal is a dead end: the user is told to raise a
        deviation and cannot tell whether one is already open, already
        investigated, or closed with a retest sitting ready for approval.
        """
        from app.models.deviations import Deviation

        rows = (
            await self.session.execute(
                select(Deviation)
                .where(Deviation.run_id == run.id, Deviation.deleted_at.is_(None))
                .order_by(Deviation.raised_at.desc())
            )
        ).scalars().all()
        if not rows:
            return {"deviation": None, "hint": "raise_deviation"}
        latest = rows[0]
        return {
            "deviation": {
                "id": str(latest.id),
                "reference": latest.reference,
                "status": latest.status,
                "retest_run_id": str(latest.retest_run_id) if latest.retest_run_id else None,
            },
            "hint": {
                "OPEN": "investigate_deviation",
                "INVESTIGATING": "record_investigation_outcome",
                "PENDING_VERIFICATION": "close_deviation",
                "CLOSED": "approve_retest_run",
                "CANCELLED": "raise_deviation",
            }.get(latest.status, "raise_deviation"),
        }

    async def approve(
        self,
        *,
        run_id: uuid.UUID,
        principal: Principal,
        password: str,
        reason: str,
        ip: str | None = None,
    ) -> CalibrationRun:
        principal.require("calibration.approve")
        run = await self._get_run(run_id, principal)
        if run.is_locked:
            raise LockedResultError()
        if run.reviewer_id is None:
            raise ConflictError(
                message_ar="المراجعة الفنية مطلوبة قبل اعتماد ضمان الجودة",
                message_en="Technical review is required before QA approval",
            )
        if run.overall_status in ("FAIL", "INCOMPLETE"):
            raise ConflictError(
                message_ar=(
                    "لا يمكن اعتماد تشغيل غير مطابق أو غير مكتمل — يلزم فتح انحراف OOS "
                    "وإغلاقه بإعادة اختبار ناجحة، ثم اعتماد تشغيل إعادة الاختبار"
                ),
                message_en=(
                    "A failing or incomplete run cannot be approved — raise an OOS "
                    "deviation, close it with a passing retest, and approve the retest run"
                ),
                details=await self._deviation_context(run),
            )
        # A deviation never excuses a failed result. It provides the investigation
        # and, through closure with a passing retest, the evidence that the
        # instrument was restored — but the retest is the run that gets approved,
        # not the run that failed. The message points at the deviation so the
        # approver has somewhere concrete to go instead of a dead end.
        if run.overall_status == UNDER_REVIEW:
            raise LimitGovernanceError(
                message_ar=(
                    "التشغيل قيد المراجعة لأن حدود القبول المطبقة غير معتمدة أو متعارضة. "
                    "يجب حسم حدود القبول أولاً ثم إعادة التنفيذ."
                ),
                message_en=(
                    "The run is UNDER_REVIEW because the applied acceptance limits are "
                    "unapproved or conflicted. Resolve the limits, then re-execute."
                ),
            )
        assert_segregation_of_duties(
            analyst_id=run.analyst_id,
            reviewer_id=run.reviewer_id,
            qa_approver_id=principal.user_id,
        )
        await self._assert_signature(principal, password)

        approved_at = datetime.now(timezone.utc)
        payload = "|".join(
            [
                run.execution_code,
                str(run.instrument_id),
                run.overall_status,
                str(run.analyst_id),
                str(run.reviewer_id),
                str(principal.user_id),
                approved_at.isoformat(),
                str(run.revision),
            ]
        )
        run.qa_approver_id = principal.user_id
        run.qa_approved_at = approved_at
        run.completed_at = run.completed_at or approved_at
        run.certificate_hash = certificate_fingerprint(payload)
        run.is_locked = True
        run.revision += 1

        # lock every child result in the same transaction
        results = (
            await self.session.execute(
                select(CalibrationTestResult).where(CalibrationTestResult.run_id == run.id)
            )
        ).scalars().all()
        for result in results:
            result.is_locked = True

        await self.audit.record(
            action="RUN_QA_APPROVED_AND_LOCKED",
            entity_type="calibration_run",
            entity_id=run.id,
            actor_label=principal.username,
            actor_id=principal.user_id,
            role_label=principal.primary_role,
            department_id=run.department_id,
            old_values={"is_locked": False, "qa_approver": None},
            new_values={
                "is_locked": True,
                "qa_approver": principal.username,
                "certificate_hash": run.certificate_hash,
                "results_locked": len(results),
            },
            reason=reason,
            ip_address=ip,
        )

        # advance the instrument calibration cycle
        instrument = await self.session.get(Instrument, run.instrument_id)
        if instrument is not None:
            instrument.last_calibration_date = approved_at.date()
            instrument.next_due_date = approved_at.date() + timedelta(
                days=instrument.calibration_freq_days
            )

        await self.session.flush()
        return run

    # ─────────────────────────────── reads ───────────────────────────────── #

    async def get_run(self, run_id: uuid.UUID, principal: Principal) -> CalibrationRun:
        return await self._get_run(run_id, principal)

    async def list_runs(
        self,
        *,
        principal: Principal,
        page: int = 1,
        page_size: int = 25,
        status: str | None = None,
        instrument_id: uuid.UUID | None = None,
    ) -> tuple[list[CalibrationRun], int]:
        principal.require("instruments.view")
        stmt = select(CalibrationRun)
        count_stmt = select(func.count()).select_from(CalibrationRun)

        conditions = []
        if not principal.is_supervisor():
            conditions.append(CalibrationRun.department_id == principal.department_id)
        if status:
            conditions.append(CalibrationRun.overall_status == status)
        if instrument_id:
            conditions.append(CalibrationRun.instrument_id == instrument_id)
        for cond in conditions:
            stmt = stmt.where(cond)
            count_stmt = count_stmt.where(cond)

        total = (await self.session.execute(count_stmt)).scalar_one()
        rows = (
            await self.session.execute(
                stmt.order_by(CalibrationRun.started_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
        return list(rows), int(total)

    async def pending_approvals(self, principal: Principal) -> list[CalibrationRun]:
        principal.require("calibration.approve")
        stmt = select(CalibrationRun).where(
            CalibrationRun.is_locked.is_(False),
            CalibrationRun.overall_status.in_(["PASS", "UNDER_REVIEW"]),
        )
        if not principal.is_supervisor():
            stmt = stmt.where(CalibrationRun.department_id == principal.department_id)
        return list((await self.session.execute(stmt)).scalars().all())

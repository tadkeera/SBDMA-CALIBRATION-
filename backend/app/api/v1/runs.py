from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Header, Query, Request

from app.api.deps import PrincipalDep, SessionDep, client_ip
from app.core.exceptions import ValidationFailedError
from app.domain.scoring.engine import serialise_outputs
from app.schemas.auth import SignaturePayload
from app.schemas.common import ok
from app.schemas.runs import ExecuteRunRequest, RunOut, RunSummaryOut
from app.services.run_service import RunService

router = APIRouter(prefix="/runs", tags=["runs"])

IdempotencyKey = Annotated[str | None, Header(alias="Idempotency-Key")]


def _serialise_run(run) -> RunOut:  # noqa: ANN001
    return RunOut(
        id=run.id,
        execution_code=run.execution_code,
        instrument_id=run.instrument_id,
        run_type=run.run_type,
        overall_status=run.overall_status,
        analyst_id=run.analyst_id,
        reviewer_id=run.reviewer_id,
        qa_approver_id=run.qa_approver_id,
        limit_source_policy=run.limit_source_policy,
        ambient_temp_c=str(run.ambient_temp_c) if run.ambient_temp_c is not None else None,
        ambient_humidity=str(run.ambient_humidity) if run.ambient_humidity is not None else None,
        certificate_hash=run.certificate_hash,
        is_locked=run.is_locked,
        revision=run.revision,
        started_at=run.started_at,
        completed_at=run.completed_at,
        reviewed_at=run.reviewed_at,
        qa_approved_at=run.qa_approved_at,
        breakdown_component=run.breakdown_component,
        results=[
            {
                "test_code": r.test_code,
                "status": r.status,
                "metric_evaluations": r.metric_evaluations_jsonb or [],
                "notes_ar": r.notes_ar,
                "outputs": r.calculated_outputs_jsonb or {},
                # stored verbatim at execution time; the laboratory charts and any
                # re-evaluation must read the same numbers that were signed for.
                "raw_inputs": r.raw_inputs_jsonb or {},
            }
            for r in sorted(run.results, key=lambda x: x.test_code)
        ],
    )


@router.post("", summary="إنشاء تشغيل معايرة", status_code=201)
async def create_run(
    payload: dict,
    request: Request,
    session: SessionDep,
    principal: PrincipalDep,
    idempotency_key: IdempotencyKey = None,
):
    from app.schemas.runs import RunCreateRequest

    if not idempotency_key:
        raise ValidationFailedError(
            message_ar="ترويسة Idempotency-Key مطلوبة لمنع تكرار إنشاء التشغيل",
            message_en="An Idempotency-Key header is required to prevent duplicate runs",
            field="Idempotency-Key",
        )
    data = RunCreateRequest.model_validate(payload)
    service = RunService(session)
    run = await service.create_run(
        principal=principal,
        instrument_id=data.instrument_id,
        reference_equipment_id=data.reference_equipment_id,
        run_type=data.run_type,
        ambient_temp_c=data.ambient_temp_c,
        ambient_humidity=data.ambient_humidity,
        limit_source_policy=data.limit_source_policy,
        breakdown_component=data.breakdown_component,
        ip=client_ip(request),
    )
    await session.commit()
    await session.refresh(run)
    return ok(_serialise_run(run).model_dump(mode="json"))


@router.post("/{run_id}/execute", summary="تشغيل محرك المعايرة")
async def execute_run(
    run_id: uuid.UUID,
    payload: ExecuteRunRequest,
    request: Request,
    session: SessionDep,
    principal: PrincipalDep,
):
    service = RunService(session)
    run, outcome = await service.execute_run(
        run_id=run_id,
        principal=principal,
        raw_inputs=payload.raw_inputs,
        scope_tests=payload.scope_tests,
        ip=client_ip(request),
    )
    await session.commit()
    await session.refresh(run)
    return ok(
        {
            "run": _serialise_run(run).model_dump(mode="json"),
            "overall": outcome.overall,
            "summary": outcome.summary(),
            "results": [
                {
                    "test_code": r.test_code,
                    "status": r.status,
                    "outputs": serialise_outputs(r.outputs),
                    "metric_evaluations": [e.as_dict() for e in r.metric_evaluations],
                    "notes_ar": r.notes_ar,
                    "formula_errors": r.formula_errors,
                }
                for r in outcome.results
            ],
        }
    )


@router.post("/{run_id}/review", summary="توقيع المراجعة الفنية")
async def review_run(
    run_id: uuid.UUID,
    payload: SignaturePayload,
    request: Request,
    session: SessionDep,
    principal: PrincipalDep,
):
    service = RunService(session)
    run = await service.review(
        run_id=run_id,
        principal=principal,
        password=payload.password,
        reason=payload.reason,
        ip=client_ip(request),
    )
    await session.commit()
    await session.refresh(run)
    return ok(_serialise_run(run).model_dump(mode="json"))


@router.post("/{run_id}/approve", summary="اعتماد ضمان الجودة النهائي وإقفال النتائج")
async def approve_run(
    run_id: uuid.UUID,
    payload: SignaturePayload,
    request: Request,
    session: SessionDep,
    principal: PrincipalDep,
):
    service = RunService(session)
    run = await service.approve(
        run_id=run_id,
        principal=principal,
        password=payload.password,
        reason=payload.reason,
        ip=client_ip(request),
    )
    await session.commit()
    await session.refresh(run)
    return ok(_serialise_run(run).model_dump(mode="json"))


@router.get("", summary="قائمة التشغيلات")
async def list_runs(
    session: SessionDep,
    principal: PrincipalDep,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    status: str | None = None,
    instrument_id: uuid.UUID | None = None,
):
    service = RunService(session)
    rows, total = await service.list_runs(
        principal=principal,
        page=page,
        page_size=page_size,
        status=status,
        instrument_id=instrument_id,
    )
    pages = (total + page_size - 1) // page_size if page_size else 0
    return ok(
        [
            RunSummaryOut(
                id=r.id,
                execution_code=r.execution_code,
                instrument_id=r.instrument_id,
                overall_status=r.overall_status,
                run_type=r.run_type,
                analyst_id=r.analyst_id,
                is_locked=r.is_locked,
                started_at=r.started_at,
                completed_at=r.completed_at,
            ).model_dump(mode="json")
            for r in rows
        ],
        meta={"page": page, "page_size": page_size, "total": total, "pages": pages},
    )


@router.get("/{run_id}", summary="تفاصيل تشغيل")
async def get_run(run_id: uuid.UUID, session: SessionDep, principal: PrincipalDep):
    service = RunService(session)
    run = await service.get_run(run_id, principal)
    await session.refresh(run)
    return ok(_serialise_run(run).model_dump(mode="json"))


@router.get("/pending/approvals", summary="التشغيلات بانتظار الاعتماد")
async def pending(session: SessionDep, principal: PrincipalDep):
    service = RunService(session)
    rows = await service.pending_approvals(principal)
    return ok(
        [
            RunSummaryOut(
                id=r.id,
                execution_code=r.execution_code,
                instrument_id=r.instrument_id,
                overall_status=r.overall_status,
                run_type=r.run_type,
                analyst_id=r.analyst_id,
                is_locked=r.is_locked,
                started_at=r.started_at,
                completed_at=r.completed_at,
            ).model_dump(mode="json")
            for r in rows
        ]
    )

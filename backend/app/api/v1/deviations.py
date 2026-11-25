"""OOS deviations: raise, investigate, close.

Three permissions, three phases. The service enforces the rules; these routes
only translate HTTP to calls.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, Request

from app.api.deps import PrincipalDep, SessionDep, client_ip
from app.schemas.common import ok
from app.schemas.deviations import (
    CancelDeviationRequest,
    CloseDeviationRequest,
    InvestigateDeviationRequest,
    StartInvestigationRequest,
    RaiseDeviationRequest,
)
from app.services.deviation_service import DeviationService, serialise

router = APIRouter(prefix="/deviations", tags=["deviations"])


@router.get("", summary="سجل الانحرافات")
async def list_deviations(
    session: SessionDep,
    principal: PrincipalDep,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    status: str | None = None,
    run_id: uuid.UUID | None = None,
):
    service = DeviationService(session)
    rows, total = await service.list_deviations(
        principal, page=page, page_size=page_size, status=status, run_id=run_id
    )
    return ok(
        [serialise(d) for d in rows],
        meta={
            "page": page,
            "page_size": page_size,
            "total": total,
            "pages": (total + page_size - 1) // page_size,
        },
    )


@router.get("/{deviation_id}", summary="تفاصيل انحراف")
async def get_deviation(deviation_id: uuid.UUID, session: SessionDep, principal: PrincipalDep):
    service = DeviationService(session)
    return ok(serialise(await service.get(deviation_id, principal)))


@router.post("", summary="فتح انحراف OOS", status_code=201)
async def raise_deviation(
    payload: RaiseDeviationRequest,
    request: Request,
    session: SessionDep,
    principal: PrincipalDep,
):
    """Raise a deviation against a failed or incomplete run.

    A passing run is refused here and again by a database trigger: the paper trail
    must not claim to investigate a result that was acceptable.
    """
    service = DeviationService(session)
    deviation = await service.raise_deviation(
        principal,
        run_id=payload.run_id,
        title=payload.title,
        description=payload.description,
        classification=payload.classification,
        ip=client_ip(request),
    )
    await session.commit()
    return ok(serialise(deviation))


@router.post("/{deviation_id}/investigate/start", summary="بدء التحقيق")
async def start_investigation(
    deviation_id: uuid.UUID,
    payload: StartInvestigationRequest,
    request: Request,
    session: SessionDep,
    principal: PrincipalDep,
):
    """Open the investigation. Separate from the conclusion date on purpose."""
    service = DeviationService(session)
    deviation = await service.start_investigation(
        principal, deviation_id, plan=payload.plan, ip=client_ip(request)
    )
    await session.commit()
    return ok(serialise(deviation))


@router.post("/{deviation_id}/investigate", summary="تسجيل التحقيق والسبب الجذري")
async def investigate_deviation(
    deviation_id: uuid.UUID,
    payload: InvestigateDeviationRequest,
    request: Request,
    session: SessionDep,
    principal: PrincipalDep,
):
    service = DeviationService(session)
    deviation = await service.investigate(
        principal,
        deviation_id,
        root_cause_category=payload.root_cause_category,
        root_cause=payload.root_cause,
        immediate_action=payload.immediate_action,
        ip=client_ip(request),
    )
    await session.commit()
    return ok(serialise(deviation))


@router.post("/{deviation_id}/close", summary="إغلاق الانحراف بقرار CAPA")
async def close_deviation(
    deviation_id: uuid.UUID,
    payload: CloseDeviationRequest,
    request: Request,
    session: SessionDep,
    principal: PrincipalDep,
):
    service = DeviationService(session)
    deviation = await service.close(
        principal,
        deviation_id,
        capa_action=payload.capa_action,
        capa_notes=payload.capa_notes,
        closure_notes=payload.closure_notes,
        retest_run_id=payload.retest_run_id,
        ip=client_ip(request),
    )
    await session.commit()
    return ok(serialise(deviation))


@router.post("/{deviation_id}/cancel", summary="إلغاء انحراف فُتح بالخطأ")
async def cancel_deviation(
    deviation_id: uuid.UUID,
    payload: CancelDeviationRequest,
    request: Request,
    session: SessionDep,
    principal: PrincipalDep,
):
    service = DeviationService(session)
    deviation = await service.cancel(
        principal, deviation_id, reason=payload.reason, ip=client_ip(request)
    )
    await session.commit()
    return ok(serialise(deviation))

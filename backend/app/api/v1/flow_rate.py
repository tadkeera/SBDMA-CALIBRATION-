"""Flow-rate (T02) endpoints — definition for the dedicated page and server-side check.

Two routes, both thin: the arithmetic lives in ``app.domain.protocol.flow_rate`` and the
limit resolution in ``FlowRateService``. The POST route exists because the page's live panel
is a *preview*; what the laboratory stands behind is the server's own recomputation, and the
API is where that happens before anything is stored.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import PrincipalDep, SessionDep
from app.schemas.common import ok
from app.services.flow_rate_service import FlowRateService

router = APIRouter(prefix="/flow-rate", tags=["flow-rate"])


class FlowRateCalculateRequest(BaseModel):
    #: three rows of up to ten readings; empty cells are allowed while the grid is filled
    readings: list[list[float | str | None]] = Field(default_factory=list)


@router.get("", summary="تعريف اختبار معدل التدفق وحدوده المعتمدة")
async def flow_rate_definition(session: SessionDep, principal: PrincipalDep) -> Any:
    data = await FlowRateService(session).definition(principal)
    return ok(data)


@router.post("/calculate", summary="إعادة حساب شبكة القراءات على الخادم")
async def flow_rate_calculate(
    payload: FlowRateCalculateRequest, session: SessionDep, principal: PrincipalDep
) -> Any:
    readings: list[list[Any]] = [list(row) for row in payload.readings]
    data = await FlowRateService(session).evaluate(principal, readings)
    return ok(data)

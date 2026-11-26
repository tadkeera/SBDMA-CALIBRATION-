"""Flow-rate service — the limits the dedicated page shows and the verdict it stores.

The page must not carry a hard-coded ±2.0 %: the number that decides PASS belongs to the
approved limit table, and an administrator who re-approves a different limit must see the
page change with it. This service resolves the active protocol for the instrument category,
takes the authority limit rows for the two flow-rate metrics, and hands the page the same
numbers the server engine will apply on submission.

Two entry points only:
  * ``definition()`` — set points, limits and the acceptance band for the page header,
  * ``evaluate()`` — the server-side recomputation of a submitted grid.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, ValidationFailedError as ValidationError
from app.core.rbac import Principal
from app.domain.protocol.flow_rate import (
    ACCURACY_PCT,
    MAX_RSD_PCT,
    READINGS_PER_SET_POINT,
    SET_POINTS,
    evaluate_flow_rate,
)
from app.models.protocol import AcceptanceLimit, CalibrationProtocol, TestDefinition

TEST_CODE = "T02"
INSTRUMENT_CATEGORY = "HPLC-UV"


class FlowRateService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _limits(self) -> tuple[Decimal, Decimal, dict[str, Any]]:
        protocol = (
            await self.session.execute(
                select(CalibrationProtocol)
                .where(
                    CalibrationProtocol.instrument_category == INSTRUMENT_CATEGORY,
                    CalibrationProtocol.status == "APPROVED",
                )
                .order_by(CalibrationProtocol.version.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if protocol is None:
            raise ConflictError(
                message_ar="لا يوجد بروتوكول معتمد لهذه الفئة من الأجهزة",
                message_en="No approved protocol exists for this instrument category",
            )
        definition = (
            await self.session.execute(
                select(TestDefinition).where(
                    TestDefinition.protocol_id == protocol.id,
                    TestDefinition.test_code == TEST_CODE,
                )
            )
        ).scalar_one_or_none()
        if definition is None:
            raise ConflictError(
                message_ar="اختبار معدل التدفق غير معرّف في البروتوكول المعتمد",
                message_en="The flow-rate test is not defined in the approved protocol",
            )

        rows = (
            await self.session.execute(
                select(AcceptanceLimit).where(
                    AcceptanceLimit.test_definition_id == definition.id,
                    AcceptanceLimit.source_type == "AUTHORITY_LIMIT",
                    AcceptanceLimit.metric_key.in_(("max_abs_error", "max_rsd")),
                )
            )
        ).scalars().all()
        by_metric = {row.metric_key: row for row in rows}

        # A metric without an approved authority limit cannot yield a verdict: the page says
        # so instead of quietly falling back to a number that was never approved.
        missing = [m for m in ("max_abs_error", "max_rsd") if m not in by_metric]
        if missing:
            raise ConflictError(
                message_ar=f"لا يوجد حد معتمد للمقاييس: {', '.join(missing)}",
                message_en=f"No approved authority limit for: {', '.join(missing)}",
                details={"missing_metrics": missing},
            )

        accuracy_row = by_metric["max_abs_error"]
        rsd_row = by_metric["max_rsd"]
        # A percentage limit on the page reads "2.0", not "2.00000000" and not "2".
        accuracy = (
            Decimal(str(accuracy_row.max_value)) if accuracy_row.max_value is not None else ACCURACY_PCT
        ).quantize(Decimal("0.1"))
        rsd = (
            Decimal(str(rsd_row.max_value)) if rsd_row.max_value is not None else MAX_RSD_PCT
        ).quantize(Decimal("0.1"))

        meta = {
            "protocol_code": protocol.protocol_code,
            "protocol_version": protocol.version,
            "test_definition_id": str(definition.id),
            "test_name_ar": definition.name_ar,
            "test_name_en": definition.name_en,
            "limits": {
                "accuracy": {
                    "id": str(accuracy_row.id),
                    "value": str(accuracy),
                    "unit": accuracy_row.unit,
                    "approval_status": accuracy_row.approval_status,
                    "note_ar": accuracy_row.note_ar,
                },
                "rsd": {
                    "id": str(rsd_row.id),
                    "value": str(rsd),
                    "unit": rsd_row.unit,
                    "approval_status": rsd_row.approval_status,
                    "note_ar": rsd_row.note_ar,
                },
            },
        }
        return accuracy, rsd, meta

    async def definition(self, principal: Principal) -> dict[str, Any]:
        """What the page needs before a single reading is typed."""
        principal.require("instruments.view")
        accuracy, rsd, meta = await self._limits()
        points = []
        for index, nominal in enumerate(SET_POINTS):
            upper = (nominal * (1 + accuracy / Decimal(100))).quantize(Decimal("0.001"))
            lower = (nominal * (1 - accuracy / Decimal(100))).quantize(Decimal("0.001"))
            points.append(
                {
                    "index": index,
                    "nominal": str(nominal),
                    "unit": "mL/min",
                    "lower_limit": str(lower),
                    "upper_limit": str(upper),
                    "readings_per_set_point": READINGS_PER_SET_POINT,
                    "field_key": ("flow_p1000", "flow_p1500", "flow_p2000")[index],
                }
            )
        return {
            "test_code": TEST_CODE,
            "set_points": points,
            "readings_per_set_point": READINGS_PER_SET_POINT,
            "acceptance": {
                "accuracy_pct": str(accuracy),
                "accuracy_band": f"{Decimal(100) - accuracy}–{Decimal(100) + accuracy}",
                "rsd_pct": str(rsd),
            },
            **meta,
        }

    async def evaluate(
        self, principal: Principal, readings: list[list[Any]]
    ) -> dict[str, Any]:
        """Recompute a submitted grid on the server. The client preview never decides."""
        principal.require("calibration.run")
        accuracy, rsd, meta = await self._limits()

        if not isinstance(readings, list) or len(readings) != len(SET_POINTS):
            raise ValidationError(
                message_ar="شبكة القراءات يجب أن تحتوي على ثلاث نقاط ضبط",
                message_en="The readings grid must contain three set points",
                field="readings",
            )
        for index, row in enumerate(readings):
            if not isinstance(row, list):
                raise ValidationError(
                    message_ar=f"قراءات نقطة الضبط {index + 1} غير صالحة",
                    message_en=f"Set point {index + 1} readings are not a list",
                    field="readings",
                )
            if len(row) > READINGS_PER_SET_POINT:
                raise ValidationError(
                    message_ar=f"نقطة الضبط {index + 1} تحتوي أكثر من {READINGS_PER_SET_POINT} قراءة",
                    message_en=f"Set point {index + 1} has more than {READINGS_PER_SET_POINT} readings",
                    field="readings",
                )

        evaluation = evaluate_flow_rate(readings, accuracy_limit=accuracy, rsd_limit=rsd)
        return {**evaluation.as_dict(), **meta}

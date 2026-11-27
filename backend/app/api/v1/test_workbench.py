"""Per-test definition and live recomputation.

The laboratory works one test at a time: open a unit, open a test, enter the readings,
watch the acceptance comparison turn green or red, press **Run Calibration**, and only
then save. That needs two things the run-level endpoints cannot give:

``GET /tests/{code}/definition``
    the approved field list, formulas and the limits that will be applied *for this
    instrument's category and the chosen limit-source policy*. The page renders itself
    from this answer, so a field added to the protocol appears without a frontend
    release, and the acceptance values shown are the ones stored in PostgreSQL rather
    than a copy compiled into the browser bundle.

``POST /tests/{code}/evaluate``
    the server's own recomputation of the entered readings — mean, SD, %RSD, deviation,
    every formula in the protocol — with each metric judged against the applied limit.
    The page's live panel is a preview; this is the record. Nothing is stored, nothing is
    locked, and the answer is the same engine that will judge the saved run, so a
    disagreement between the preview and the certificate can only be a bug in the
    preview.

Both routes are read-only: no audit entry is written for a calculation the analyst may
repeat fifty times while filling a grid. The *save* is what the audit trail records.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import PrincipalDep, SessionDep
from app.core.exceptions import NotFoundError, ValidationFailedError
from app.domain.protocol.blueprint import LIMITS, TestSpec, test_by_code
from app.domain.protocol.reference_manual import PROCEDURES_EN
from app.domain.scoring.engine import execute_test, serialise_outputs
from app.models.assets import Instrument
from app.models.protocol import AcceptanceLimit, CalibrationProtocol, TestDefinition
from app.schemas.common import ok

router = APIRouter(prefix="/tests", tags=["tests"])


class TestEvaluateRequest(BaseModel):
    """The readings as entered. Keys are protocol field keys, values are scalars or lists."""

    raw_inputs: dict[str, Any] = Field(default_factory=dict)
    instrument_id: uuid.UUID | None = None
    limit_source_policy: str | None = None


# ────────────────────────────── protocol helpers ───────────────────────────── #


async def _active_protocol(session, instrument_id: uuid.UUID | None, principal) -> CalibrationProtocol:
    """The approved protocol that governs this unit (or the laboratory's default)."""
    category: str | None = None
    if instrument_id is not None:
        instrument = await session.get(Instrument, instrument_id)
        if instrument is None or instrument.deleted_at is not None:
            raise NotFoundError(message_ar="الجهاز غير موجود", message_en="Instrument not found")
        principal.assert_department(instrument.department_id)
        category = instrument.category
    stmt = select(CalibrationProtocol).where(CalibrationProtocol.status == "APPROVED")
    if category:
        stmt = stmt.where(CalibrationProtocol.instrument_category == category)
    protocol = (
        await session.execute(stmt.order_by(CalibrationProtocol.version.desc()).limit(1))
    ).scalar_one_or_none()
    if protocol is None:
        raise NotFoundError(
            message_ar="لا يوجد بروتوكول معتمد لهذه الفئة",
            message_en="No approved protocol exists for this category",
        )
    return protocol


async def _definition_and_limits(session, protocol: CalibrationProtocol, test_code: str):
    definition = (
        await session.execute(
            select(TestDefinition).where(
                TestDefinition.protocol_id == protocol.id,
                TestDefinition.test_code == test_code,
            )
        )
    ).scalar_one_or_none()
    if definition is None:
        raise NotFoundError(
            message_ar=f"الاختبار {test_code} غير موجود في البروتوكول المعتمد",
            message_en=f"Test {test_code} is not part of the approved protocol",
        )
    limits = (
        await session.execute(
            select(AcceptanceLimit).where(AcceptanceLimit.test_definition_id == definition.id)
        )
    ).scalars().all()
    return definition, limits


def _limit_view(row: AcceptanceLimit) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "metric_key": row.metric_key,
        "source_type": row.source_type,
        "operator": row.operator,
        "min_value": None if row.min_value is None else str(row.min_value),
        "max_value": None if row.max_value is None else str(row.max_value),
        "unit": row.unit,
        "approval_status": row.approval_status,
    }


def _domain_tests(test_code: str) -> TestSpec:
    spec = test_by_code(test_code)
    if spec is None:
        raise NotFoundError(
            message_ar=f"الاختبار {test_code} غير معروف",
            message_en=f"Unknown test {test_code}",
        )
    return spec


# ──────────────────────────────── endpoints ───────────────────────────────── #


@router.get("/{test_code}/definition", summary="تعريف اختبار واحد وحقوله وحدوده المطبقة")
async def test_definition(
    test_code: str,
    session: SessionDep,
    principal: PrincipalDep,
    instrument_id: uuid.UUID | None = None,
    limit_source_policy: str | None = None,
) -> Any:
    principal.require("instruments.view")
    code = test_code.upper()
    spec = _domain_tests(code)
    protocol = await _active_protocol(session, instrument_id, principal)
    definition, limits = await _definition_and_limits(session, protocol, code)

    fields = (definition.input_schema_jsonb or {}).get("fields") or []
    # Every limit the test carries, plus the resolved one per metric under the requested
    # policy, so the page can print the number that will actually be applied while still
    # letting the analyst inspect the other sources.
    resolved: dict[str, dict[str, Any]] = {}
    policy = (limit_source_policy or "AUTHORITY_LIMIT").upper()
    for row in limits:
        resolved.setdefault(row.metric_key, {})
    for row in limits:
        if row.source_type == policy:
            resolved[row.metric_key] = _limit_view(row)
        elif not resolved.get(row.metric_key):
            resolved[row.metric_key] = _limit_view(row)

    return ok(
        {
            "test_code": code,
            "name_ar": definition.name_ar,
            "name_en": definition.name_en,
            "module": definition.module,
            "standard_ref": definition.standard_ref,
            "is_active": definition.is_active,
            "protocol_code": protocol.protocol_code,
            "protocol_version": protocol.version,
            "limit_source_policy": policy,
            "fields": fields,
            "formulas": [
                {
                    "key": formula.formula_key,
                    "expression": formula.expression_text,
                    "description_ar": formula.description_ar,
                    "description_en": formula.description_en,
                    "decimals": formula.rounding_decimals,
                }
                for formula in (definition.formulas or [])
            ],
            "metrics": list(spec.metrics),
            "chart": spec.chart,
            # the English procedure is the documentation of record (USP/ISO wording); the
            # Arabic translation stays in the database as the translation of record
            "procedure_en": list(PROCEDURES_EN.get(code, ())),
            "procedure_ar": list(spec.procedure_ar),
            "limits": [_limit_view(row) for row in limits],
            "resolved_limits": resolved,
        }
    )


@router.post("/{test_code}/evaluate", summary="إعادة حساب قراءات اختبار على الخادم")
async def test_evaluate(
    test_code: str,
    payload: TestEvaluateRequest,
    session: SessionDep,
    principal: PrincipalDep,
) -> Any:
    """Recompute one test from the readings as entered — nothing is written."""
    principal.require("instruments.view")
    code = test_code.upper()
    spec = _domain_tests(code)
    protocol = await _active_protocol(session, payload.instrument_id, principal)
    _definition, limits = await _definition_and_limits(session, protocol, code)

    domain_limits = [row for row in LIMITS if row.test_code == code]
    policy = (payload.limit_source_policy or "AUTHORITY_LIMIT").upper()
    # Only the limits of the *approved* protocol version may judge a reading: a stale
    # protocol row in the database must not decide a verdict the certificate quotes.
    allowed = {(row.metric_key, row.source_type) for row in limits}
    domain_limits = [row for row in domain_limits if (row.metric_key, row.source_type) in allowed]
    limit_id_lookup = {
        (row.metric_key, row.source_type, row.approval_status): str(row.id) for row in limits
    }

    # The engine is CPU-bound; keep it off the event loop for the same reason the run
    # execution does (see docs/load-test.md).
    outcome = await asyncio.to_thread(
        execute_test,
        spec,
        payload.raw_inputs.get(code, payload.raw_inputs),
        limits=domain_limits,
        policy_source=policy,
        limit_id_lookup=limit_id_lookup,
    )

    if outcome.formula_errors:
        raise ValidationFailedError(
            message_ar="تعذر حساب أحد عناصر الاختبار: " + "; ".join(outcome.formula_errors),
            message_en="A formula could not be evaluated: " + "; ".join(outcome.formula_errors),
            field="raw_inputs",
        )

    # Signal series are returned separately so the charts can be drawn from the same
    # numbers the verdict used, without the browser having to re-derive anything.
    entered = payload.raw_inputs.get(code, payload.raw_inputs)
    series_keys = {field.key for field in spec.fields if field.type in ("series", "spectrum")}
    signals = {key: value for key, value in entered.items() if key in series_keys}
    stats = _statistics(signals)

    return ok(
        {
            "test_code": code,
            "status": outcome.status,
            "outputs": serialise_outputs(outcome.outputs),
            "metrics": [evaluation.as_dict() for evaluation in outcome.metric_evaluations],
            "notes_ar": outcome.notes_ar,
            "signals": signals,
            "statistics": stats,
            "protocol_code": protocol.protocol_code,
            "protocol_version": protocol.version,
            "limit_source_policy": policy,
        }
    )


def _statistics(series: dict[str, Any]) -> dict[str, Any]:
    """Mean, sample SD, %RSD, min, max and n for each entered series.

    Computed with the same Decimal helpers the engine uses (``mean``/``sd``/``rsd``), so
    the panel the analyst watches and the record that is saved cannot disagree on the
    definition of a standard deviation.
    """
    from decimal import Decimal

    from app.domain.protocol.flow_rate import mean, rsd, sample_sd

    out: dict[str, Any] = {}
    for key, raw in series.items():
        values: list[float] = []
        for item in raw if isinstance(raw, list) else [raw]:
            try:
                values.append(float(str(item)))
            except (TypeError, ValueError):
                continue
        if not values:
            continue
        dec = [Decimal(str(value)) for value in values]
        average = mean(dec)
        spread = sample_sd(dec)
        relative = rsd(dec)
        out[key] = {
            "n": len(values),
            "mean": None if average is None else str(round(average, 6)),
            "sd": None if spread is None else str(round(spread, 6)),
            "rsd_pct": None if relative is None else str(round(relative, 4)),
            "min": str(min(values)),
            "max": str(max(values)),
            "deviation": None
            if average is None
            else str(round(max(abs(value - float(average)) for value in values), 6)),
        }
    return out

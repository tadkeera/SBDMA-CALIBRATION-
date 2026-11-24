"""Seed the SHIMADZU-LC2050C-UV-CAL protocol from the authoritative blueprint.

Nothing here is invented: tests, fields, formulas, limits and the breakdown
matrix are read directly from app.domain.protocol.blueprint, the single source
of truth transcribed from the comparative report.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.protocol.blueprint import (
    LIMITS,
    PROTOCOL_CODE,
    PROTOCOL_TITLE_AR,
    PROTOCOL_TITLE_EN,
    PROTOCOL_VERSION,
    TESTS,
)
from app.models.protocol import (
    AcceptanceLimit,
    CalibrationProtocol,
    FormulaDefinition,
    TestDefinition,
)

INSTRUMENT_CATEGORY = "HPLC-UV"


async def seed_protocol(session: AsyncSession) -> dict[str, int]:
    created = {"protocol": 0, "tests": 0, "limits": 0, "formulas": 0}

    existing = (
        await session.execute(
            select(CalibrationProtocol).where(
                CalibrationProtocol.protocol_code == PROTOCOL_CODE,
                CalibrationProtocol.version == PROTOCOL_VERSION,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return created | {"skipped": 1}  # idempotent

    protocol = CalibrationProtocol(
        id=uuid.uuid4(),
        protocol_code=PROTOCOL_CODE,
        instrument_category=INSTRUMENT_CATEGORY,
        title_ar=PROTOCOL_TITLE_AR,
        title_en=PROTOCOL_TITLE_EN,
        version=PROTOCOL_VERSION,
        status="APPROVED",
        notes_ar=(
            "بروتوكول مستخرج من التقرير المقارن (مصفوفة 2.1) ومصفوفة إغلاق الفجوات (2.4). "
            "الحدود المصنّفة معيبة أو متعارضة مُسجّلة بحالة CONFLICT_REQUIRES_QA "
            "ولا يمكن أن تُنتج نتيجة PASS صامتة."
        ),
    )
    session.add(protocol)
    await session.flush()
    created["protocol"] = 1

    test_id_by_code: dict[str, uuid.UUID] = {}
    for spec in TESTS:
        definition = TestDefinition(
            id=uuid.uuid4(),
            protocol_id=protocol.id,
            test_code=spec.code,
            sequence_order=spec.sequence,
            module=spec.module,
            name_ar=spec.name_ar,
            name_en=spec.name_en,
            standard_ref=spec.standard,
            procedure_ar=list(spec.procedure_ar),
            procedure_en=None,
            input_schema_jsonb={
                "fields": [asdict(f) | {"options": list(f.options) if f.options else None} for f in spec.fields],
                "metrics": list(spec.metrics),
            },
            chart_config_jsonb={"type": spec.chart},
            is_mandatory=spec.mandatory,
        )
        session.add(definition)
        test_id_by_code[spec.code] = definition.id
        created["tests"] += 1

        for f in spec.formulas:
            session.add(
                FormulaDefinition(
                    id=uuid.uuid4(),
                    test_definition_id=definition.id,
                    formula_key=f.key,
                    description_ar=f.description_ar,
                    description_en=f.description_en,
                    expression_text=f.expression,
                    rounding_decimals=f.decimals,
                    version=1,
                    is_active=True,
                )
            )
            created["formulas"] += 1
    await session.flush()

    for limit in LIMITS:
        test_id = test_id_by_code.get(limit.test_code)
        if test_id is None:  # pragma: no cover - blueprint integrity guard
            raise RuntimeError(f"limit references unknown test {limit.test_code}")
        session.add(
            AcceptanceLimit(
                id=uuid.uuid4(),
                test_definition_id=test_id,
                metric_key=limit.metric_key,
                source_type=limit.source_type,
                operator=limit.operator,
                min_value=limit.min_value,
                max_value=limit.max_value,
                unit=limit.unit,
                approval_status=limit.approval_status,
                note_ar=limit.note_ar,
                flagged=limit.flagged,
                approved_at=None,
            )
        )
        created["limits"] += 1

    await session.flush()
    return created

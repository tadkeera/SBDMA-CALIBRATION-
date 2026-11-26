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

from app.domain.protocol.reference_manual import MANUAL, PROCEDURES_EN
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


def documentation_payload(code: str) -> dict:
    """The documentary half of a test definition: English steps + manual entry.

    Kept as one function so the seed, the documentation sync and the API all agree on
    the shape that gets stored. Nothing in the payload is measurement data.
    """
    entry = MANUAL[code]
    return {
        "overview_en": entry.overview_en,
        "ideal_readings": [
            {"field": row.field, "value": row.value, "note_en": row.note_en}
            for row in entry.ideal_readings
        ],
        "evaluation": [{"metric": key, "text_en": text} for key, text in entry.evaluation_en],
        "references": list(entry.references),
        "limit_notes": list(entry.limit_notes),
    }


async def sync_test_documentation(session: AsyncSession) -> dict[str, int]:
    """Fill in documentation columns that are missing, and never overwrite them.

    The protocol rows in a live deployment were seeded when ``procedure_en`` and
    ``reference_jsonb`` did not exist. Those columns are documentary — no limit, formula
    or run depends on them — so writing them in place is safe and avoids publishing a
    duplicate protocol version that would fragment run history. The rule is *fill a null,
    never clobber*: if an administrator has already curated a text, the seed leaves it
    alone. Idempotent: a second call reports zeros.
    """
    filled = {"procedure_en": 0, "reference": 0}
    rows = (
        await session.execute(
            select(TestDefinition).where(TestDefinition.test_code.in_(list(MANUAL)))
        )
    ).scalars().all()
    for row in rows:
        if not row.procedure_en and row.test_code in PROCEDURES_EN:
            row.procedure_en = list(PROCEDURES_EN[row.test_code])
            filled["procedure_en"] += 1
        if not row.reference_jsonb and row.test_code in MANUAL:
            row.reference_jsonb = documentation_payload(row.test_code)
            filled["reference"] += 1
    await session.flush()
    return filled


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
        # The protocol exists: still heal the documentation columns, because a release
        # that adds a documented procedure must reach a database that is already seeded.
        return created | {"skipped": 1} | await sync_test_documentation(session)

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
            procedure_en=list(PROCEDURES_EN[spec.code]) if spec.code in PROCEDURES_EN else None,
            reference_jsonb=documentation_payload(spec.code) if spec.code in MANUAL else None,
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
    return created | await sync_test_documentation(session)

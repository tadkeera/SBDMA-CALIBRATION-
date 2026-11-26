"""Reference Manual — assembling the documented content for a test.

The manual is a *reading* of rows that already exist: the test definition (names, module,
standard, English procedure, reference block), its formulas and its acceptance limits.
Nothing here computes a result; the equations shown are the ones the scoring engine
actually evaluates, quoted from ``formula_definitions.expression_text`` so that the
manual can never describe a formula the system does not use.

Charts are derived from the ideal worked example stored in ``reference_jsonb``, not from
any run: the manual illustrates what a compliant measurement looks like, and it must be
reproducible on a bench that has no data yet.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.protocol import AcceptanceLimit, CalibrationProtocol, FormulaDefinition, TestDefinition

_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def _numbers(text: str) -> list[float]:
    return [float(m) for m in _NUMBER.findall(str(text))]


def _ideal_map(reference: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not reference:
        return {}
    return {row["field"]: row for row in reference.get("ideal_readings", []) if "field" in row}


def _chart_payload(
    chart_type: str,
    fields: list[dict[str, Any]],
    ideal: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """Turn the ideal readings into a plottable series.

    A single rule per chart family keeps the manual honest: the x axis is always the
    independent variable the analyst sets (volume, concentration, set temperature, flow),
    the y axis the response. Tests without a natural pair fall back to a bar chart of
    their first numeric reading, which is what the laboratory screen shows too.
    """
    if chart_type in (None, "", "none"):
        return None

    numeric_fields = [f for f in fields if f.get("type") in ("number", "series", "integer")]
    series_fields = [f for f in numeric_fields if f.get("type") in ("series", "spectrum")]

    def values(key: str) -> list[float]:
        row = ideal.get(key)
        return _numbers(row["value"]) if row else []

    def label(key: str) -> str:
        row = ideal.get(key)
        if row and row.get("field"):
            return f.get("label_en") if (f := next((x for x in fields if x["key"] == key), None)) else key
        field = next((x for x in fields if x["key"] == key), None)
        return (field or {}).get("label_en") or key

    def unit(key: str) -> str:
        field = next((x for x in fields if x["key"] == key), None)
        return (field or {}).get("unit") or ""

    pairs: list[dict[str, Any]] = []
    x_label = ""
    y_label = ""

    if chart_type == "linearity" and len(series_fields) >= 2:
        xs, ys = values(series_fields[0]["key"]), values(series_fields[1]["key"])
        pairs = [{"x": x, "y": y} for x, y in zip(xs, ys)]
        x_label, y_label = label(series_fields[0]["key"]), label(series_fields[1]["key"])
    elif chart_type == "temperature":
        sets = values("t_set")
        refs = values("t_ref_raw") or values("t_ref_raw")
        pairs = [{"x": x, "y": y} for x, y in zip(sets, refs)]
        x_label, y_label = "Set temperature (°C)", "Reference thermometer (°C)"
    elif chart_type == "flow":
        sets, vols = values("set_flow"), values("collected_vol")
        pairs = [{"x": x, "y": y} for x, y in zip(sets, vols)]
        x_label, y_label = "Set flow (mL/min)", "Collected volume (mL)"
    elif chart_type == "gradient":
        levels = [0.0, 10.0, 50.0, 90.0, 100.0]
        heights = [values(k) for k in ("height_0", "height_10", "height_50", "height_90", "height_100")]
        pairs = [
            {"x": level, "y": h[0] if h else 0.0} for level, h in zip(levels, heights)
        ]
        x_label, y_label = "Nominal trace-channel composition (%)", "Detector response (mAU)"

    if pairs:
        return {
            "kind": "line",
            "x_label": x_label,
            "y_label": y_label,
            "points": pairs,
        }

    # bars: one bar per numeric reading, labelled by its field
    bars = []
    for field in numeric_fields:
        vals = values(field["key"])
        if not vals:
            continue
        bars.append(
            {
                "label": field.get("label_en") or field["key"],
                "value": vals[0],
                "unit": field.get("unit") or "",
            }
        )
    if not bars:
        return None
    return {
        "kind": "bar",
        "x_label": "",
        "y_label": bars[0]["unit"] or "",
        "bars": bars[:10],
    }


def build_manual_entry(
    definition: TestDefinition,
    formulas: Iterable[FormulaDefinition],
    limits: Iterable[AcceptanceLimit],
) -> dict[str, Any]:
    reference = definition.reference_jsonb or {}
    fields = list((definition.input_schema_jsonb or {}).get("fields") or [])
    ideal = _ideal_map(reference)

    readings = []
    for field in fields:
        row = ideal.get(field["key"], {})
        readings.append(
            {
                "key": field["key"],
                "label_en": field.get("label_en") or field["key"],
                "label_ar": field.get("label_ar"),
                "type": field.get("type"),
                "length": field.get("length"),
                "unit": field.get("unit"),
                "required": bool(field.get("required")),
                "options": field.get("options") or [],
                "ideal_value": row.get("value"),
                "ideal_note": row.get("note_en"),
            }
        )

    limit_rows = [
        {
            "metric_key": limit.metric_key,
            "source_type": limit.source_type,
            "operator": limit.operator,
            "min_value": None if limit.min_value is None else str(limit.min_value),
            "max_value": None if limit.max_value is None else str(limit.max_value),
            "unit": limit.unit,
            "approval_status": limit.approval_status,
            "flagged": limit.flagged,
            "note_ar": limit.note_ar,
        }
        for limit in sorted(limits, key=lambda x: (x.metric_key, x.source_type))
    ]

    return {
        "code": definition.test_code,
        "sequence_order": definition.sequence_order,
        "name_en": definition.name_en,
        "name_ar": definition.name_ar,
        "module": definition.module,
        "standard_ref": definition.standard_ref,
        "is_active": definition.is_active,
        "is_mandatory": definition.is_mandatory,
        "overview_en": reference.get("overview_en"),
        "procedure_en": list(definition.procedure_en or []),
        "readings": readings,
        "equations": [
            {
                "key": f.formula_key,
                "expression": f.expression_text,
                "description_en": f.description_en,
                "decimals": f.rounding_decimals,
            }
            for f in sorted(formulas, key=lambda x: x.formula_key)
        ],
        "evaluation": reference.get("evaluation", []),
        "limits": limit_rows,
        "references": reference.get("references", []),
        "limit_notes": reference.get("limit_notes", []),
        "chart": _chart_payload(
            (definition.chart_config_jsonb or {}).get("type", "none"), fields, ideal
        ),
    }


async def load_manual(
    session: AsyncSession,
    *,
    protocol_code: str,
    test_codes: Iterable[str] | None = None,
    include_inactive: bool = True,
) -> tuple[CalibrationProtocol, list[dict[str, Any]]]:
    """Assemble manual entries for the current version of a protocol."""
    protocol = (
        await session.execute(
            select(CalibrationProtocol)
            .where(CalibrationProtocol.protocol_code == protocol_code)
            .order_by(CalibrationProtocol.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if protocol is None:
        return None, []  # type: ignore[return-value]

    statement = select(TestDefinition).where(TestDefinition.protocol_id == protocol.id)
    if test_codes:
        statement = statement.where(TestDefinition.test_code.in_(list(test_codes)))
    if not include_inactive:
        statement = statement.where(TestDefinition.is_active.is_(True))
    definitions = list(
        (await session.execute(statement.order_by(TestDefinition.sequence_order))).scalars().all()
    )
    if not definitions:
        return protocol, []

    ids = [d.id for d in definitions]
    formulas: dict[Any, list[FormulaDefinition]] = {}
    for row in (
        await session.execute(
            select(FormulaDefinition).where(
                FormulaDefinition.test_definition_id.in_(ids), FormulaDefinition.is_active.is_(True)
            )
        )
    ).scalars().all():
        formulas.setdefault(row.test_definition_id, []).append(row)

    limits: dict[Any, list[AcceptanceLimit]] = {}
    for row in (
        await session.execute(select(AcceptanceLimit).where(AcceptanceLimit.test_definition_id.in_(ids)))
    ).scalars().all():
        limits.setdefault(row.test_definition_id, []).append(row)

    entries = [
        build_manual_entry(d, formulas.get(d.id, []), limits.get(d.id, [])) for d in definitions
    ]
    return protocol, entries

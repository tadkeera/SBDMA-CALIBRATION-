"""Calibration engine — formula execution plus the QA governance gate.

Two hard rules from the master specification:
  1. Every formula runs through the safe AST engine (never eval).
  2. A metric can never be judged PASS while its governing limit is UNAPPROVED
     or CONFLICT_REQUIRES_QA — the run escalates to UNDER_REVIEW instead.

This module is pure: it performs no I/O and is fully unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal

from app.domain.math_engine.ast_engine import UnsafeExpression, evaluate
from app.domain.protocol.blueprint import LimitSpec, TestSpec

Status = Literal["PASS", "FAIL", "UNDER_REVIEW", "INCOMPLETE"]

PASS: Status = "PASS"
FAIL: Status = "FAIL"
UNDER_REVIEW: Status = "UNDER_REVIEW"
INCOMPLETE: Status = "INCOMPLETE"

_SEVERITY: dict[Status, int] = {PASS: 0, INCOMPLETE: 1, UNDER_REVIEW: 2, FAIL: 3}


def worst(statuses: list[Status]) -> Status:
    if not statuses:
        return PASS
    return max(statuses, key=lambda s: _SEVERITY[s])


@dataclass(slots=True)
class MetricEvaluation:
    metric_key: str
    value: Decimal | None
    unit: str
    applied_limit_id: str | None
    applied_source: str | None
    comparator: str
    limit_text: str
    status: Status
    message_ar: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "metric_key": self.metric_key,
            "value": None if self.value is None else str(self.value),
            "unit": self.unit,
            "applied_limit_id": self.applied_limit_id,
            "applied_source": self.applied_source,
            "comparator": self.comparator,
            "limit_text": self.limit_text,
            "status": self.status,
            "message_ar": self.message_ar,
        }


@dataclass(slots=True)
class TestOutcome:
    test_code: str
    outputs: dict[str, Any]
    metric_evaluations: list[MetricEvaluation]
    status: Status
    notes_ar: str | None = None
    formula_errors: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RunOutcome:
    results: list[TestOutcome]
    overall: Status

    @property
    def by_code(self) -> dict[str, TestOutcome]:
        return {r.test_code: r for r in self.results}

    def summary(self) -> dict[str, int]:
        return {
            "pass": sum(1 for r in self.results if r.status == PASS),
            "fail": sum(1 for r in self.results if r.status == FAIL),
            "review": sum(1 for r in self.results if r.status == UNDER_REVIEW),
            "incomplete": sum(1 for r in self.results if r.status == INCOMPLETE),
        }


# ─────────────────────────────── limit helpers ────────────────────────────── #


def find_limit(
    limits: list[LimitSpec], test_code: str, metric_key: str, source: str
) -> LimitSpec | None:
    for lim in limits:
        if (
            lim.test_code == test_code
            and lim.metric_key == metric_key
            and lim.source_type == source
        ):
            return lim
    return None


def format_limit(limit: LimitSpec | None) -> str:
    if limit is None:
        return "—"
    value = limit.min_value if limit.operator == "gte" else limit.max_value
    rendered = "—" if value is None else _trim(value)
    match limit.operator:
        case "lte":
            return f"≤ {rendered} {limit.unit}"
        case "gte":
            return f"≥ {rendered} {limit.unit}"
        case "abs_lte":
            return f"|x| ≤ {rendered} {limit.unit}"
        case "between":
            return f"{_trim(limit.min_value)} … {_trim(limit.max_value)} {limit.unit}"
        case "equals":
            return f"= {rendered} {limit.unit}"
    return "—"


def _trim(value: Decimal | None) -> str:
    if value is None:
        return "—"
    normalized = value.normalize()
    text = format(normalized, "f")
    return text


def _compare(value: Decimal, limit: LimitSpec) -> bool:
    match limit.operator:
        case "lte":
            return limit.max_value is not None and value <= limit.max_value
        case "gte":
            return limit.min_value is not None and value >= limit.min_value
        case "abs_lte":
            return limit.max_value is not None and abs(value) <= limit.max_value
        case "between":
            return (
                limit.min_value is not None
                and limit.max_value is not None
                and limit.min_value <= value <= limit.max_value
            )
        case "equals":
            return limit.min_value is not None and value == limit.min_value
    return False


def evaluate_metric(
    *,
    test_code: str,
    metric_key: str,
    value: Decimal | None,
    source: str,
    unit: str,
    limits: list[LimitSpec],
    limit_id_lookup: dict[tuple[str, str, str], str] | None = None,
) -> MetricEvaluation:
    """The single choke point that decides a metric verdict."""
    limit = find_limit(limits, test_code, metric_key, source)
    applied_id = None
    if limit and limit_id_lookup:
        applied_id = limit_id_lookup.get((test_code, metric_key, source))

    base = dict(
        metric_key=metric_key,
        value=value,
        unit=limit.unit if limit else unit,
        applied_limit_id=applied_id,
        applied_source=source,
        comparator=limit.operator if limit else "—",
        limit_text=format_limit(limit),
    )

    if limit is None:
        return MetricEvaluation(
            **base,
            status=UNDER_REVIEW,
            message_ar="لا يوجد حد قبول مسجل لهذا المقياس من المصدر المختار — يلزم اعتماد QA.",
        )
    if value is None:
        return MetricEvaluation(**base, status=INCOMPLETE, message_ar="قيمة غير محسوبة أو غير صالحة.")
    if limit.approval_status == "REJECTED":
        return MetricEvaluation(
            **base, status=UNDER_REVIEW, message_ar="الحد مرفوض من ضمان الجودة ولا يجوز استخدامه."
        )
    if limit.approval_status in ("UNAPPROVED", "CONFLICT_REQUIRES_QA"):
        msg = (
            "الحد متعارض أو موثّق الخطأ ويلزم حسم ضمان الجودة قبل إصدار الحكم."
            if limit.approval_status == "CONFLICT_REQUIRES_QA"
            else "الحد غير معتمد من ضمان الجودة."
        )
        return MetricEvaluation(**base, status=UNDER_REVIEW, message_ar=msg)

    ok = _compare(value, limit)
    return MetricEvaluation(
        **base,
        status=PASS if ok else FAIL,
        message_ar=None if ok else "القيمة خارج حد القبول المعتمد — انحراف OOS.",
    )


# ───────────────────────────────── execution ──────────────────────────────── #


def _coerce_inputs(test: TestSpec, raw: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    scope: dict[str, Any] = {}
    complete = True
    for fspec in test.fields:
        value = raw.get(fspec.key)
        if value in (None, "", []):
            if fspec.required:
                complete = False
            # formulas still need a numeric zero for optional fields
            if fspec.type in ("number", "integer"):
                scope[fspec.key] = Decimal("0")
            elif fspec.type in ("series", "spectrum"):
                scope[fspec.key] = []
            continue
        if fspec.type in ("series", "spectrum"):
            if isinstance(value, str):
                parts = [p for p in value.replace(";", ",").split(",") if p.strip()]
            else:
                parts = list(value)
            nums = [Decimal(str(p)) for p in parts if str(p).strip() != ""]
            if fspec.required and fspec.length and len(nums) < fspec.length:
                complete = False
            scope[fspec.key] = nums
        elif fspec.type == "select":
            scope[fspec.key] = value
        elif fspec.type == "boolean":
            scope[fspec.key] = Decimal(1 if value else 0)
        else:
            scope[fspec.key] = Decimal(str(value))
    return scope, complete


#: Select values that count as a failure. The protocol uses ``PASS``/``FAIL``; the
#: earlier revision used ``Passed``/``Failed``. Both are accepted, in any case, so a
#: reading stored by either version is read the same way instead of silently passing
#: a failed sensor.
_FAIL_VALUES = frozenset({"fail", "failed", "reject", "rejected"})


def _is_failed(value: object) -> bool:
    return isinstance(value, str) and value.strip().lower() in _FAIL_VALUES


def _select_gate(test: TestSpec, raw: dict[str, Any]) -> list[str]:
    """Select-type fields that gate the verdict (e.g. leak sensors, limiters)."""
    return [
        fspec.label_ar
        for fspec in test.fields
        if fspec.type == "select" and _is_failed(raw.get(fspec.key))
    ]


def execute_test(
    test: TestSpec,
    raw_inputs: dict[str, Any],
    *,
    limits: list[LimitSpec],
    policy_source: str,
    limit_id_lookup: dict[tuple[str, str, str], str] | None = None,
) -> TestOutcome:
    scope, complete = _coerce_inputs(test, raw_inputs)

    if not complete:
        evaluations = [
            evaluate_metric(
                test_code=test.code,
                metric_key=m,
                value=None,
                source=policy_source,
                unit="",
                limits=limits,
                limit_id_lookup=limit_id_lookup,
            )
            for m in test.metrics
        ]
        return TestOutcome(
            test_code=test.code,
            outputs={},
            metric_evaluations=evaluations,
            status=INCOMPLETE,
        )

    outputs: dict[str, Any] = {}
    formula_errors: list[str] = []
    for formula in test.formulas:
        try:
            result = evaluate(formula.expression, scope)
            outputs[formula.key] = result
            scope[formula.key] = result
        except UnsafeExpression as exc:
            formula_errors.append(f"{formula.key}: {exc}")
            outputs[formula.key] = None

    evaluations: list[MetricEvaluation] = []
    for metric in test.metrics:
        value = outputs.get(metric)
        numeric = value if isinstance(value, Decimal) else None
        unit = next((f.unit for f in test.fields if f.key == metric), None) or ""
        evaluations.append(
            evaluate_metric(
                test_code=test.code,
                metric_key=metric,
                value=numeric,
                source=policy_source,
                unit=unit,
                limits=limits,
                limit_id_lookup=limit_id_lookup,
            )
        )

    failures = _select_gate(test, raw_inputs)
    if failures:
        status: Status = FAIL
        notes = f"عناصر غير مطابقة: {'، '.join(failures)}"
    else:
        status = worst([e.status for e in evaluations])
        notes = None

    return TestOutcome(
        test_code=test.code,
        outputs=outputs,
        metric_evaluations=evaluations,
        status=status,
        notes_ar=notes,
        formula_errors=formula_errors,
    )


def execute_run(
    *,
    tests: list[TestSpec],
    raw_inputs: dict[str, dict[str, Any]],
    limits: list[LimitSpec],
    policy_source: str,
    limit_id_lookup: dict[tuple[str, str, str], str] | None = None,
) -> RunOutcome:
    results = [
        execute_test(
            test,
            raw_inputs.get(test.code, {}),
            limits=limits,
            policy_source=policy_source,
            limit_id_lookup=limit_id_lookup,
        )
        for test in tests
    ]
    return RunOutcome(results=results, overall=worst([r.status for r in results]))


def serialise_outputs(outputs: dict[str, Any]) -> dict[str, Any]:
    """Decimal is rendered as a string so JSON never loses precision."""
    def convert(value: Any) -> Any:
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, list):
            return [convert(v) for v in value]
        return value

    return {k: convert(v) for k, v in outputs.items()}

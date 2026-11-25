#!/usr/bin/env python3
"""Generate ``src/core/protocol.ts`` from the authoritative Python blueprint.

Why a generator instead of a hand-kept twin: the two engines must score identical
readings identically, and hand-transcribing 20 tests, 93 limits and 75 formulas
invites exactly the defect the parity tests exist to catch. The blueprint is the
single source of truth (it is what the seeder writes to PostgreSQL), so the
TypeScript table is *derived* from it here and the derivation is verified in CI
(``backend/tests/test_protocol_parity.py`` regenerates and compares).

Usage:
    python scripts/export_protocol_ts.py            # write src/core/protocol.ts
    python scripts/export_protocol_ts.py --check    # fail if the file is stale
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND = REPO_ROOT / "backend"
OUTPUT = REPO_ROOT / "src" / "core" / "protocol.ts"

sys.path.insert(0, str(BACKEND))

from app.domain.protocol.blueprint import (  # noqa: E402
    BREAKDOWN_MATRIX,
    LIMITS,
    PROTOCOL_CODE,
    PROTOCOL_TITLE_AR,
    PROTOCOL_TITLE_EN,
    PROTOCOL_VERSION,
    TESTS,
)

HEADER = '''import type {{ AcceptanceLimit, LimitSource, TestSpec }} from './types';

/**
 * {code} v{version}
 * {title_en}
 * {title_ar}
 *
 * GENERATED FILE — do not edit by hand.
 * Produced by `python scripts/export_protocol_ts.py` from
 * `backend/app/domain/protocol/blueprint.py`, the same blueprint the seeder writes
 * to PostgreSQL. `test_protocol_parity.py` regenerates this file and compares, so a
 * hand edit or a stale copy fails the build instead of shipping two disagreeing
 * engines.
 *
 * {n_tests} tests · {n_limits} acceptance limits · {n_formulas} formulas.
 * Limits the source material classifies as conflicting are seeded as
 * CONFLICT_REQUIRES_QA so the engine can never issue a silent PASS on them.
 */

export const PROTOCOL_CODE = {code};
export const PROTOCOL_VERSION = {version};
export const PROTOCOL_TITLE_AR = {title_ar};
export const PROTOCOL_TITLE_EN = {title_en};

let seq = 0;
function L(
  testCode: string,
  metricKey: string,
  sourceType: LimitSource,
  operator: AcceptanceLimit['operator'],
  minValue: number | null,
  maxValue: number | null,
  unit: string,
  approvalStatus: AcceptanceLimit['approvalStatus'],
  note?: string,
  flagged?: boolean,
): AcceptanceLimit {{
  seq += 1;
  return {{
    id: `lim-${{String(seq).padStart(4, '0')}}`,
    testCode,
    metricKey,
    sourceType,
    operator,
    minValue,
    maxValue,
    unit,
    approvalStatus,
    approvedBy: approvalStatus === 'APPROVED' ? 'QA-APPROVER (seeded)' : null,
    approvedAt: approvalStatus === 'APPROVED' ? '2026-01-15T08:00:00.000Z' : null,
    note,
    flagged,
  }};
}}

const A = 'APPROVED' as const;
const C = 'CONFLICT_REQUIRES_QA' as const;
'''


def _q(value: str) -> str:
    """Single-quoted TypeScript string (the parity test matches on this form)."""
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _num(value) -> str:
    if value is None:
        return "null"
    text = str(value)
    if text.endswith(".0"):
        text = text[:-2]
    return text


def _field_ts(field) -> str:
    parts = [
        f"key: {_q(field.key)}",
        f"labelAr: {_q(field.label_ar)}",
        f"labelEn: {_q(field.label_en)}",
        f"type: {_q(field.type)}",
    ]
    if field.unit:
        parts.append(f"unit: {_q(field.unit)}")
    if field.length:
        parts.append(f"length: {field.length}")
    if field.options:
        parts.append("options: [" + ", ".join(_q(option) for option in field.options) + "]")
    if not field.required:
        parts.append("required: false")
    if field.hint_ar:
        parts.append(f"hintAr: {_q(field.hint_ar)}")
    return "{ " + ", ".join(parts) + " }"


def _formula_ts(formula) -> str:
    return (
        "{ "
        f"key: {_q(formula.key)}, "
        f"expression: {_q(formula.expression)}, "
        f"descriptionAr: {_q(formula.description_ar)}, "
        f"descriptionEn: {_q(formula.description_en)}, "
        f"decimals: {formula.decimals}"
        " }"
    )


def _test_ts(test) -> str:
    procedures = "\n".join(f"      {_q(line)}," for line in test.procedure_ar)
    fields = "\n".join(f"      {_field_ts(field)}," for field in test.fields)
    formulas = "\n".join(f"      {_formula_ts(formula)}," for formula in test.formulas)
    metrics = ", ".join(_q(metric) for metric in test.metrics)
    return f"""  {{
    code: {_q(test.code)},
    sequence: {test.sequence},
    nameAr: {_q(test.name_ar)},
    nameEn: {_q(test.name_en)},
    module: {_q(test.module)},
    standard: {_q(test.standard)},
    procedureAr: [
{procedures}
    ],
    fields: [
{fields}
    ],
    formulas: [
{formulas}
    ],
    metrics: [{metrics}],
    chart: {_q(test.chart)},
    mandatory: {'true' if test.mandatory else 'false'},
  }},"""


def _limit_ts(limit) -> str:
    status = "C" if limit.approval_status == "CONFLICT_REQUIRES_QA" else "A"
    args = [
        _q(limit.test_code),
        _q(limit.metric_key),
        _q(limit.source_type),
        _q(limit.operator),
        _num(limit.min_value),
        _num(limit.max_value),
        _q(limit.unit),
        status,
    ]
    if limit.note_ar:
        args.append(_q(limit.note_ar))
    if limit.flagged:
        if not limit.note_ar:
            args.append("undefined")
        args.append("true")
    return "  L(" + ", ".join(args) + "),"


def render() -> str:
    n_formulas = sum(len(test.formulas) for test in TESTS)
    chunks = [
        HEADER.format(
            code=_q(PROTOCOL_CODE),
            version=_q(PROTOCOL_VERSION),
            title_ar=_q(PROTOCOL_TITLE_AR),
            title_en=_q(PROTOCOL_TITLE_EN),
            n_tests=len(TESTS),
            n_limits=len(LIMITS),
            n_formulas=n_formulas,
        ),
        "export const TESTS: TestSpec[] = [",
        "\n".join(_test_ts(test) for test in TESTS),
        "];",
        "",
        f"/** {len(LIMITS)} acceptance limits, one row per (test, metric, source). */",
        "export const LIMITS: AcceptanceLimit[] = [",
        "\n".join(_limit_ts(limit) for limit in LIMITS),
        "];",
        "",
        "/** Post-breakdown mandatory re-test matrix. */",
        "export const BREAKDOWN_MATRIX: { key: string; ar: string; en: string; tests: string[] }[] = [",
        "\n".join(
            "  {\n"
            f"    key: {_q(row['key'])},\n"
            f"    ar: {_q(row['ar'])},\n"
            f"    en: {_q(row['en'])},\n"
            "    tests: [" + ", ".join(_q(code) for code in row["tests"]) + "],\n"
            "  },"
            for row in BREAKDOWN_MATRIX
        ),
        "];",
        "",
        "export function testsForComponent(key: string): string[] {",
        "  return BREAKDOWN_MATRIX.find((b) => b.key === key)?.tests ?? [];",
        "}",
        "",
    ]
    return "\n".join(chunks)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit 1 if the file is stale")
    args = parser.parse_args()

    rendered = render()
    if args.check:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if current != rendered:
            print(f"{OUTPUT} is stale — run python scripts/export_protocol_ts.py", file=sys.stderr)
            return 1
        print(f"{OUTPUT} is up to date ({len(TESTS)} tests, {len(LIMITS)} limits)")
        return 0

    OUTPUT.write_text(rendered, encoding="utf-8")
    print(
        f"wrote {OUTPUT.relative_to(REPO_ROOT)}: "
        f"{len(TESTS)} tests, {len(LIMITS)} limits, "
        f"{sum(len(t.formulas) for t in TESTS)} formulas"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

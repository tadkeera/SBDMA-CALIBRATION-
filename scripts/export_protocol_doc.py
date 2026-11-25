#!/usr/bin/env python
"""Render `docs/protocol.md` from the protocol blueprint.

The document and the table the engines execute must be the same artefact. Written
by hand, the document drifts the first time a limit changes — and a laboratory
reading a stale acceptance limit is worse than a laboratory reading none, because
it believes it is compliant.

    python scripts/export_protocol_doc.py            # write docs/protocol.md
    python scripts/export_protocol_doc.py --check     # fail if it is out of date
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.domain.protocol import blueprint as bp  # noqa: E402

TARGET = ROOT / "docs" / "protocol.md"

SOURCE_LABEL = {
    "INTEGRITY_GUIDE_CH2": "دليل سلامة الأجهزة — الفصل 2",
    "IOQ_PROTOCOL_CH4": "بروتوكول iOQ — الفصل 4",
    "MANUFACTURER_SPEC": "مواصفات المصنع",
    "SOP_LIMIT": "إجراء تشغيلي (SOP)",
    "AUTHORITY_LIMIT": "الحد المعتمد (Authority)",
}

OPERATOR_AR = {
    "lte": "≤",
    "lt": "<",
    "gte": "≥",
    "gt": ">",
    "eq": "=",
    "between": "بين",
}


def _num(value: object) -> str:
    from decimal import Decimal

    if value is None:
        return "—"
    if isinstance(value, Decimal):
        text = format(value.normalize(), "f")
        return text
    return str(value)


def _limit_text(limit) -> str:
    op = OPERATOR_AR.get(limit.operator, limit.operator)
    if limit.operator == "between":
        text = f"{_num(limit.min_value)} … {_num(limit.max_value)}"
    elif limit.operator in ("lte", "lt"):
        text = f"{op} {_num(limit.max_value)}"
    elif limit.operator in ("gte", "gt"):
        text = f"{op} {_num(limit.min_value)}"
    else:
        text = f"{op} {_num(limit.min_value)}"
    return f"{text} {limit.unit}" if limit.unit else text


def render() -> str:
    lines: list[str] = []
    add = lines.append

    limits_by_test: dict[str, list] = {}
    for limit in bp.LIMITS:
        limits_by_test.setdefault(limit.test_code, []).append(limit)

    conflicts = [lim for lim in bp.LIMITS if lim.approval_status == bp.C]
    formula_total = sum(len(test.formulas) for test in bp.TESTS)
    field_total = sum(len(test.fields) for test in bp.TESTS)

    add(f"# البروتوكول المعتمد — {bp.PROTOCOL_CODE} v{bp.PROTOCOL_VERSION}")
    add("")
    add(f"**{bp.PROTOCOL_TITLE_AR}**  ")
    add(f"*{bp.PROTOCOL_TITLE_EN}*")
    add("")
    add(
        f"الجهاز: Shimadzu i-Series LC-2050C (UV Detector + Sample Cooler) · رقم القطعة "
        f"`S228-65821-58` · الدورية: كل 180 يوماً أو بعد أي صيانة كبرى."
    )
    add("")
    add(
        f"**{len(bp.TESTS)} اختباراً · {len(bp.LIMITS)} حد قبول · {field_total} حقلاً · "
        f"{formula_total} معادلة · {len(bp.BREAKDOWN_MATRIX)} صفاً في مصفوفة إعادة الاختبار.**"
    )
    add("")
    add(
        "> هذا الملف **مُولَّد آلياً** من "
        "`backend/app/domain/protocol/blueprint.py` بواسطة "
        "`scripts/export_protocol_doc.py`. لا يُحرَّر بيداً: أي تعديل يدوي يُفشل "
        "`--check` في الاختبارات، لأن وثيقة تحدِّث حدوداً لا يطبّقها المحرك هي أسوأ من "
        "وثيقة قديمة."
    )
    add("")
    add("---")
    add("")

    # ── index ────────────────────────────────────────────────────────────────
    add("## الفهرس")
    add("")
    add("| # | الاختبار | الوحدة | المعايير | حقول | معادلات | مقاييس | حدود |")
    add("|---|---|---|---|---|---|---|---|")
    for test in bp.TESTS:
        add(
            f"| {test.code} | {test.name_ar} | `{test.module}` | {test.standard} | "
            f"{len(test.fields)} | {len(test.formulas)} | {len(test.metrics)} | "
            f"{len(limits_by_test.get(test.code, []))} |"
        )
    add("")
    add("---")
    add("")

    # ── per test ─────────────────────────────────────────────────────────────
    for test in bp.TESTS:
        add(f"## {test.code} — {test.name_ar}")
        add(f"*{test.name_en}*")
        add("")
        add(f"**الوحدة:** `{test.module}` · **المعايير:** {test.standard}")
        if not test.mandatory:
            add("")
            add("**اختياري** لهذا النوع من التشغيلات.")
        if test.procedure_ar:
            add("")
            steps = (
                list(test.procedure_ar)
                if isinstance(test.procedure_ar, (list, tuple))
                else [test.procedure_ar]
            )
            if len(steps) == 1:
                add(f"**الإجراء:** {steps[0]}")
            else:
                add("**الإجراء:**")
                add("")
                for index, step in enumerate(steps, start=1):
                    add(f"{index}. {step}")
        add("")

        if test.fields:
            add("**الحقول المدخلة:**")
            add("")
            add("| المفتاح | الوصف | النوع | الوحدة | الطول | إلزامي |")
            add("|---|---|---|---|---|---|")
            for field in test.fields:
                length = field.length if field.length is not None else "—"
                add(
                    f"| `{field.key}` | {field.label_ar} | `{field.type}` | "
                    f"{field.unit or '—'} | {length} | {'نعم' if field.required else 'لا'} |"
                )
            add("")

        if test.formulas:
            add("**المعادلات المنفَّذة (AST مُتحقق منه، بلا `eval`):**")
            add("")
            add("| المفتاح | التعبير | الوصف |")
            add("|---|---|---|")
            for formula in test.formulas:
                add(f"| `{formula.key}` | `{formula.expression}` | {formula.description_ar} |")
            add("")

        if test.metrics:
            add("**المقاييس وحدودها:**")
            add("")
            add("| المقياس | الحد المعتمد | المصادر الأخرى | الحالة |")
            add("|---|---|---|---|")
            for metric in test.metrics:
                rows = [lim for lim in limits_by_test.get(test.code, []) if lim.metric_key == metric]
                authority = next(
                    (lim for lim in rows if lim.source_type == "AUTHORITY_LIMIT"), None
                )
                others = [
                    f"{SOURCE_LABEL.get(lim.source_type, lim.source_type)}: {_limit_text(lim)}"
                    for lim in rows
                    if lim.source_type != "AUTHORITY_LIMIT"
                ]
                state = "معتمد"
                if authority is not None and authority.approval_status == bp.C:
                    state = "**متعارض — يتطلب اعتماد الجودة**"
                elif authority is None:
                    state = "بلا حد معتمد"
                add(
                    f"| `{metric}` | {_limit_text(authority) if authority else '—'} | "
                    f"{' · '.join(others) if others else '—'} | {state} |"
                )
            add("")
        add("---")
        add("")

    # ── breakdown matrix ─────────────────────────────────────────────────────
    add("## مصفوفة إعادة الاختبار بعد الأعطال")
    add("")
    add("| المكوّن | الاختبارات المطلوبة |")
    add("|---|---|")
    for row in bp.BREAKDOWN_MATRIX:
        add(f"| {row['ar']} (`{row['key']}`) | {', '.join(row['tests'])} |")
    add("")
    add(
        "أي تشغيل من نوع `POST_BREAKDOWN` يقتصر على الاختبارات المذكورة للمكوّن المعطوب، "
        "مع `T01` (التحقق التلقائي) دائماً."
    )
    add("")

    # ── governance note ──────────────────────────────────────────────────────
    add("## حوكمة الحدود")
    add("")
    add(
        "كل حد يحمل مصدره وحالة اعتماده. الحد المعتمد (`AUTHORITY_LIMIT`) هو الوحيد الذي "
        "يُنتج `PASS`؛ وحدود المصادر الأخرى تُحفظ للمقارنة والتوثيق."
    )
    add("")
    if conflicts:
        add("**الحدود المتعارضة في هذا الإصدار:**")
        add("")
        for limit in conflicts:
            add(
                f"- `{limit.test_code}:{limit.metric_key}` من "
                f"{SOURCE_LABEL.get(limit.source_type, limit.source_type)} "
                f"({_limit_text(limit)}) أوسع من الحد المعتمد — أي قيمة بين الحدين تُحوَّل "
                f"إلى `UNDER_REVIEW` ولا تُقبل تلقائياً."
            )
        add("")
    else:
        add("لا توجد حدود متعارضة في هذا الإصدار.")
        add("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Render docs/protocol.md from the blueprint")
    parser.add_argument("--check", action="store_true", help="fail if the file is stale")
    args = parser.parse_args()

    rendered = render()
    if args.check:
        if not TARGET.is_file():
            print(f"missing {TARGET.relative_to(ROOT)}", file=sys.stderr)
            return 1
        if TARGET.read_text(encoding="utf-8") != rendered:
            print(
                f"{TARGET.relative_to(ROOT)} is stale — run scripts/export_protocol_doc.py",
                file=sys.stderr,
            )
            return 1
        print(f"{TARGET.relative_to(ROOT)} is up to date")
        return 0

    TARGET.write_text(rendered, encoding="utf-8")
    print(
        f"wrote {TARGET.relative_to(ROOT)}: {len(bp.TESTS)} tests, "
        f"{len(bp.LIMITS)} limits, {sum(len(t.formulas) for t in bp.TESTS)} formulas"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

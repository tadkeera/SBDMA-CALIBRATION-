"""Print-quality Reference Manual: one test, or all twenty, as a PDF.

Layout is deliberately conservative — A4 portrait, 14 mm margins, the same official
letterhead and the same typographic scale as the certificates — because the manual is
bound, printed and read alongside them. Each test gets:

  1. a title band with the test code, name, module and the standard it implements;
  2. ``Overview & importance``;
  3. ``Required readings`` — the input fields with the ideal worked example;
  4. ``Mathematical equations`` — the expressions the scoring engine evaluates;
  5. ``Evaluation criteria`` and ``Acceptance limits`` — every source, the adopted one
     highlighted, conflicts visible;
  6. ``Calibration curve`` — drawn from the ideal example, vector, not a screenshot;
  7. ``Scientific references``.

Every page carries the test code of the section it belongs to, so a loose page from a
printed manual can be identified on its own.
"""

from __future__ import annotations

import io
from typing import Any

from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.services.report_service import (
    BRAND,
    FONT_BODY,
    _letterhead,
    _styles,
)

LINE = colors.HexColor("#dfe5ea")
MUTED = colors.HexColor("#5b6773")
SOFT = colors.HexColor("#f2f5f8")
PASS = colors.HexColor("#16794f")
WARN = colors.HexColor("#9a6a12")


def _styles_extra() -> dict[str, ParagraphStyle]:
    st = _styles()
    st["body"] = ParagraphStyle("body", parent=st["cell"], fontSize=8.4, leading=11.6)
    st["mono"] = ParagraphStyle(
        "mono", parent=st["cell"], fontName=FONT_BODY, fontSize=7.8, leading=10.4,
        textColor=colors.HexColor("#16202b"),
    )
    st["title2"] = ParagraphStyle(
        "title2", parent=st["title"], fontSize=13, leading=16, alignment=TA_CENTER
    )
    st["section"] = ParagraphStyle(
        "section", parent=st["h2"], fontSize=9.4, leading=12, spaceBefore=5, spaceAfter=2.5
    )
    return st


def _chart_drawing(chart: dict[str, Any], width: float = 168 * mm, height: float = 48 * mm) -> Drawing | None:
    """A vector chart: a line for x/y families, bars for single-value tests."""
    if not chart:
        return None
    drawing = Drawing(width, height)
    if chart.get("kind") == "line" and chart.get("points"):
        plot = LinePlot()
        plot.x = 42
        plot.y = 24
        plot.width = width - 60
        plot.height = height - 40
        plot.data = [[(p["x"], p["y"]) for p in chart["points"]]]
        plot.lines[0].strokeColor = BRAND
        plot.lines[0].strokeWidth = 1.1
        try:  # markers are cosmetic; a version without them must not fail the manual
            plot.lines[0].symbol = _marker()
        except Exception:  # noqa: BLE001
            pass
        plot.xValueAxis.valueMin = min(p["x"] for p in chart["points"])
        plot.xValueAxis.valueMax = max(p["x"] for p in chart["points"]) or 1
        plot.yValueAxis.valueMin = None
        plot.yValueAxis.labels.fontName = FONT_BODY
        plot.yValueAxis.labels.fontSize = 6.5
        plot.xValueAxis.labels.fontName = FONT_BODY
        plot.xValueAxis.labels.fontSize = 6.5
        plot.xValueAxis.labelTextFormat = "%g"
        plot.yValueAxis.labelTextFormat = "%g"
        drawing.add(plot)
    elif chart.get("kind") == "bar" and chart.get("bars"):
        bars = chart["bars"]
        plot = VerticalBarChart()
        plot.x = 42
        plot.y = 26
        plot.width = width - 60
        plot.height = height - 44
        plot.data = [[bar["value"] for bar in bars]]
        plot.categoryAxis.categoryNames = [bar["label"] for bar in bars]
        plot.categoryAxis.labels.fontName = FONT_BODY
        plot.categoryAxis.labels.fontSize = 5.4
        plot.categoryAxis.labels.angle = 20
        plot.valueAxis.labels.fontName = FONT_BODY
        plot.valueAxis.labels.fontSize = 6.5
        plot.bars[0].fillColor = BRAND
        plot.valueAxis.valueMin = 0
        drawing.add(plot)
    else:  # pragma: no cover - defensive
        return None
    return drawing


def _marker():  # noqa: ANN202
    from reportlab.graphics.widgets.markers import makeMarker

    return makeMarker("FilledCircle", size=3)


def _table(
    st: dict[str, ParagraphStyle],
    header: list[str],
    rows: list[list[str]],
    widths: list[float] | None = None,
    *,
    highlight: dict[int, colors.Color] | None = None,
) -> Table:
    data = [[Paragraph(f"<b>{h}</b>", st["cellb"]) for h in header]]
    style = [
        ("GRID", (0, 0), (-1, -1), 0.4, LINE),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef1f5")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2),
    ]
    for index, row in enumerate(rows, start=1):
        data.append(
            [
                cell if isinstance(cell, Paragraph) else Paragraph("" if cell is None else str(cell), st["cell"])
                for cell in row
            ]
        )
        if index % 2 == 0:
            style.append(("BACKGROUND", (0, index), (-1, index), colors.HexColor("#fafbfc")))
        if highlight and (index - 1) in highlight:
            style.append(("TEXTCOLOR", (0, index), (-1, index), highlight[index - 1]))
    table = Table(data, colWidths=widths, repeatRows=1)
    table.setStyle(TableStyle(style))
    return table


def _num(value: Any) -> str:
    """A limit value printed as a laboratory would write it: 2 °C, not 2.00000000 °C."""
    if value is None:
        return ""
    try:
        number = float(str(value))
    except (TypeError, ValueError):
        return str(value)
    text = f"{number:.10f}".rstrip("0").rstrip(".")
    return text or "0"


def _limit_text(limit: dict[str, Any]) -> str:
    unit = limit.get("unit") or ""
    limit = {**limit, "min_value": _num(limit.get("min_value")), "max_value": _num(limit.get("max_value"))}
    if limit["operator"] == "between":
        return f"{limit['min_value']} – {limit['max_value']} {unit}".strip()
    if limit["operator"] == "lte":
        return f"≤ {limit['max_value']} {unit}".strip()
    if limit["operator"] == "gte":
        return f"≥ {limit['min_value']} {unit}".strip()
    return f"= {limit['min_value']} {unit}".strip()


def _test_story(st: dict[str, ParagraphStyle], entry: dict[str, Any]) -> list[Any]:
    story: list[Any] = []

    title = Table(
        [
            [
                Paragraph(
                    f'<font color="white" size=13><b>{entry["code"]}</b></font>',
                    ParagraphStyle("c", parent=st["cellb"], alignment=TA_CENTER, fontSize=14),
                ),
                Paragraph(
                    f'<font color="white" size=10><b>{entry["name_en"]}</b></font><br/>'
                    f'<font color="white" size=7.6>{entry["module"]} · sequence {entry["sequence_order"]}</font>',
                    ParagraphStyle("n", parent=st["cellb"], textColor=colors.white),
                ),
            ]
        ],
        colWidths=[22 * mm, None],
    )
    title.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, 0), BRAND),
                ("BACKGROUND", (1, 0), (1, 0), colors.HexColor("#1d2a36")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (1, 0), (1, 0), 5),
            ]
        )
    )
    story.append(KeepTogether([title, Spacer(1, 2 * mm)]))
    story.append(
        Paragraph(
            f"<b>Standard implemented:</b> {entry['standard_ref']}"
            + ("" if entry.get("is_active", True) else "  ·  <b>STATUS: DISABLED</b>"),
            st["note"],
        )
    )

    # 1 — overview
    if entry.get("overview_en"):
        story.append(Paragraph("1 · Overview and importance", st["section"]))
        story.append(Paragraph(entry["overview_en"], st["body"]))

    # 2 — documented procedure
    if entry.get("procedure_en"):
        story.append(Paragraph("2 · Documented procedure", st["section"]))
        steps = [
            [f"{i}", Paragraph(step, st["cell"])] for i, step in enumerate(entry["procedure_en"], start=1)
        ]
        table = Table(steps, colWidths=[8 * mm, None])
        table.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.4, LINE),
                    ("BACKGROUND", (0, 0), (0, -1), SOFT),
                    ("ALIGN", (0, 0), (0, -1), "CENTER"),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 2.2),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2),
                ]
            )
        )
        story.append(table)

    # 3 — required readings
    story.append(Paragraph("3 · Required readings and ideal values", st["section"]))
    rows = []
    for row in entry["readings"]:
        kind = row["type"] or ""
        if row["type"] == "series" and row.get("length"):
            kind = f"series × {row['length']}"
        rows.append(
            [
                row["label_en"],
                kind,
                row["unit"] or "—",
                "yes" if row["required"] else "no",
                row.get("ideal_value") or "—",
                row.get("ideal_note") or "",
            ]
        )
    story.append(
        _table(
            st,
            ["Reading", "Type", "Unit", "Required", "Ideal value", "Comment"],
            rows,
            widths=[44 * mm, 18 * mm, 16 * mm, 16 * mm, 26 * mm, None],
        )
    )

    # 4 — equations
    if entry["equations"]:
        story.append(Paragraph("4 · Mathematical equations", st["section"]))
        story.append(
            _table(
                st,
                ["Key", "Expression", "Meaning"],
                [
                    [eq["key"], Paragraph(f'<font face="{FONT_BODY}">{eq["expression"]}</font>', st["mono"]),
                     eq.get("description_en") or ""]
                    for eq in entry["equations"]
                ],
                widths=[34 * mm, 62 * mm, None],
            )
        )

    # 5 — evaluation and limits
    if entry["evaluation"]:
        story.append(Paragraph("5 · Evaluation criteria", st["section"]))
        story.append(
            _table(
                st,
                ["Metric", "How it is evaluated"],
                [[row.get("metric", ""), row.get("text_en", "")] for row in entry["evaluation"]],
                widths=[46 * mm, None],
            )
        )

    if entry["limits"]:
        story.append(Paragraph("5.1 · Acceptance limits by source", st["section"]))
        adopted = {
            i
            for i, row in enumerate(entry["limits"])
            if row["source_type"] == "AUTHORITY_LIMIT" and row["approval_status"] == "APPROVED"
        }
        story.append(
            _table(
                st,
                ["Metric", "Source", "Criterion", "Status"],
                [
                    [row["metric_key"], row["source_type"], _limit_text(row), row["approval_status"]]
                    for row in entry["limits"]
                ],
                widths=[46 * mm, 40 * mm, 46 * mm, None],
                highlight={i: PASS for i in adopted},
            )
        )
        story.append(
            Paragraph(
                "Green rows are the adopted authority limits; CONFLICT_REQUIRES_QA rows are recorded but can "
                "never produce a silent PASS.",
                st["note"],
            )
        )
    if entry.get("limit_notes"):
        for note in entry["limit_notes"]:
            story.append(Paragraph(f"Note on limits: {note}", st["note"]))

    # 6 — chart
    drawing = _chart_drawing(entry.get("chart") or {})
    if drawing is not None:
        chart = entry["chart"]
        caption = (
            f"Calibration curve — {chart.get('y_label') or ''} against {chart.get('x_label') or ''}"
            if chart.get("kind") == "line"
            else f"Reference values — {chart.get('y_label') or ''}"
        )
        story.append(Paragraph("6 · Chart / calibration curve", st["section"]))
        story.append(KeepTogether([drawing, Paragraph(caption.strip(" —"), st["note"])]))
        story.append(
            Paragraph(
                "The curve is drawn from the ideal worked example in this manual, not from a stored run.",
                st["note"],
            )
        )

    # 7 — references
    if entry["references"]:
        story.append(Paragraph("7 · Scientific references", st["section"]))
        for index, reference in enumerate(entry["references"], start=1):
            story.append(Paragraph(f"[{index}] {reference}", st["body"]))

    return story


def build_manual_pdf(payload: dict[str, Any]) -> bytes:
    """Render the manual. ``payload['entries']`` has one entry, or all twenty."""
    st = _styles_extra()
    entries: list[dict[str, Any]] = payload["entries"]
    single = len(entries) == 1

    def on_page(canvas, doc):  # noqa: ANN001
        canvas.saveState()
        canvas.setStrokeColor(LINE)
        canvas.line(14 * mm, 12 * mm, A4[0] - 14 * mm, 12 * mm)
        canvas.setFont(FONT_BODY, 7)
        canvas.setFillColor(colors.HexColor("#8a949e"))
        canvas.drawString(14 * mm, 8.5 * mm, payload["document_id"])
        canvas.drawCentredString(
            A4[0] / 2, 8.5 * mm, f"Reference Manual · {payload['protocol']['code']} v{payload['protocol']['version']}"
        )
        canvas.drawRightString(A4[0] - 14 * mm, 8.5 * mm, f"Page {doc.page} of {payload['page_total']}")
        canvas.restoreState()

    def render_story() -> list[Any]:
        """A fresh flowable list for each pass.

        Flowables — and ReportLab's chart widgets in particular — are consumed by the
        build that lays them out, and cannot be deep-copied. Two passes therefore need
        two independently constructed stories, not one copied twice.
        """
        story: list[Any] = []
        story.extend(_letterhead(st, payload.get("branding")))
        story.append(Spacer(1, 3 * mm))

        heading = Table(
            [
                [
                    Paragraph(
                        payload["title_en"], st["title2"]
                    )
                ],
                [
                    Paragraph(
                        payload["subtitle"],
                        ParagraphStyle("sub2", parent=st["sub"], fontSize=8.2),
                    )
                ],
            ],
            colWidths=[None],
        )
        heading.setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.6, BRAND),
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fbfcfd")),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        story.append(heading)
        story.append(Spacer(1, 3 * mm))

        if not single:
            story.append(Paragraph("Contents", st["section"]))
            contents = [
                [e["code"], e["name_en"], e["module"], e["standard_ref"]] for e in entries
            ]
            story.append(
                _table(
                    st,
                    ["Code", "Test", "Module", "Standard"],
                    contents,
                    widths=[16 * mm, 66 * mm, 26 * mm, None],
                )
            )
            story.append(
                Paragraph(
                    f"{len(entries)} tests · generated {payload['generated_at']} · "
                    "each section is self-contained and may be printed on its own.",
                    st["note"],
                )
            )
            story.append(PageBreak())

        for index, entry in enumerate(entries):
            story.extend(_test_story(st, entry))
            if index < len(entries) - 1:
                story.append(PageBreak())

        return story

    # The page count is only known after layout, and the footer must not say "of 1" on a
    # thirty-page manual. Two passes, each on its own copy: a flowable is consumed by the
    # build that lays it out, so reusing the list would emit an empty second document.
    buffer = io.BytesIO()
    doc = _document(buffer, payload)
    doc.build(render_story(), onFirstPage=on_page, onLaterPages=on_page)
    pages = doc.page
    payload["page_total"] = max(pages, 1)

    buffer = io.BytesIO()
    doc = _document(buffer, payload)
    doc.build(render_story(), onFirstPage=on_page, onLaterPages=on_page)
    return buffer.getvalue()


def _document(buffer: io.BytesIO, payload: dict[str, Any]) -> SimpleDocTemplate:
    return SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=12 * mm,
        bottomMargin=16 * mm,
        title=payload["title_en"],
        author="SBDMA Laboratory Calibration & OQ Platform",
        subject=payload["subtitle"],
    )

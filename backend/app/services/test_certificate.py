"""Per-test calibration certificate.

The run-level certificate attests a whole calibration campaign. The laboratory also has
to hand a customer a document for **one** measurement — an oven temperature check, a
wavelength accuracy verification — without the other nineteen tests in the annex. This
module renders that document: the same official letterhead, the instrument and reference
standard identification, the raw readings the analyst entered, the computed results with
the limit that was applied, the verdict, the date and the three electronic signatures.

It reuses the letterhead and typography of ``report_service`` deliberately rather than
re-implementing them: a second copy of the header would drift, and the header is the one
part of the page a regulator recognises instantly.

The payload is assembled by ``ExportService`` from stored rows only — nothing here is
taken from the client, so the document cannot be printed from an unsaved screen.
"""

from __future__ import annotations

import io
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.services.report_service import (
    BRAND,
    FONT_BODY,
    FONT_STRONG,
    _header_table,
    _letterhead,
    _styles,
    ar,
)

PASS_COLOR = colors.HexColor("#16794f")
FAIL_COLOR = colors.HexColor("#a2302a")
REVIEW_COLOR = colors.HexColor("#9a6a12")
MUTED = colors.HexColor("#5b6773")
LINE = colors.HexColor("#dfe5ea")


def _verdict_color(status: str):  # noqa: ANN202
    return {"PASS": PASS_COLOR, "FAIL": FAIL_COLOR}.get(status, REVIEW_COLOR)


def _kv_table(st: dict[str, ParagraphStyle], rows: list[tuple[str, str]], widths=(42 * mm, None)) -> Table:
    data = [
        [Paragraph(f"<b>{key}</b>", st["cell"]), Paragraph(value or "—", st["cell"])]
        for key, value in rows
    ]
    table = Table(data, colWidths=list(widths))
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.4, LINE),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f2f5f8")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 2.0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.0),
            ]
        )
    )
    return table


def _grid_table(
    st: dict[str, ParagraphStyle],
    header: list[str],
    rows: list[list[str]],
    widths: list[float] | None = None,
    *,
    verdict_col: int | None = None,
) -> Table:
    data = [[Paragraph(f"<b>{h}</b>", st["cellb"]) for h in header]]
    style = [
        ("GRID", (0, 0), (-1, -1), 0.4, LINE),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef1f5")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 1.9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.9),
    ]
    for index, row in enumerate(rows, start=1):
        cells = [Paragraph(str(cell), st["cell"]) for cell in row]
        if verdict_col is not None and len(row) > verdict_col:
            colour = _verdict_color(str(row[verdict_col]))
            cells[verdict_col] = Paragraph(
                f'<font color="{colour.hexval().replace("0x", "#")}"><b>{row[verdict_col]}</b></font>',
                st["cell"],
            )
        data.append(cells)
        if index % 2 == 0:
            style.append(("BACKGROUND", (0, index), (-1, index), colors.HexColor("#fafbfc")))
    table = Table(data, colWidths=widths, repeatRows=1)
    table.setStyle(TableStyle(style))
    return table


def build_test_certificate_pdf(payload: dict[str, Any]) -> bytes:
    """Render one test's certificate. ``payload`` comes from stored rows only."""
    st = _styles()
    test = payload["test"]
    run = payload["run"]
    instrument = payload["instrument"]

    # An Arabic line set inside an English paragraph has no natural break point and
    # ReportLab's logical-order renderer overlaps the two scripts. The closing line
    # therefore gets its own right-aligned Arabic run instead of being appended to
    # the document id.
    ar_style = ParagraphStyle("cert_ar", parent=st["lh_ar"], fontSize=7.2, leading=11)
    st["h2"].spaceBefore = 4

    def on_page(canvas, doc):  # noqa: ANN001
        canvas.saveState()
        canvas.setFont(FONT_BODY, 7)
        canvas.setFillColor(colors.HexColor("#8a949e"))
        canvas.drawString(14 * mm, 9 * mm, payload["document_id"])
        canvas.drawRightString(
            A4[0] - 14 * mm, 9 * mm, f"Page {doc.page} of {payload['page_total']}  ·  {payload['generated_at']}"
        )
        canvas.setStrokeColor(LINE)
        canvas.line(14 * mm, 12 * mm, A4[0] - 14 * mm, 12 * mm)
        canvas.restoreState()

    def render_story() -> list[Any]:
        status = test["status"]
        colour = _verdict_color(status)
        story: list[Any] = []

        story.extend(_letterhead(st, payload.get("branding")))
        story.append(Spacer(1, 2.5 * mm))
        story.append(
            _header_table(
                st,
                payload["subtitle"],
                title_en="Test Calibration Certificate",
                title_ar="شهادة معايرة اختبار",
            )
        )
        story.append(Spacer(1, 2.2 * mm))

        # ── verdict banner ─────────────────────────────────────────────────
        banner = Table(
            [
                [
                    Paragraph(
                        f'<font color="white" size=10><b>{test["code"]}</b></font>',
                        ParagraphStyle("tcode", parent=st["cellb"], alignment=TA_CENTER, fontSize=13),
                    ),
                    Paragraph(
                        f'<font color="white" size=9><b>{test["name_en"]}</b></font>',
                        ParagraphStyle("tname", parent=st["cellb"], textColor=colors.white, fontSize=10),
                    ),
                    Paragraph(
                        f'<font color="white" size=12><b>{status}</b></font>',
                        ParagraphStyle("tstatus", parent=st["cellb"], alignment=TA_CENTER),
                    ),
                ]
            ],
            colWidths=[20 * mm, None, 34 * mm],
        )
        banner.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (0, 0), BRAND),
                    ("BACKGROUND", (1, 0), (1, 0), colors.HexColor("#1d2a36")),
                    ("BACKGROUND", (2, 0), (2, 0), colour),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("TOPPADDING", (0, 0), (-1, -1), 3.6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3.6),
                    ("LEFTPADDING", (1, 0), (1, 0), 5),
                ]
            )
        )
        story.append(banner)
        story.append(Spacer(1, 2.2 * mm))

        # ── identification ────────────────────────────────────────────────
        story.append(Paragraph("1 · Identification", st["h2"]))
        story.append(
            _kv_table(
                st,
                [
                    ("Test", f"{test['code']} — {test['name_en']}"),
                    ("Module / standard", f"{test['module']} · {test['standard_ref']}"),
                    (
                        "Instrument",
                        f"{instrument['manufacturer']} {instrument['model']} · asset {instrument['asset_code']} · "
                        f"S/N {instrument['serial_number']}",
                    ),
                    ("Calibration run", f"{run['execution_code']} · {run['run_type']} · revision {run['revision']}"),
                    ("Reference standard", payload["reference"]["label"]),
                    ("Protocol", f"{payload['protocol']['code']} v{payload['protocol']['version']}"),
                    ("Limit source applied", run["limit_source_policy"]),
                ],
            )
        )
        story.append(Spacer(1, 1.4 * mm))

        # ── readings ──────────────────────────────────────────────────────
        if payload["readings"]:
            story.append(Paragraph("2 · Recorded readings", st["h2"]))
            story.append(
                KeepTogether(
                    _grid_table(
                        st,
                        ["Field", "Value", "Unit"],
                        payload["readings"],
                        widths=[None, 60 * mm, 28 * mm],
                    )
                )
            )
            story.append(Spacer(1, 1.4 * mm))

        # ── results ───────────────────────────────────────────────────────
        story.append(Paragraph("3 · Computed results and acceptance criteria", st["h2"]))
        story.append(
            _grid_table(
                st,
                ["Metric", "Result", "Limit applied", "Source", "Verdict", "Note"],
                payload["metrics"],
                # "Source" carries machine tokens such as AUTHORITY_LIMIT that must not
                # wrap mid-token: it is set wide enough for the longest one.
                widths=[34 * mm, 22 * mm, 36 * mm, 32 * mm, 16 * mm, None],
                verdict_col=4,
            )
        )
        if test.get("notes_ar"):
            story.append(Spacer(1, 1.5 * mm))
            story.append(Paragraph(f"Note: {test['notes_ar']}", st["note"]))
        story.append(Spacer(1, 1.8 * mm))

        # ── conformity statement ──────────────────────────────────────────
        statement = (
            f"The measurement described above was performed on the instrument identified in section 1 against "
            f"{payload['protocol']['code']} version {payload['protocol']['version']} and evaluated against the "
            f"acceptance limits stated in section 3. The verdict recorded for test {test['code']} is "
            f"<b>{status}</b>. Results are traceable to the reference standard identified in section 1 and are "
            f"reported by the laboratory under ISO/IEC 17025:2017 §7.8."
        )
        box = Table(
            [[Paragraph(statement, ParagraphStyle("stmt", parent=st["cell"], fontSize=8, leading=9.9))]],
            colWidths=[None],
        )
        box.setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.6, colour),
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fbfcfd")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 4.2),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4.2),
                ]
            )
        )
        # ── signatures ────────────────────────────────────────────────────
        # The closing block — conformity statement, the three signatures, the
        # fingerprint — is kept together: a signature table that breaks between the
        # analyst and the QA approver is exactly the thing an assessor queries. When
        # the block does not fit under section 3 it starts a second page as a whole.
        sig_rows = [
            [s["role"], s["name"], (s["at"] or "—").replace("T", " ").replace("Z", " UTC")]
            for s in payload["signatures"]
        ]
        closing: list[Any] = [
            Spacer(1, 1.2 * mm),
            box,
            Spacer(1, 1.6 * mm),
            Paragraph("4 · Electronic signatures", st["h2"]),
            _grid_table(st, ["Role", "Signed by", "Date and time"], sig_rows, widths=[45 * mm, None, 55 * mm]),
            Spacer(1, 2 * mm),
            Paragraph(
                f"Certificate fingerprint (SHA-256, run level): {run['certificate_hash'] or '—'}",
                st["note"],
            ),
            Paragraph(f"Document {payload['document_id']} · generated {payload['generated_at']}", st["note"]),
            Spacer(1, 1.6 * mm),
            Paragraph(ar("صادر إلكترونياً من منصة معايرة الهيئة"), ar_style),
        ]
        story.append(KeepTogether(closing))
        return story

    def _document(buffer: io.BytesIO) -> SimpleDocTemplate:
        return SimpleDocTemplate(
            buffer,
            pagesize=A4,
            leftMargin=14 * mm,
            rightMargin=14 * mm,
            topMargin=12 * mm,
            bottomMargin=16 * mm,
            title=f"{test['code']} — Test Calibration Certificate",
            author="SBDMA Laboratory Calibration & OQ Platform",
            subject=f"{run['execution_code']} / {test['code']}",
        )

    # The footer states "Page X of Y", so the total must be known before writing. The
    # page count comes from the build itself — counting "/Type /Page" in the bytes also
    # matches the "/Type /Pages" catalogue node and reports one page too many.
    buffer = io.BytesIO()
    doc = _document(buffer)
    doc.build(render_story(), onFirstPage=on_page, onLaterPages=on_page)
    payload["page_total"] = max(doc.page, 1)

    buffer = io.BytesIO()
    doc = _document(buffer)
    doc.build(render_story(), onFirstPage=on_page, onLaterPages=on_page)
    return buffer.getvalue()

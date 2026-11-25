"""Certificate (PDF) and data export (XLSX) generation.

Design rules taken from the specification and GxP practice:
  * nothing is invented — every value comes from a stored row;
  * a certificate is only ever produced for an APPROVED and LOCKED run;
  * the certificate prints the stored `certificate_hash` and a QR code that
    encodes the same hash, so a printed copy can be verified against the database;
  * every export is itself audited (who exported what and when);
  * Arabic text is shaped + bidi-reordered because ReportLab draws glyphs in
    logical order.
"""

from __future__ import annotations

import io
import uuid
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

import arabic_reshaper
import qrcode
from bidi.algorithm import get_display
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfbase.ttfonts import TTFont
from app.services.branding_service import DEFAULT_HEADER_AR, DEFAULT_HEADER_EN
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    KeepTogether,
    PageTemplate,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

#: Font families, in the order a deployment should be able to find them.
#:
#: The first entry is **shipped with the application** and that is deliberate: the
#: platform's Python runtime is not the laboratory's container, and on Vercel there is
#: no ``/usr/share/fonts`` at all. Production found this the hard way — the weekly KPI
#: job died with ``KeyError: 'DejaVuSans-Bold'`` because a style referenced a font that
#: had never been registered, and every PDF that carries the letterhead was affected.
#: A report generator whose fonts come from the host is a report generator that works
#: until it is deployed somewhere else.
ASSET_FONT_DIR = Path(__file__).resolve().parents[1] / "assets" / "fonts"
FONT_SEARCH_PATH: tuple[Path, ...] = (
    ASSET_FONT_DIR,
    Path("/usr/share/fonts/truetype/dejavu"),
    Path("/usr/share/fonts/TTF"),
)

FONT_REGULAR = "DejaVuSans"
FONT_BOLD = "DejaVuSans-Bold"
#: What ReportLab registers out of the box; used when no Arabic-capable font is found,
#: so a missing font degrades the shaping instead of raising from inside a PDF build.
FALLBACK_REGULAR = "Helvetica"
FALLBACK_BOLD = "Helvetica-Bold"


def _font_source(filename: str) -> Path | None:
    for directory in FONT_SEARCH_PATH:
        candidate = directory / filename
        if candidate.is_file():
            return candidate
    return None


def _register_fonts() -> bool:
    """Register an Arabic-capable font from the first place that has one."""
    try:
        regular = _font_source("DejaVuSans.ttf")
        bold = _font_source("DejaVuSans-Bold.ttf")
        if regular is None or bold is None:
            return False
        registered = pdfmetrics.getRegisteredFontNames()
        if FONT_REGULAR not in registered:
            pdfmetrics.registerFont(TTFont(FONT_REGULAR, str(regular)))
        if FONT_BOLD not in registered:
            pdfmetrics.registerFont(TTFont(FONT_BOLD, str(bold)))
        return True
    except Exception:  # pragma: no cover - a corrupt font file
        return False


HAS_ARABIC_FONT = _register_fonts()

#: The names every style must use. Never reference the constants above directly: if the
#: bold face failed to register, a style naming it raises at build time, not at import,
#: and the failure lands in whichever report happened to need bold text.
FONT_BODY = FONT_REGULAR if HAS_ARABIC_FONT else FALLBACK_REGULAR
FONT_STRONG = FONT_BOLD if HAS_ARABIC_FONT else FALLBACK_BOLD


def ar(text: str) -> str:
    """Shape and reorder Arabic text for ReportLab's logical-order renderer."""
    if not text:
        return ""
    if not HAS_ARABIC_FONT:
        return text
    return get_display(arabic_reshaper.reshape(str(text)))


def mix(en_text: str, ar_text: str) -> str:
    """Render an English/Arabic pair so both read correctly in an LTR renderer."""
    return f"{en_text} — {ar(ar_text)}" if ar_text else en_text


ARABIC_RANGE = range(0x0600, 0x06FF)


def has_arabic(text: str) -> bool:
    return any(ord(ch) in ARABIC_RANGE for ch in text)


def _fmt(value: Any, decimals: int | None = None) -> str:
    """Present a stored decimal without exposing 40 digits of binary noise.

    The stored value keeps full precision; only the printed form is rounded, and
    the certificate states that rule explicitly.
    """
    if value is None or value == "":
        return "—"
    if isinstance(value, str):
        try:
            number = Decimal(value)
        except (InvalidOperation, ValueError):
            return value
    elif isinstance(value, (int, float, Decimal)):
        number = Decimal(str(value))
    else:
        return str(value)

    if decimals is not None:
        quant = Decimal(1).scaleb(-decimals)
        return format(number.quantize(quant, rounding=ROUND_HALF_UP), "f")

    # 6 significant digits, trailing zeros trimmed — never scientific notation
    if number == 0:
        return "0"
    exp = number.adjusted()
    digits = max(0, min(6 - (exp + 1), 12))
    quant = Decimal(1).scaleb(-digits)
    text = format(number.quantize(quant, rounding=ROUND_HALF_UP), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _limit_text(raw: str | None) -> str:
    """Strip placeholder units the engine emits when a unit is dimensionless."""
    if not raw:
        return "—"
    cleaned = str(raw).replace("—", "").replace("  ", " ").strip()
    return cleaned or "—"


STATUS_COLORS = {
    "PASS": colors.HexColor("#16794f"),
    "FAIL": colors.HexColor("#b42318"),
    "UNDER_REVIEW": colors.HexColor("#1d4ed8"),
    "INCOMPLETE": colors.HexColor("#8a6d3b"),
}

BRAND = colors.HexColor("#21695e")


# ════════════════════════════════════════════════════════════════════════════
# Certificate PDF
# ════════════════════════════════════════════════════════════════════════════


def _qr_image(payload: str) -> Image:
    qr = qrcode.QRCode(version=None, box_size=3, border=1)
    qr.add_data(payload)
    qr.make(fit=True)
    buf = io.BytesIO()
    qr.make_image(fill_color="#16202b", back_color="white").save(buf, format="PNG")
    buf.seek(0)
    return Image(buf, width=26 * mm, height=26 * mm)


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    font = FONT_BODY
    bold = FONT_STRONG
    return {
        "title": ParagraphStyle(
            "title", parent=base["Title"], fontName=bold, fontSize=15, leading=19,
            textColor=BRAND, spaceAfter=2,
        ),
        "sub": ParagraphStyle(
            "sub", parent=base["Normal"], fontName=font, fontSize=8.5, leading=11,
            textColor=colors.HexColor("#5b6773"), alignment=TA_CENTER,
        ),
        "h2": ParagraphStyle(
            "h2", parent=base["Normal"], fontName=bold, fontSize=10, leading=13,
            textColor=BRAND, spaceBefore=6, spaceAfter=3,
        ),
        "cell": ParagraphStyle("cell", parent=base["Normal"], fontName=font, fontSize=7.6, leading=9.6),
        # machine codes are latin-only and must never break mid-token
        "cell_action": ParagraphStyle(
            "cell_action", parent=base["Normal"], fontName=font,
            fontSize=7.2, leading=9.2, splitLongWords=0,
        ),
        "cellb": ParagraphStyle(
            "cellb", parent=base["Normal"], fontName=bold, fontSize=7.6, leading=9.6
        ),
        "cellr": ParagraphStyle(
            "cellr", parent=base["Normal"], fontName=font, fontSize=7.6, leading=9.6,
            alignment=TA_RIGHT,
        ),
        "note": ParagraphStyle(
            "note", parent=base["Normal"], fontName=font, fontSize=7.2, leading=9.4,
            textColor=colors.HexColor("#5b6773"),
        ),
        # ── official letterhead ──────────────────────────────────────────
        # Both blocks are set at the same size and leading so the letterhead reads
        # as one balanced band, not as two lists that happen to sit side by side.
        "lh_ar": ParagraphStyle(
            "lh_ar", parent=base["Normal"], fontName=bold, fontSize=8.6, leading=11.4,
            alignment=TA_RIGHT, textColor=colors.HexColor("#16202b"),
        ),
        "lh_en": ParagraphStyle(
            "lh_en", parent=base["Normal"], fontName=bold, fontSize=8.6, leading=11.4,
            alignment=0, textColor=colors.HexColor("#16202b"),  # TA_LEFT
        ),
    }


#: marker for "already shaped" — see _letterhead
_AR_MARK = ""


def _headline_lines(branding: dict[str, Any], key: str, default: tuple[str, ...]) -> list[str]:
    lines = branding.get(key) or default
    return [str(line) for line in lines if str(line).strip()]


def _letterhead(
    st: dict[str, ParagraphStyle],
    branding: dict[str, Any] | None,
    *,
    width: float | None = None,
) -> list[Any]:
    """The official letterhead: Arabic right, logo centred, English left, ruled off.

    Nothing here is invented: the four lines come from the stored settings (or the
    agency's defaults) and the logo is the uploaded official mark. When no logo has
    been uploaded the centre cell simply stays empty rather than showing a stand-in
    graphic that a reader could mistake for an official symbol.
    """
    branding = branding or {}
    arabic = [_AR_MARK + line for line in _headline_lines(branding, "header_ar", DEFAULT_HEADER_AR)]
    english = _headline_lines(branding, "header_en", DEFAULT_HEADER_EN)

    usable = width or (A4[0] - 28 * mm)
    centre = usable * 0.20
    side = (usable - centre) / 2
    avail = side - 3 * mm

    # One type size for both blocks, chosen so that the longest line of either
    # language still fits on one line. Two blocks of different sizes read as two
    # unrelated captions; a letterhead has to look like a single band.
    size = 8.4
    longest_en = max(stringWidth(line, FONT_STRONG, size) for line in english)
    shaped_ar = [ar(line) for line in arabic]
    longest_ar = max(stringWidth(line, FONT_STRONG, size) for line in shaped_ar)
    longest = max(longest_en, longest_ar)
    if longest > avail:
        size = max(6.6, size * avail / longest)
    leading = size * 1.34

    ar_style = ParagraphStyle(
        "lh_ar_run", parent=st["lh_ar"], fontSize=size, leading=leading
    )
    en_style = ParagraphStyle(
        "lh_en_run", parent=st["lh_en"], fontSize=size, leading=leading
    )

    centre_cell: Any = Paragraph("", en_style)
    body = branding.get("logo_bytes")
    if body:
        try:
            logo = Image(io.BytesIO(body))
            max_w, max_h = centre - 6 * mm, 16 * mm
            ratio = min(max_w / logo.imageWidth, max_h / logo.imageHeight)
            logo.drawWidth = logo.imageWidth * ratio
            logo.drawHeight = logo.imageHeight * ratio
            logo.hAlign = "CENTER"
            centre_cell = logo
        except Exception:  # noqa: BLE001 - a broken image must not lose the report
            centre_cell = Paragraph("", en_style)

    table = Table(
        [
            [
                [Paragraph(line, ar_style) for line in shaped_ar],
                centre_cell,
                [Paragraph(line, en_style) for line in english],
            ]
        ],
        colWidths=[side, centre, side],
    )
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (0, 0), (0, 0), "RIGHT"),
                ("ALIGN", (1, 0), (1, 0), "CENTER"),
                ("ALIGN", (2, 0), (2, 0), "LEFT"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    # a heavy brand rule with a hairline beneath: a formal divider, not a box
    rule = Table([[""]], colWidths=[usable], rowHeights=[2.2 * mm])
    rule.setStyle(
        TableStyle(
            [
                ("LINEABOVE", (0, 0), (-1, 0), 1.1, BRAND),
                ("LINEBELOW", (0, 0), (-1, 0), 0.4, colors.HexColor("#b9c4cc")),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return [table, Spacer(1, 1.6 * mm), rule]


def _header_table(
    st: dict[str, ParagraphStyle],
    subtitle: str,
    *,
    title_en: str = "Calibration Certificate",
    title_ar: str = "شهادة معايرة",
) -> Table:
    logo = Paragraph(
        "<b>SBDMA</b><br/><font size=6.5>Laboratory Calibration &amp; OQ Platform</font>",
        ParagraphStyle("logo", parent=st["cellb"], fontSize=13, leading=15, textColor=colors.white),
    )
    titles = [
        Paragraph(mix(title_en, title_ar), st["title"]),
        Paragraph(subtitle, st["sub"]),
    ]
    table = Table([[logo, titles]], colWidths=[38 * mm, None])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, 0), BRAND),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (1, 0), (1, 0), "CENTER"),
                ("LEFTPADDING", (1, 0), (1, 0), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("BOX", (0, 0), (-1, -1), 0.6, BRAND),
            ]
        )
    )
    return table


def _clone(story: list[Any]) -> list[Any]:
    """Flowables are single-use; both passes need their own copy."""
    import copy

    return [copy.deepcopy(item) for item in story]


def build_certificate_pdf(payload: dict[str, Any]) -> bytes:
    """Render the approved-run certificate.

    `payload` is assembled by the service layer from stored rows only.
    """
    st = _styles()
    def on_page(canvas, doc):  # noqa: ANN001
        canvas.saveState()
        canvas.setFont(FONT_BODY, 7)
        canvas.setFillColor(colors.HexColor("#8a949e"))
        canvas.drawString(14 * mm, 9 * mm, payload["document_id"])
        canvas.drawRightString(
            A4[0] - 14 * mm,
            9 * mm,
            f"Page {doc.page} of {payload['page_total']}  ·  {payload['generated_at']}",
        )
        canvas.setStrokeColor(colors.HexColor("#dfe5ea"))
        canvas.line(14 * mm, 12 * mm, A4[0] - 14 * mm, 12 * mm)
        canvas.restoreState()

    run = payload["run"]
    instrument = payload["instrument"]
    story: list[Any] = []

    story.extend(_letterhead(st, payload.get("branding")))
    story.append(Spacer(1, 2.5 * mm))
    story.append(_header_table(st, payload["subtitle"]))
    story.append(Spacer(1, 4 * mm))

    # ── verdict banner ─────────────────────────────────────────────────────
    verdict = run["overall_status"]
    banner = Table(
        [
            [
                Paragraph(
                    f'<font color="white" size=11><b>{verdict}</b></font>',
                    ParagraphStyle("v", parent=st["cellb"], alignment=TA_CENTER),
                ),
                Paragraph(
                    mix(f"Overall verdict: <b>{verdict}</b>", "نتيجة التشغيل الكلية"),
                    ParagraphStyle("vt", parent=st["cell"], textColor=colors.white, fontSize=9),
                ),
            ]
        ],
        colWidths=[34 * mm, None],
    )
    banner.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), STATUS_COLORS.get(verdict, BRAND)),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (1, 0), (1, 0), 8),
            ]
        )
    )
    story.append(banner)
    story.append(Spacer(1, 3 * mm))

    # ── identification ─────────────────────────────────────────────────────
    info_rows = [
        [
            Paragraph("<b>Run code</b>", st["cell"]), Paragraph(run["execution_code"], st["cellb"]),
            Paragraph(ar("رمز التشغيل"), st["cellr"]),
        ],
        [
            Paragraph("<b>Instrument</b>", st["cell"]),
            Paragraph(
                f"{instrument['manufacturer']} {instrument['model']} — {instrument['asset_code']}",
                st["cell"],
            ),
            Paragraph("", st["cellr"]),
        ],
        [
            Paragraph("<b>Part / Serial</b>", st["cell"]),
            Paragraph(f"{instrument['part_number'] or '—'} / {instrument['serial_number']}", st["cell"]),
            Paragraph("", st["cellr"]),
        ],
        [
            Paragraph("<b>Category / Dept</b>", st["cell"]),
            Paragraph(f"{instrument['category']} — {instrument['department_code']}", st["cell"]),
            Paragraph(ar("الفئة / القسم"), st["cellr"]),
        ],
        [
            Paragraph("<b>Protocol</b>", st["cell"]),
            Paragraph(f"{payload['protocol']['code']} v{payload['protocol']['version']}", st["cell"]),
            Paragraph(ar("البروتوكول"), st["cellr"]),
        ],
        [
            Paragraph("<b>Run type</b>", st["cell"]),
            Paragraph(run["run_type"], st["cell"]),
            Paragraph(ar("نوع التشغيل"), st["cellr"]),
        ],
        [
            Paragraph("<b>Limit source applied</b>", st["cell"]),
            Paragraph(run["limit_source_policy"], st["cell"]),
            Paragraph(ar("مصدر حدود القبول"), st["cellr"]),
        ],
        [
            Paragraph("<b>Ambient</b>", st["cell"]),
            Paragraph(f"{run['ambient_temp_c'] or '—'} °C / {run['ambient_humidity'] or '—'} %RH", st["cell"]),
            Paragraph(ar("ظروف البيئة"), st["cellr"]),
        ],
        [
            Paragraph("<b>Reference item</b>", st["cell"]),
            Paragraph(payload["reference"]["label"], st["cell"]),
            Paragraph(ar("الأداة المرجعية"), st["cellr"]),
        ],
        [
            Paragraph("<b>Started / Approved</b>", st["cell"]),
            Paragraph(f"{run['started_at']} → {run['qa_approved_at'] or '—'}", st["cell"]),
            Paragraph(ar("البدء / الاعتماد"), st["cellr"]),
        ],
    ]
    info = Table(info_rows, colWidths=[38 * mm, None, 30 * mm])
    info.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#dfe5ea")),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f4f7f8")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
            ]
        )
    )
    story.append(info)

    # ── results ────────────────────────────────────────────────────────────
    story.append(Paragraph(mix("Test results", "نتائج الاختبارات"), st["h2"]))
    head = [
        Paragraph(f'<b>Test</b> <font size=6 color="#7a868f">{ar("اختبار")}</font>', st["cellb"]),
        Paragraph(f'<b>Metric</b> <font size=6 color="#7a868f">{ar("المقياس")}</font>', st["cellb"]),
        Paragraph(f'<b>Value</b> <font size=6 color="#7a868f">{ar("القيمة")}</font>', st["cellb"]),
        Paragraph(f'<b>Unit</b> <font size=6 color="#7a868f">{ar("الوحدة")}</font>', st["cellb"]),
        Paragraph(f'<b>Applied limit</b> <font size=6 color="#7a868f">{ar("الحد المطبق")}</font>', st["cellb"]),
        Paragraph(f'<b>Source</b> <font size=6 color="#7a868f">{ar("المصدر")}</font>', st["cellb"]),
        Paragraph(f'<b>Status</b> <font size=6 color="#7a868f">{ar("الحالة")}</font>', st["cellb"]),
    ]
    rows: list[list[Any]] = [head]
    row_tones: list[tuple[int, str]] = []
    for result in run["results"]:
        if not result["metric_evaluations"]:
            rows.append(
                [
                    Paragraph(result["test_code"], st["cellb"]),
                    Paragraph(mix("selector checks", "فحوص الحساسات والمفاتيح"), st["cell"]),
                    Paragraph("—", st["cell"]),
                    Paragraph("—", st["cell"]),
                    Paragraph("all selectors must read Passed", st["cell"]),
                    Paragraph("SOP", st["cell"]),
                    Paragraph(f"<b>{result['status']}</b>", st["cell"]),
                ]
            )
            row_tones.append((len(rows) - 1, result["status"]))
            continue
        for evaluation in result["metric_evaluations"]:
            rows.append(
                [
                    Paragraph(result["test_code"], st["cellb"]),
                    Paragraph(evaluation["metric_key"], st["cell"]),
                    Paragraph(_fmt(evaluation.get("value")), st["cell"]),
                    Paragraph((evaluation.get("unit") or "").strip() or "—", st["cell"]),
                    Paragraph(_limit_text(evaluation.get("limit_text")), st["cell"]),
                    Paragraph(evaluation.get("applied_source") or "—", st["cell"]),
                    Paragraph(f"<b>{evaluation['status']}</b>", st["cell"]),
                ]
            )
            row_tones.append((len(rows) - 1, evaluation["status"]))

    table = Table(rows, repeatRows=1, colWidths=[12 * mm, 38 * mm, 24 * mm, 16 * mm, 40 * mm, 30 * mm, None])
    style = [
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#e3e8ec")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef3f4")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 1.8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.8),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]
    for index, status in row_tones:
        colour = STATUS_COLORS.get(status)
        if colour is not None and status != "PASS":
            style.append(("BACKGROUND", (6, index), (6, index), colours.Color(
                colour.red, colour.green, colour.blue, 0.12
            )))
    table.setStyle(TableStyle(style))
    story.append(table)

    summary = payload["summary"]
    story.append(Spacer(1, 2 * mm))
    story.append(
        Paragraph(
            f"Pass {summary['pass']} · Fail {summary['fail']} · "
            f"Under review {summary['review']} · Incomplete {summary['incomplete']} "
            f"— {payload['metric_total']} metric evaluations against "
            f"{payload['limit_total']} stored limits. Values are stored at full decimal "
            "precision and printed to 6 significant digits.",
            st["note"],
        )
    )

    # ── signatures ─────────────────────────────────────────────────────────
    signatures = payload["signatures"]
    sig_rows = [[
        Paragraph(f'<b>Role</b> <font size=6 color="#7a868f">{ar("الدور")}</font>', st["cellb"]),
        Paragraph("<b>Name</b>", st["cellb"]),
        Paragraph("<b>Signature timestamp (UTC)</b>", st["cellb"]),
        Paragraph("<b>Meaning</b>", st["cellb"]),
    ]]
    for sig in signatures:
        # Narrow cells cannot hold shaped Arabic: the Arabic role name travels in
        # the wider "Meaning" column where it wraps correctly.
        sig_rows.append([
            Paragraph(sig["role"], st["cell"]),
            Paragraph(sig["name"], st["cell"]),
            Paragraph(sig["at"] or "— not signed —", st["cell"]),
            Paragraph(mix(sig["meaning"], sig["role_ar"]), st["cell"]),
        ])
    sig_table = Table(sig_rows, colWidths=[36 * mm, 34 * mm, 42 * mm, None], repeatRows=1)
    sig_table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#dfe5ea")),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef3f4")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    story.append(PageBreak())
    story.append(Paragraph(mix("Electronic signatures", "التوقيعات الإلكترونية"), st["h2"]))
    story.append(sig_table)

    # ── integrity block ────────────────────────────────────────────────────
    qr_payload = f"SBDMA|{run['execution_code']}|{run['certificate_hash']}"
    integrity = Table(
        [
            [
                _qr_image(qr_payload),
                [
                    Paragraph("<b>Certificate fingerprint (SHA-256)</b>", st["cellb"]),
                    Paragraph(
                        f'<font face="{FONT_BODY}" size=7>{run["certificate_hash"]}</font>',
                        st["cell"],
                    ),
                    Spacer(1, 1.5 * mm),
                    Paragraph(
                        "This fingerprint is computed over the run code, instrument, verdict, "
                        "all three signatory identifiers, the approval timestamp and the revision "
                        "counter. Any later change to a locked run is rejected by the database, "
                        "so a re-print must reproduce this exact value.",
                        st["note"],
                    ),
                    Spacer(1, 1 * mm),
                    Paragraph(
                        ar(
                            "البصمة محسوبة على رمز التشغيل والجهاز والنتيجة وهويات الموقعين الثلاثة "
                            "ووقت الاعتماد ورقم المراجعة. أي تعديل لاحق مرفوض من قاعدة البيانات نفسها."
                        ),
                        st["note"],
                    ),
                ],
            ]
        ],
        colWidths=[30 * mm, None],
    )
    integrity.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.6, BRAND),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (1, 0), (1, 0), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(
        KeepTogether([Paragraph(mix("Data integrity", "سلامة البيانات"), st["h2"]), integrity])
    )

    # ── audit trail ────────────────────────────────────────────────────────
    audit_rows = payload.get("audit") or []
    if audit_rows:
        story.append(
            Paragraph(mix("Audit trail for this run", "سجل التدقيق لهذا التشغيل"), st["h2"])
        )
        audit_table_rows: list[list[Any]] = [[
            Paragraph("<b>Timestamp (UTC)</b>", st["cellb"]),
            Paragraph("<b>Actor</b>", st["cellb"]),
            Paragraph("<b>Action</b>", st["cellb"]),
            Paragraph("<b>Reason</b>", st["cellb"]),
            Paragraph("<b>Hash prefix</b>", st["cellb"]),
        ]]
        for row in audit_rows[:60]:
            stamp, actor, role, action, reason, hash_prefix = (list(row) + [""] * 6)[:6]
            audit_table_rows.append(
                [
                    Paragraph(str(stamp), st["cell"]),
                    Paragraph(f"{actor}<br/><font size=6 color='#7a868f'>{role}</font>", st["cell"]),
                    # action codes are long single tokens (RUN_QA_APPROVED_AND_LOCKED);
                    # give the column room and let them wrap at underscores
                    Paragraph(str(action).replace("_", "_<wbr/>"), st["cell_action"]),
                    Paragraph(
                        mix(str(reason or "—"), "") if not has_arabic(str(reason or "")) else ar(str(reason)),
                        st["cell"],
                    ),
                    Paragraph(str(hash_prefix), st["cell"]),
                ]
            )
        audit_table = Table(
            audit_table_rows, colWidths=[28 * mm, 28 * mm, 46 * mm, None, 24 * mm], repeatRows=1
        )
        audit_table.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#e3e8ec")),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef3f4")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 1.8),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 1.8),
                ]
            )
        )
        story.append(audit_table)
        story.append(
            Paragraph(
                "Each row's hash covers the previous hash and the row payload; altering any "
                "historical row breaks every subsequent hash and is rejected by the database.",
                st["note"],
            )
        )

    story.append(Spacer(1, 2.5 * mm))
    story.append(
        Paragraph(
            "Generated by the SBDMA Laboratory Calibration &amp; OQ Platform. The ASCII portion of "
            "this document is authoritative; Arabic text is a translation aid. Signed records are "
            "immutable: the audit trail that produced them is append-only at the database level.",
            st["note"],
        )
    )

    # Two passes: the footer states "Page X of Y", so the page count must be
    # known before the content is written. The first pass is written to a
    # throwaway buffer and only counted.
    def _build(target: io.BytesIO, total: int) -> None:
        payload["page_total"] = total
        document = SimpleDocTemplate(
            target,
            pagesize=A4,
            leftMargin=14 * mm,
            rightMargin=14 * mm,
            topMargin=12 * mm,
            bottomMargin=16 * mm,
            title=payload["document_id"],
            author="SBDMA Laboratory Calibration Platform",
            subject=payload["run"]["execution_code"],
        )
        document.build(_clone(story), onFirstPage=on_page, onLaterPages=on_page)

    probe = io.BytesIO()
    _build(probe, 1)
    pages = max(1, len(__import__("re").findall(rb"/Type\s*/Page[^s]", probe.getvalue())))
    final = io.BytesIO()
    _build(final, pages)
    return final.getvalue()


# ════════════════════════════════════════════════════════════════════════════
# XLSX export
# ════════════════════════════════════════════════════════════════════════════

#: Rows 1-4 carry the official letterhead, 5 is its breathing space, then the sheet
#: title/subtitle and the table header. Data therefore starts here — the tests and
#: the summary scan read from this constant instead of a magic 5.
XLSX_LETTERHEAD_ROWS = 4
XLSX_SPACER_ROW = 1
XLSX_FIRST_DATA_ROW = XLSX_LETTERHEAD_ROWS + XLSX_SPACER_ROW + 4

HEADER_FILL = PatternFill("solid", fgColor="21695E")
HEADER_FONT = Font(name="Calibri", bold=True, color="FFFFFF", size=10)
TITLE_FONT = Font(name="Calibri", bold=True, size=13, color="21695E")
THIN = Side(style="thin", color="D5DDE2")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def _write_letterhead(ws, branding: dict[str, Any] | None, columns: int) -> None:  # noqa: ANN001
    """The official letterhead, right-aligned Arabic and left-aligned English.

    Spreadsheets have no page header that survives every viewer, so the letterhead
    is real cells: it prints, it sorts with the sheet and it exports onward intact.
    The Arabic block occupies the right half with its reading order set to RTL, the
    English block the left half, and the logo is floated in the centre.
    """
    branding = branding or {}
    arabic = _headline_lines(branding, "header_ar", DEFAULT_HEADER_AR)
    english = _headline_lines(branding, "header_en", DEFAULT_HEADER_EN)
    half = max(2, columns // 2)
    ar_start, ar_end = half + 1, columns
    en_start, en_end = 1, half

    for index in range(XLSX_LETTERHEAD_ROWS):
        row = index + 1
        ws.row_dimensions[row].height = 16
        if index < len(english):
            ws.cell(row=row, column=en_start, value=english[index])
        if index < len(arabic):
            ws.cell(row=row, column=ar_start, value=arabic[index])
        if ar_end > ar_start:
            ws.merge_cells(start_row=row, start_column=ar_start, end_row=row, end_column=ar_end)
        if en_end > en_start:
            ws.merge_cells(start_row=row, start_column=en_start, end_row=row, end_column=en_end)
        en_cell = ws.cell(row=row, column=en_start)
        en_cell.font = Font(bold=True, size=10, color="16202B")
        en_cell.alignment = Alignment(horizontal="left", vertical="center")
        ar_cell = ws.cell(row=row, column=ar_start)
        ar_cell.font = Font(bold=True, size=10, color="16202B")
        ar_cell.alignment = Alignment(horizontal="right", vertical="center", readingOrder=2)

    rule_row = XLSX_LETTERHEAD_ROWS
    rule = Side(style="medium", color="21695E")
    for column in range(1, columns + 1):
        ws.cell(row=rule_row, column=column).border = Border(bottom=rule)

    body = branding.get("logo_bytes")
    if body:
        try:
            from openpyxl.drawing.image import Image as XLImage

            image = XLImage(io.BytesIO(body))
            ratio = min(60 / image.width, 56 / image.height, 1.0)
            image.width = max(1, int(image.width * ratio))
            image.height = max(1, int(image.height * ratio))
            anchor = get_column_letter(max(1, half)) + "1"
            ws.add_image(image, anchor)
        except Exception:  # noqa: BLE001 - the report outranks its logo
            pass


def _write_sheet(ws, title: str, subtitle: str, headers: list[str], rows: list[list[Any]],  # noqa: ANN001
                 widths: list[int], branding: dict[str, Any] | None = None) -> None:
    title_row = XLSX_LETTERHEAD_ROWS + XLSX_SPACER_ROW + 1
    ws.cell(row=title_row, column=1, value=title).font = TITLE_FONT
    ws.cell(row=title_row + 1, column=1, value=subtitle).font = Font(
        size=9, italic=True, color="5B6773"
    )
    header_row = XLSX_FIRST_DATA_ROW - 1
    for col, header in enumerate(headers, start=1):
        cell = ws.cell(row=header_row, column=col, value=header)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.border = BORDER
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(col)].width = widths[col - 1]
    for r, row in enumerate(rows, start=header_row + 1):
        for c, value in enumerate(row, start=1):
            cell = ws.cell(row=r, column=c, value=value)
            cell.border = BORDER
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            if c == len(headers) and str(value) in STATUS_COLORS:
                colour = STATUS_COLORS[str(value)]
                cell.font = Font(bold=True, color=f"{int(colour.red * 255):02X}{int(colour.green * 255):02X}{int(colour.blue * 255):02X}")
    ws.freeze_panes = ws.cell(row=header_row + 1, column=1)
    ws.sheet_view.rightToLeft = False
    _write_letterhead(ws, branding, len(headers))


def build_run_xlsx(payload: dict[str, Any]) -> bytes:
    run = payload["run"]
    wb = Workbook()

    ws = wb.active
    ws.title = "Summary"
    _write_sheet(
        ws,
        f"Calibration Run {run['execution_code']}",
        f"Generated {payload['generated_at']} · {payload['document_id']} · "
        f"status {run['overall_status']} · locked={run['is_locked']}",
        ["Field", "Value"],
        [
            ["Execution code", run["execution_code"]],
            ["Overall status", run["overall_status"]],
            ["Run type", run["run_type"]],
            ["Limit source policy", run["limit_source_policy"]],
            ["Instrument", f"{payload['instrument']['manufacturer']} {payload['instrument']['model']}"],
            ["Asset code", payload["instrument"]["asset_code"]],
            ["Serial number", payload["instrument"]["serial_number"]],
            ["Category / department", f"{payload['instrument']['category']} / {payload['instrument']['department_code']}"],
            ["Protocol", f"{payload['protocol']['code']} v{payload['protocol']['version']}"],
            ["Reference item", payload["reference"]["label"]],
            ["Ambient temperature (°C)", run["ambient_temp_c"]],
            ["Ambient humidity (%RH)", run["ambient_humidity"]],
            ["Analyst", payload["signatures"][0]["name"]],
            ["Analyst signed at", payload["signatures"][0]["at"]],
            ["Technical reviewer", payload["signatures"][1]["name"]],
            ["Reviewer signed at", payload["signatures"][1]["at"]],
            ["QA approver", payload["signatures"][2]["name"]],
            ["QA approved at", payload["signatures"][2]["at"]],
            ["Revision", run["revision"]],
            ["Certificate fingerprint (SHA-256)", run["certificate_hash"] or "— not approved —"],
            ["Started at", run["started_at"]],
            ["Completed at", run["completed_at"]],
        ],
        [34, 78], branding=payload.get("branding"),
    )

    ws2 = wb.create_sheet("Results")
    rows: list[list[Any]] = []
    for result in run["results"]:
        if not result["metric_evaluations"]:
            rows.append([result["test_code"], "selectors", "—", "—", "all selectors Passed", "SOP", result["status"]])
            continue
        for evaluation in result["metric_evaluations"]:
            rows.append([
                result["test_code"],
                evaluation["metric_key"],
                evaluation["value"],
                evaluation.get("unit") or "",
                evaluation.get("limit_text") or "",
                evaluation.get("applied_source") or "",
                evaluation["status"],
            ])
    _write_sheet(
        ws2,
        "Metric evaluations",
        "Values are stored as exact decimals on the server and exported verbatim.",
        ["Test", "Metric", "Value", "Unit", "Applied limit", "Source", "Status"],
        rows,
        [9, 30, 20, 12, 30, 24, 14], branding=payload.get("branding"),
    )

    ws3 = wb.create_sheet("Limits")
    _write_sheet(
        ws3,
        "Acceptance limits applied to this protocol",
        "Conflicted or unapproved limits force the run to UNDER_REVIEW.",
        ["Test", "Metric", "Source", "Operator", "Min", "Max", "Unit", "Approval status"],
        payload["limits"],
        [9, 30, 24, 10, 12, 12, 12, 24], branding=payload.get("branding"),
    )

    ws4 = wb.create_sheet("Audit")
    _write_sheet(
        ws4,
        "Audit trail for this run",
        "Append-only. Each row's hash covers the previous hash and the payload.",
        ["Timestamp (UTC)", "Actor", "Role", "Action", "Reason", "Hash (prefix)"],
        payload["audit"],
        [24, 18, 16, 32, 46, 20], branding=payload.get("branding"),
    )

    ws5 = wb.create_sheet("Raw inputs")
    _write_sheet(
        ws5,
        "Raw readings as entered",
        "ALCOA+: raw data exported exactly as captured, before any calculation.",
        ["Test", "Field", "Value"],
        payload["raw_rows"],
        [9, 30, 60], branding=payload.get("branding"),
    )

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def document_id(kind: str, run_code: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"SBDMA-{kind}-{run_code}-{stamp}-{uuid.uuid4().hex[:6].upper()}"


# ══════════════════════════════════════════════════════════════════════════════
# KPI report — the scheduled weekly register
# ══════════════════════════════════════════════════════════════════════════════


def build_kpi_pdf(payload: dict[str, Any]) -> bytes:
    """Weekly KPI register as a PDF.

    Deliberately shaped like the certificate: same header, same footer with the
    document id and page count, same font handling. A QA officer who trusts one
    document should not have to learn a second layout to trust the other.
    """
    st = _styles()
    buf = io.BytesIO()
    doc = BaseDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=16 * mm,
        title=mix("KPI report", "تقرير مؤشرات الأداء"),
        author="SBDMA",
    )

    def on_page(canvas, doc_):  # noqa: ANN001
        canvas.saveState()
        canvas.setFont(FONT_BODY, 7)
        canvas.setFillColor(colors.HexColor("#8a949e"))
        canvas.drawString(14 * mm, 9 * mm, payload["document_id"])
        canvas.drawRightString(
            A4[0] - 14 * mm,
            9 * mm,
            f"Page {doc_.page} of {payload['page_total']}  ·  {payload['generated_at']}",
        )
        canvas.restoreState()

    frames = [Frame(14 * mm, 16 * mm, A4[0] - 28 * mm, A4[1] - 30 * mm, id="main")]
    doc.addPageTemplates([PageTemplate(id="kpi", frames=frames, onPage=on_page)])

    story: list[Any] = []
    story.extend(_letterhead(st, payload.get("branding")))
    story.append(Spacer(1, 2.5 * mm))
    story.append(
        _header_table(
            st,
            f"{payload['scope_label']} · {payload['period_label']}",
            title_en="KPI Report",
            title_ar="تقرير مؤشرات الأداء",
        )
    )
    story.append(Spacer(1, 5 * mm))

    def section(title_en: str, title_ar: str) -> None:
        story.append(
            Paragraph(
                f'<font color="#173a5e"><b>{title_en}</b></font> — {ar(title_ar)}',
                ParagraphStyle("kpi-sect", parent=st["h2"], fontSize=10.5, spaceBefore=8, spaceAfter=3),
            )
        )

    def metrics_table(rows: list[tuple[str, str, Any, str]]) -> Table:
        data = [
            [
                Paragraph(
                    f'<font color="white">{mix("Metric", "المؤشر")}</font>', st["cellb"]
                ),
                Paragraph(
                    f'<font color="white">{mix("Value", "القيمة")}</font>', st["cellb"]
                ),
                Paragraph(
                    f'<font color="white">{mix("Basis for the figure", "أساس الرقم")}</font>',
                    st["cellb"],
                ),
            ]
        ]
        for label_en, label_ar, value, basis in rows:
            data.append([
                Paragraph(f"{label_en} — {ar(label_ar)}", st["cell"]),
                Paragraph(f"<b>{_fmt(value) if value is not None else '—'}</b>", st["cellb"]),
                Paragraph(basis, st["cell"]),
            ])
        table = Table(data, colWidths=[70 * mm, 34 * mm, None], repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), BRAND),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#dfe5ea")),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f9fb")]),
                ]
            )
        )
        return table

    inst = payload["instruments"]
    runs = payload["runs"]
    devs = payload["deviations"]
    comp = payload["compliance"]

    section("Instruments", "الأجهزة")
    story.append(
        metrics_table(
            [
                ("Registered instruments", "أجهزة مسجلة", inst["total"], "non-deleted instruments"),
                ("Overdue calibration", "متأخرة المعايرة", inst["overdue"], "next_due_date < today"),
                ("Due within 30 days", "مستحقة خلال 30 يوماً", inst["due_within_30_days"], "next_due_date ≤ today+30"),
            ]
        )
    )

    section("Calibration runs", "تشغيلات المعايرة")
    story.append(
        metrics_table(
            [
                ("Completed runs", "تشغيلات مكتملة", runs["completed"], "PASS + FAIL + UNDER_REVIEW"),
                ("Passed", "مطابقة", runs["passed"], "overall_status = PASS"),
                ("Failed", "غير مطابقة", runs["failed"], "overall_status = FAIL"),
                ("Pass rate", "معدل النجاح",
                 f"{runs['pass_rate_percent']}%" if runs["pass_rate_percent"] is not None else None,
                 "passed ÷ completed — no synthetic value when completed = 0"),
                ("Awaiting QA approval", "بانتظار اعتماد QA", runs["pending_qa_approval"], "unlocked & PASS/UNDER_REVIEW"),
                ("Approved & locked", "معتمدة ومقفلة", runs["locked"], "is_locked = true"),
                ("Mean approval time (days)", "متوسط زمن الاعتماد", runs["mean_approval_days"], "qa_approved_at − started_at"),
            ]
        )
    )

    section("Deviations (OOS)", "الانحرافات خارج المواصفة")
    story.append(
        metrics_table(
            [
                ("Open deviations", "انحرافات مفتوحة", devs["open"], "status not CLOSED/CANCELLED"),
                ("Open critical", "مفتوحة حرجة", devs["critical_open"], "classification = CRITICAL"),
            ]
        )
    )

    section("Compliance", "الامتثال")
    story.append(
        metrics_table(
            [
                ("Expired reference equipment", "أدوات مرجعية منتهية", comp["expired_reference_equipment"], "expiry_date < today"),
                ("Expired reference standards", "معايير مرجعية منتهية", comp["expired_reference_standards"], "expiry_date < today"),
                ("Open maintenance tickets", "تذاكر صيانة مفتوحة", comp["open_maintenance_tickets"], "OPEN or IN_PROGRESS"),
                ("D₂ lamp alerts", "تنبيهات مصباح D₂", comp["d2_lamp_alerts"], "lamp hours ≥ 1800"),
            ]
        )
    )

    story.append(Spacer(1, 5 * mm))
    story.append(
        Paragraph(
            ar(
                "جميع القيم محسوبة من صفوف قاعدة البيانات لحظة التوليد، ولا تُدخل يدوياً. "
                "التقرير مُدرج في سجل التدقيق بمعرّفه وبصمته."
            ),
            ParagraphStyle("kpi-note", parent=st["sub"], fontSize=8, textColor=colors.HexColor("#6b7488")),
        )
    )

    doc.build(story)
    return buf.getvalue()

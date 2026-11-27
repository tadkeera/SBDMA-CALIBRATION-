"""Vector charts for the per-test certificate.

The laboratory asked for the certificate to carry its charts — on their own page, after
the page of values, not interleaved with the tables. Three decisions follow from that:

**The charts are drawn from stored rows.** Every series here comes from
``calibration_test_results.raw_inputs_jsonb`` / ``calculated_outputs_jsonb``, the two
columns written once when the run was executed and never edited afterwards. A chart on a
certificate is a reading of the record, so it may not be drawn from anything the caller
sends.

**They are published as vector drawings, not bitmaps.** ``graphics.renderPDF`` embeds the
shapes as PDF path operators, so a chart stays sharp at any zoom and the file stays small
— the alternative, rendering to PNG on the server, would need an image backend the
deployment does not carry and would multiply the certificate's size.

**Each chart knows its own limits.** A figure positioned at index ``i`` is at the
acceptance limit for that test, so a value that failed is visibly outside the dashed line
and a value that passed is visibly inside it. A chart without its limit is decoration.

The module is pure apart from ReportLab itself: it takes a description of the series and
returns flowables, and the caller decides the page break.
"""

from __future__ import annotations

from typing import Any

from reportlab.graphics import renderPDF
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.legends import Legend
from reportlab.graphics.charts.linecharts import HorizontalLineChart
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.shapes import Drawing, Line, Rect, String
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, Spacer

from app.services.report_service import BRAND, FONT_BODY, FONT_STRONG

PASS_COLOR = colors.HexColor("#16794f")
FAIL_COLOR = colors.HexColor("#a2302a")
GRID_COLOR = colors.HexColor("#dfe5ea")
AXIS_COLOR = colors.HexColor("#98a2b3")
TEXT_COLOR = colors.HexColor("#39424c")
ACCENT = colors.HexColor("#b54708")

#: Printed width of a chart, in millimetres: the A4 body is 182 mm wide.
CHART_WIDTH_MM = 176
CHART_HEIGHT_MM = 62


def _fmt(value: Any, places: int = 3) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if number != number or number in (float("inf"), float("-inf")):  # NaN / inf
        return "—"
    return f"{number:.{places}f}".rstrip("0").rstrip(".") or "0"


def _drawing(title: str, subtitle: str | None = None, *, height_mm: float | None = None) -> Drawing:
    drawing = Drawing(CHART_WIDTH_MM * mm, (height_mm or (CHART_HEIGHT_MM + 12)) * mm)
    drawing.add(String(0, drawing.height - 9, title, fontName=FONT_STRONG, fontSize=8.4, fillColor=BRAND))
    if subtitle:
        drawing.add(
            String(0, drawing.height - 19, subtitle, fontName=FONT_BODY, fontSize=6.8, fillColor=TEXT_COLOR)
        )
    return drawing


def _limit_lines(drawing: Drawing, ax, limits: list[float | None], *, colour=FAIL_COLOR) -> None:  # noqa: ANN001
    """Horizontal dashed lines at the acceptance limits, with their values printed."""
    for value in {round(v, 8) for v in limits if v is not None}:
        drawing.add(
            Line(
                ax.x,
                ax.value(value),
                ax.x + ax.width,
                ax.value(value),
                strokeColor=colour,
                strokeWidth=0.7,
                strokeDashArray=[2.2, 2.2],
            )
        )
        drawing.add(
            String(
                ax.x + ax.width + 1.5,
                ax.value(value) - 2,
                _fmt(value, 3),
                fontName=FONT_BODY,
                fontSize=6,
                fillColor=colour,
            )
        )


def bar_chart(
    *,
    title: str,
    subtitle: str | None,
    labels: list[str],
    series: list[tuple[str, list[float | None], Any]],
    limits: list[float | None] | None = None,
    unit: str = "",
    places: int = 3,
) -> Drawing:
    """A grouped bar chart: one group per reading, one bar per computed quantity."""
    drawing = _drawing(title, subtitle)
    chart = VerticalBarChart()
    chart.x = 34
    chart.y = 26
    chart.width = drawing.width - 78
    chart.height = drawing.height - 58
    chart.data = [list(values) for _name, values, _colour in series]
    chart.categoryAxis.categoryNames = labels
    chart.categoryAxis.labels.fontName = FONT_BODY
    chart.categoryAxis.labels.fontSize = 6.2
    chart.categoryAxis.labels.fillColor = TEXT_COLOR
    chart.categoryAxis.strokeColor = AXIS_COLOR
    chart.valueAxis.strokeColor = AXIS_COLOR
    chart.valueAxis.labels.fontName = FONT_BODY
    chart.valueAxis.labels.fontSize = 6.2
    chart.valueAxis.labels.fillColor = TEXT_COLOR
    chart.valueAxis.gridStrokeColor = GRID_COLOR
    chart.valueAxis.gridStrokeWidth = 0.4
    chart.valueAxis.visibleGrid = True
    # The window is fixed from the data *and the limits*, because ReportLab computes its
    # own axis range while drawing — after the limit lines have already been placed — and
    # an auto-scaled axis puts a dashed limit line outside the plot.
    all_values = [v for _n, values, _c in series for v in values if v is not None]
    all_values += [v for v in (limits or []) if v is not None]
    window_low, window_high = _axis_window(list(all_values))
    chart.valueAxis.valueMin = window_low
    chart.valueAxis.valueMax = window_high
    chart.barSpacing = 2
    chart.groupSpacing = 10
    for index, (_name, _values, colour) in enumerate(series):
        chart.bars[index].fillColor = colour
        chart.bars[index].strokeColor = None
    # A %accuracy of 0.1 against a ±2 % window is a sliver of a bar. The printed value
    # above each bar is what makes the figure readable without lying about its scale.
    chart.barLabelFormat = "%s"
    chart.barLabels.fontName = FONT_BODY
    chart.barLabels.fontSize = 5.4
    chart.barLabels.fillColor = TEXT_COLOR
    chart.barLabels.dy = 3
    # labelTextFormat must be a printf template: "%s %" would raise inside ReportLab at
    # draw time, so the unit is appended only when it is a word ("mL/min", "AU").
    if unit and unit.isalpha() or (unit and "/" in unit and "%" not in unit):
        chart.valueAxis.labelTextFormat = f"%s {unit}"
    else:
        chart.valueAxis.labelTextFormat = "%s"

    legend = Legend()
    legend.x = chart.x
    legend.y = drawing.height - 26
    legend.fontName = FONT_BODY
    legend.fontSize = 6.4
    legend.alignment = "right"
    legend.columnMaximum = 1
    legend.deltay = 8
    legend.colorNamePairs = [
        (colour, name) for name, _values, colour in series
    ]

    drawing.add(chart)
    if limits:
        for value in {round(v, 8) for v in limits if v is not None}:
            offset = chart.y + chart.height * _position(value, window_low, window_high)
            drawing.add(
                Line(
                    chart.x,
                    offset,
                    chart.x + chart.width,
                    offset,
                    strokeColor=FAIL_COLOR,
                    strokeWidth=0.7,
                    strokeDashArray=[2.4, 2.4],
                )
            )
            drawing.add(
                String(
                    chart.x + chart.width + 2,
                    offset - 2,
                    _fmt(value, 3),
                    fontName=FONT_BODY,
                    fontSize=6,
                    fillColor=FAIL_COLOR,
                )
            )
    drawing.add(legend)
    return drawing


def _axis_window(values: list[float | None]) -> tuple[float, float]:
    """A y window that always contains the data *and* every limit that will be drawn."""
    clean = [float(v) for v in values if v is not None]
    if not clean:
        return 0.0, 1.0
    low, high = min(clean), max(clean)
    if low == high:
        pad = abs(low) * 0.1 or 1.0
        return low - pad, high + pad
    pad = (high - low) * 0.15
    return low - pad, high + pad


def _position(value: float, low: float, high: float) -> float:
    span = (high - low) or 1.0
    return (value - low) / span


def line_chart(
    *,
    title: str,
    subtitle: str | None,
    series: list[tuple[str, list[tuple[float, float]], Any]],
    limits: list[float | None] | None = None,
    x_label: str = "",
    y_label: str = "",
) -> Drawing:
    """A control chart: every series carries its own (x, y) pairs.

    The flow-rate control chart plots thirty readings from three set points on one axis,
    each series on its *own* nominal. Sharing one x list would have plotted the second
    and third set points over the first ten positions — a chart that looks complete and
    says something false.
    """
    drawing = _drawing(title, subtitle)
    plot = LinePlot()
    plot.x = 40
    plot.y = 34
    plot.width = drawing.width - 96
    plot.height = drawing.height - 70
    plot.data = [
        [(x, y) for x, y in points if y is not None] for _name, points, _colour in series
    ]
    plot.joinedLines = 1
    for index, (_name, _points, colour) in enumerate(series):
        plot.lines[index].strokeColor = colour
        plot.lines[index].strokeWidth = 1.0
        # a visible marker: a control chart is read point by point, not as a trend line
        plot.lines[index].symbol = "circle"
        # ``symbolSize`` is not a LinePlot attribute in this ReportLab build; only the
        # attributes the class declares may be set, so the marker keeps its default size.
        plot.lines[index].fillColor = colour
    plot.xValueAxis.labelTextFormat = "%g"
    plot.xValueAxis.labels.fontName = FONT_BODY
    plot.xValueAxis.labels.fontSize = 6.2
    plot.xValueAxis.labels.fillColor = TEXT_COLOR
    plot.xValueAxis.strokeColor = AXIS_COLOR
    plot.yValueAxis.labelTextFormat = "%g"
    plot.yValueAxis.labels.fontName = FONT_BODY
    plot.yValueAxis.labels.fontSize = 6.2
    plot.yValueAxis.labels.fillColor = TEXT_COLOR
    plot.yValueAxis.strokeColor = AXIS_COLOR
    plot.yValueAxis.gridStrokeColor = GRID_COLOR
    plot.yValueAxis.visibleGrid = True

    all_values = [y for _n, points, _c in series for _x, y in points if y is not None]
    window_low, window_high = _axis_window(all_values + [v for v in (limits or []) if v is not None])
    plot.yValueAxis.valueMin = window_low
    plot.yValueAxis.valueMax = window_high

    if x_label:
        drawing.add(
            String(
                plot.x + plot.width / 2 - 14,
                plot.y - 24,
                x_label,
                fontName=FONT_BODY,
                fontSize=6.4,
                fillColor=TEXT_COLOR,
            )
        )
    if y_label:
        # above the axis and to its left; the legend starts further right so the two do
        # not share a line (they did, and the axis name was unreadable under the key)
        drawing.add(
            String(plot.x - 26, plot.y + plot.height + 4, y_label, fontName=FONT_BODY, fontSize=6.4, fillColor=TEXT_COLOR)
        )
    drawing.add(plot)
    if limits:
        labelled: list[float] = []
        for value in sorted({round(v, 8) for v in limits if v is not None}, reverse=True):
            yy = plot.y + plot.height * _position(value, window_low, window_high)
            drawing.add(
                Line(plot.x, yy, plot.x + plot.width, yy, strokeColor=FAIL_COLOR, strokeWidth=0.7, strokeDashArray=[2.4, 2.4])
            )
            # A ±2 % band puts the two bounds of a set point eight points apart; printing
            # both numbers there overlaps them into a smudge. The line is always drawn,
            # the number is printed only where there is room for it.
            if any(abs(yy - previous) < 7.5 for previous in labelled):
                continue
            labelled.append(yy)
            drawing.add(
                String(plot.x + plot.width + 2, yy - 2, _fmt(value, 3), fontName=FONT_BODY, fontSize=6, fillColor=FAIL_COLOR)
            )
    if len(series) > 1:
        legend = Legend()
        legend.x = plot.x + 30
        legend.y = drawing.height - 26
        legend.fontName = FONT_BODY
        legend.fontSize = 6.4
        legend.columnMaximum = 1
        legend.deltay = 8
        legend.colorNamePairs = [(colour, name) for name, _points, colour in series]
        drawing.add(legend)
    return drawing


def gauge(
    *,
    title: str,
    subtitle: str | None,
    measured: float,
    nominal: float | None,
    lower: float | None,
    upper: float | None,
    unit: str,
) -> Drawing:
    """One measured value on a ruler that shows where its accepted band is.

    Used for the one-number tests (wavelength deviation, lamp energy, oven stability): a
    bar chart of one bar says nothing a table cell does not, whereas a ruler shows whether
    the value sits in the middle of its band or against its edge.

    A one-sided limit (≤ x, ≥ x) is drawn as a band that runs to the end of the scale it
    constrains, not as a band from the measurement itself — otherwise a conforming value
    would always appear to sit at the very edge of a green zone, which is the opposite of
    what the figure is for.
    """
    # a ruler needs a fraction of the height of a chart: 34 mm instead of 74 mm, so four
    # of them share a page instead of two and the page is not mostly white space
    drawing = _drawing(title, subtitle, height_mm=34)
    left = 34
    width = drawing.width - 92
    y = drawing.height / 2 - 20
    bar_height = 15

    # the window: always contains the measurement and the limit that governs it
    candidates = [measured] + [v for v in (lower, upper) if v is not None]
    low = min(candidates)
    high = max(candidates)
    if high == low:
        high = low + (abs(low) * 0.1 or 1.0)
    pad = (high - low) * 0.18
    window_low, window_high = low - pad, high + pad
    if upper is not None and lower is None and window_low < 0 <= low:
        window_low = 0.0  # a "≤" limit is measured from zero, not from an arbitrary floor

    def place(value: float) -> float:
        return left + width * (value - window_low) / (window_high - window_low)

    drawing.add(Rect(left, y, width, bar_height, fillColor=colors.HexColor("#f6f8fa"), strokeColor=GRID_COLOR, strokeWidth=0.5))

    band_from = place(lower) if lower is not None else left
    band_to = place(upper) if upper is not None else left + width
    drawing.add(
        Rect(
            band_from,
            y,
            max(band_to - band_from, 1.2),
            bar_height,
            fillColor=colors.HexColor("#dcefe5"),
            strokeColor=PASS_COLOR,
            strokeWidth=0.6,
        )
    )
    # the limit line(s), so the edge of the band is unambiguous even in a photocopy
    for value in (lower, upper):
        if value is None:
            continue
        drawing.add(Line(place(value), y - 3, place(value), y + bar_height + 3, strokeColor=FAIL_COLOR, strokeWidth=0.8))
        drawing.add(
            String(
                place(value) - 8,
                y - 12,
                _fmt(value, 3),
                fontName=FONT_BODY,
                fontSize=6,
                fillColor=FAIL_COLOR,
            )
        )

    marker = place(measured)
    drawing.add(Line(marker, y - 5, marker, y + bar_height + 5, strokeColor=BRAND, strokeWidth=1.8))
    label = f"{_fmt(measured, 3)} {unit}".strip()
    # keep the value label inside the ruler; a marker near the right edge printed it off-page
    label_x = min(max(marker - 6, left), left + width - 26)
    drawing.add(String(label_x, y + bar_height + 9, label, fontName=FONT_STRONG, fontSize=7, fillColor=BRAND))

    if nominal is not None:
        drawing.add(
            String(
                left,
                y + bar_height + 9,
                f"nominal {_fmt(nominal, 3)}",
                fontName=FONT_BODY,
                fontSize=6,
                fillColor=AXIS_COLOR,
            )
        )
    drawing.add(String(left, y - 12, _fmt(window_low, 3), fontName=FONT_BODY, fontSize=6, fillColor=AXIS_COLOR))
    drawing.add(
        String(left + width - 18, y - 12, _fmt(window_high, 3), fontName=FONT_BODY, fontSize=6, fillColor=AXIS_COLOR)
    )
    return drawing


#: How much vertical room the charts may take on one page. The body of an A4 sheet is
#: 269 mm; leaving ~120 mm free means the conformity statement and the signature block —
#: which are kept together on purpose — still fit under the last figure instead of being
#: pushed onto a page of their own.
CHARTS_PER_PAGE_MM = 232.0


def chart_pages(
    *,
    st: dict[str, ParagraphStyle],
    charts: list[Drawing],
    title: str,
    note: str,
) -> list[Any]:
    """Wrap the drawings as flowables, packed by their real height.

    The laboratory asked for the charts on their own page, after the page of values, which
    is what this does — but a page per *two* figures wastes a sheet when the figures are
    rulers rather than full charts. Each drawing reports its own height, so the packing is
    by measurement rather than by a fixed count, and a page break is inserted only when the
    next figure would not fit.
    """
    if not charts:
        return []
    story: list[Any] = [Paragraph(title, st["h2"])]
    used = 0.0
    first = True
    for item in charts:
        # callers may pass either a Drawing or an already-wrapped flowable; the height is
        # read from whichever carries it
        drawing = getattr(item, "drawing", item)
        height_mm = float(getattr(drawing, "height", 0)) / mm
        if not first and used + height_mm > CHARTS_PER_PAGE_MM:
            story.append(PageBreak())
            story.append(Paragraph(title + " (continued)", st["h2"]))
            used = 0.0
        elif not first:
            story.append(Spacer(1, 3 * mm))
            used += 3
        story.append(drawing_flowable(drawing))
        # ``drawing_flowable`` wraps a Drawing; the loop keeps the Drawing for its height
        # and hands the wrapper to platypus, so ``drawing`` here is still the Drawing.
        used += height_mm
        first = False
    if note:
        story.append(Spacer(1, 2.5 * mm))
        story.append(Paragraph(note, st["note"]))
    return story


def drawing_flowable(drawing: Drawing):  # noqa: ANN201 - reportlab type
    """The flowable ReportLab needs to place a Drawing in a platypus story."""
    return renderPDF.GraphicsFlowable(drawing)


def ensure_series_png(*_args, **_kwargs):  # pragma: no cover - intentionally unsupported
    """Rasterising is not supported: charts ship as vectors. Kept as an explicit refusal."""
    raise NotImplementedError(
        "Chart images are embedded as PDF vectors; rasterisation is not part of this build."
    )

"""Which charts a given test's certificate carries, and from what.

``certificate_charts`` knows how to draw; this module knows *what* to draw for each of
the twenty tests, using only what was stored with the result:

* ``raw_inputs_jsonb`` — the readings exactly as entered (scalars, or lists for the
  series tests);
* ``calculated_outputs_jsonb`` — every formula the engine evaluated (means, SDs, %RSD,
  slopes, deviations);
* ``metric_evaluations_jsonb`` — each metric with the limit that was applied and the
  verdict, including the printed limit text.

Nothing else is consulted, so the figures on a certificate cannot show a number that is
not also on its table. A test with no numeric content (a leak-sensor check, a
"pressure limiter PASS" acknowledgement) produces no chart at all rather than a
decorative empty frame, and the caller prints the value tables alone.
"""

from __future__ import annotations

from typing import Any

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle

from app.services.certificate_charts import (
    ACCENT,
    BRAND,
    FAIL_COLOR,
    PASS_COLOR,
    bar_chart,
    gauge,
    line_chart,
)

#: Colour per series index, in the order used across the application.
PALETTE = [BRAND, ACCENT, colors.HexColor("#1d4ed8"), colors.HexColor("#6b7280")]


def _numeric(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(str(value))
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _series_values(raw: Any) -> list[float | None]:
    if isinstance(raw, list):
        return [_numeric(item) for item in raw]
    single = _numeric(raw)
    return [single] if single is not None else []


def _limit_bounds(metric: dict[str, Any]) -> tuple[float | None, float | None]:
    """The applied limit as numbers, from the structured fields the engine stored."""
    low = _numeric(metric.get("min_value"))
    high = _numeric(metric.get("max_value"))
    if low is not None or high is not None:
        return low, high
    # older rows carry only the printed form ("≤ 2.0 %"); read the first number out of it
    text = str(metric.get("limit_text") or "")
    import re

    numbers = [float(match) for match in re.findall(r"-?\d+(?:\.\d+)?", text)]
    if not numbers:
        return None, None
    if "…" in text or "between" in text.lower():
        return (numbers[0], numbers[1]) if len(numbers) > 1 else (None, numbers[0])
    if "≥" in text:
        return numbers[0], None
    return None, numbers[0]


def build_test_charts(
    *,
    test: dict[str, Any],
    chart: str,
    outputs: dict[str, Any],
    metrics: list[dict[str, Any]],
    raw: dict[str, Any],
    lang: str = "en",
) -> list[Any]:
    """Return the drawings this test's certificate should carry, in reading order."""
    charts: list[Any] = []
    code = str(test.get("code", ""))
    name = test.get("name_en", code)

    if chart == "flow":
        # three set points × ten replicates: the accuracy curve and the control chart.
        nominals = [1.0, 1.5, 2.0]
        keys = ["p1000", "p1500", "p2000"]
        accuracies = [_numeric(outputs.get(f"acc_{key}")) for key in keys]
        rsds = [_numeric(outputs.get(f"rsd_{key}")) for key in keys]
        accuracy_limit = None
        for metric in metrics:
            if str(metric.get("metric_key")) == "max_abs_error" and accuracy_limit is None:
                _low, accuracy_limit = _limit_bounds(metric)
        band = abs(accuracy_limit or 2.0)
        charts.append(
            bar_chart(
                title=f"{code} · Accuracy and %RSD by set point",
                subtitle=f"Nominal flow 1.000 / 1.500 / 2.000 mL/min · accepted ±{band:g} % accuracy, %RSD ≤ 1.0 %",
                labels=[f"{nominal:g} mL/min" for nominal in nominals],
                series=[
                    ("%accuracy", accuracies, BRAND),
                    ("%RSD", rsds, ACCENT),
                ],
                limits=[band, -band],
                unit="%",
            )
        )
        # One series per set point, each on its own nominal, so the acceptance band of a
        # set point is a flat segment the reader can follow instead of one global band
        # that fits none of them. The x axis continues across the three rows: reading 11
        # is the first replicate of 1.500 mL/min, which is how the bench numbered them.
        points_series: list[tuple[str, list[tuple[float, float]], Any]] = []
        bands: list[float | None] = []
        cursor = 0
        for position, (nominal, key) in enumerate(zip(nominals, ("flow_p1000", "flow_p1500", "flow_p2000"))):
            values = _series_values(raw.get(key))
            if not values:
                continue
            points_series.append(
                (
                    f"{nominal:g} mL/min",
                    [(float(cursor + index + 1), float(value)) for index, value in enumerate(values) if value is not None],
                    PALETTE[position % len(PALETTE)],
                )
            )
            bands.append(nominal * (1 + band / 100))
            bands.append(nominal * (1 - band / 100))
            cursor += len(values)
        if points_series:
            total = cursor
            charts.append(
                line_chart(
                    title=f"{code} · Replicate control chart",
                    subtitle=(
                        f"{total} readings in run order · each set point plotted on its own nominal "
                        "with its acceptance band (dashed)"
                    ),
                    series=points_series,
                    limits=bands,
                    x_label="reading #",
                    y_label="mL/min",
                )
            )
        return charts

    if chart == "gradient":
        levels = ["10", "50", "90", "100"]
        actual = [_numeric(outputs.get(f"actual_{level}")) for level in levels]
        deviation = [_numeric(outputs.get(f"dev_{level}")) for level in levels]
        charts.append(
            bar_chart(
                title=f"{code} · Gradient proportioning accuracy",
                subtitle="Measured proportion at each programmed step",
                labels=[f"{level} %" for level in levels],
                series=[("measured %", actual, BRAND), ("deviation %", deviation, ACCENT)],
                unit="%",
            )
        )
        return charts

    if chart == "linearity":
        xs = _series_values(raw.get("concs")) or _series_values(raw.get("volumes"))
        ys = _series_values(raw.get("heights")) or _series_values(raw.get("linearity_areas"))
        xs = [value for value in xs if value is not None]
        ys = [value for value in ys if value is not None]
        if len(xs) >= 2 and len(ys) >= 2:
            slope = _numeric(outputs.get("slope")) or _numeric(outputs.get("ols_slope"))
            intercept = _numeric(outputs.get("intercept")) or _numeric(outputs.get("ols_intercept"))
            title = f"{code} · Linearity"
            subtitle = "Measured response against the injected level"
            if slope is not None:
                subtitle += f" · fitted y = {slope:.6g}x {'+' if (intercept or 0) >= 0 else '−'} {abs(intercept or 0):.4g}"
            series: list[tuple[str, list[tuple[float, float]], Any]] = [
                ("measured", list(zip(xs, ys)), BRAND),
            ]
            if slope is not None:
                fitted = [slope * x + (intercept or 0.0) for x in xs]
                series.append(("OLS fit", list(zip(xs, fitted)), ACCENT))
            charts.append(
                line_chart(
                    title=title,
                    subtitle=subtitle,
                    series=series,
                    x_label="level",
                    y_label="response",
                )
            )
        return charts

    if chart == "repeatability":
        rts = _series_values(raw.get("rt_values"))
        areas = _series_values(raw.get("areas"))
        baseline = _series_values(raw.get("baseline"))

        def numbered(values: list[float | None]) -> list[tuple[float, float]]:
            return [
                (float(index + 1), float(value))
                for index, value in enumerate(values)
                if value is not None
            ]

        if rts:
            charts.append(
                line_chart(
                    title=f"{code} · Retention time by injection",
                    subtitle="Each point is one injection; a drift here is a pump or column problem",
                    series=[("RT (min)", numbered(rts), BRAND)],
                    x_label="injection",
                    y_label="min",
                )
            )
        if areas:
            charts.append(
                line_chart(
                    title=f"{code} · Peak area by injection",
                    subtitle="Repeatability of the detector response",
                    series=[("area", numbered(areas), ACCENT)],
                    x_label="injection",
                    y_label="area",
                )
            )
        if baseline:
            mean = sum(value for value in baseline if value is not None) / max(
                1, len([value for value in baseline if value is not None])
            )
            spread = _numeric(outputs.get("baseline_sd")) or _numeric(outputs.get("sd_baseline"))
            charts.append(
                line_chart(
                    title=f"{code} · Baseline over 30-second segments",
                    subtitle="Noise and drift of the UV baseline · mean and ±2 SD if recorded",
                    series=[("mAU", numbered(baseline), BRAND)],
                    limits=[mean, mean + 2 * spread, mean - 2 * spread] if spread else [mean],
                    x_label="segment",
                    y_label="mAU",
                )
            )
        return charts

    if chart == "spectrum":
        pairs = [
            ("peak 205 nm", _numeric(outputs.get("peak_205"))),
            ("valley 245 nm", _numeric(outputs.get("valley_245"))),
            ("peak 273 nm", _numeric(outputs.get("peak_273"))),
        ]
        present = [(label, value) for label, value in pairs if value is not None]
        if present:
            charts.append(
                bar_chart(
                    title=f"{code} · Spectrum landmarks",
                    subtitle="Detected maxima and minimum of the caffeine scan",
                    labels=[label for label, _value in present],
                    series=[("AU", [value for _label, value in present], BRAND)],
                    unit="AU",
                )
            )
        return charts

    if chart == "temperature":
        categories = ["set", "display", "reference"]
        values = [
            _numeric(outputs.get("t_set")),
            _numeric(outputs.get("t_display")),
            _numeric(outputs.get("t_ref_corrected")),
        ]
        if any(value is not None for value in values):
            charts.append(
                bar_chart(
                    title=f"{code} · Temperature: set, indicated and reference",
                    subtitle="The reference has been corrected with its calibration certificate",
                    labels=categories,
                    series=[("°C", values, BRAND)],
                    unit="°C",
                )
            )
        return charts

    # Everything else is judged on one number per metric: draw each metric against its
    # own accepted band, one gauge per metric, so a reader sees how close to the edge the
    # measurement sits rather than only whether it passed.
    for metric in metrics:
        value = _numeric(metric.get("value"))
        if value is None:
            continue
        low, high = _limit_bounds(metric)
        if low is None and high is None:
            continue
        key = str(metric.get("metric_key", ""))
        unit = str(metric.get("unit") or "")
        status = str(metric.get("status") or "")
        charts.append(
            gauge(
                title=f"{code} · {key}",
                subtitle=f"{status} · applied limit {metric.get('limit_text') or '—'}",
                measured=value,
                # a nominal is printed only when the acceptance is a two-sided band; a
                # "≤" limit has no centre to sit in
                nominal=(low + high) / 2 if low is not None and high is not None else None,
                lower=low,
                upper=high,
                unit=unit,
            )
        )

    # A "share of the applied limit" summary makes the metrics comparable even when they
    # carry different units (nm, mV, MPa, mAU), which is the same idea the screen uses.
    shares = []
    labels = []
    for metric in metrics:
        value = _numeric(metric.get("value"))
        low, high = _limit_bounds(metric)
        # Only an *upper* bound can be read as "how much of the limit was used". A ≥ limit
        # (lamp energy, for instance) is inverted: 1850 mV against a floor of 800 mV would
        # plot at 231 % and read as a failure when it is the most conforming value on the
        # sheet. Those metrics are shown as rulers above instead.
        bound = high if high not in (None, 0) else None
        if value is None or not bound:
            continue
        labels.append(str(metric.get("metric_key")))
        shares.append(round(abs(value) / abs(bound) * 100, 2))
    if len(labels) >= 2:
        charts.append(
            bar_chart(
                title=f"{code} · Each metric as a share of its applied limit",
                subtitle="100 % is the acceptance limit; anything above it is a failure",
                labels=labels,
                series=[("% of limit", shares, BRAND)],
                limits=[100.0],
                unit="%",
            )
        )
    return charts


def chart_note(has_charts: bool) -> str:
    if not has_charts:
        return ""
    return (
        "Charts are drawn from the stored readings and computed results of this test "
        "(raw_inputs_jsonb / calculated_outputs_jsonb). Dashed lines mark the acceptance "
        "limit that was applied to the measurement; they are not fitted to the data."
    )

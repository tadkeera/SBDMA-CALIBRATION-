"""Flow-rate (T02) evaluation — the arithmetic behind the dedicated page.

The laboratory's flow-rate test is entered as **ten replicate flows at each of three set
points** (1.000, 1.500 and 2.000 mL/min, thirty numbers in total). That is a different shape
from the rest of the protocol, and the page that collects it needs three things the generic
screen does not provide:

* the reference limits for each set point, expressed both as a percentage and as an actual
  mL/min band (0.980–1.020 for the 1.000 mL/min point, and so on) — the analyst standing at
  the pump checks a measured value against a band, not against a percentage;
* statistics per set point (mean, sample SD, %RSD, %accuracy) computed on *every keystroke*,
  so a drifting run is visible before thirty values have been typed;
* the same numbers computed again on the server, because a browser preview is a convenience
  and the stored verdict has to be defensible.

This module is pure: Decimal arithmetic, no I/O, no framework. The API endpoint, the
certificate and the unit tests all call the same functions, so there is exactly one
definition of "%RSD" in the system.

Edge cases that matter in a real laboratory:
  * one value typed so far — the mean and %accuracy are meaningful, SD and %RSD are not
    (a single replicate has no spread). They are returned as ``None`` and rendered "—",
    never as ``NaN`` and never as a division by zero;
  * a zero mean (a completely blocked pump) — %RSD is undefined rather than infinite;
  * empty cells — ten boxes exist but the analyst may have filled seven; the statistics are
    computed on the values that exist, and ``complete`` says whether all thirty are in.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

#: The three set points the protocol fixes, in mL/min. Kept here as well as in the protocol
#: blueprint because the page needs the *nominal* value to compute accuracy, and the nominal
#: is part of the method, not of the readings.
SET_POINTS: tuple[Decimal, ...] = (Decimal("1.000"), Decimal("1.500"), Decimal("2.000"))
READINGS_PER_SET_POINT = 10
#: Accepted accuracy, in percent, applied symmetrically around the nominal flow.
ACCURACY_PCT = Decimal("2.0")
#: Accepted relative standard deviation across the ten replicates of one set point.
MAX_RSD_PCT = Decimal("1.0")


def _dec(value: Any) -> Decimal | None:
    """Coerce one entered reading to Decimal, or None when the cell is empty/invalid."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        number = Decimal(text)
    except Exception:
        return None
    if not number.is_finite():
        return None
    return number


def mean(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    return sum(values, Decimal(0)) / Decimal(len(values))


def sample_sd(values: list[Decimal]) -> Decimal | None:
    """Sample standard deviation (n − 1). Undefined below two points, by design."""
    if len(values) < 2:
        return None
    centre = mean(values)
    assert centre is not None
    variance = sum(((v - centre) ** 2 for v in values), Decimal(0)) / Decimal(len(values) - 1)
    return variance.sqrt()


def rsd(values: list[Decimal]) -> Decimal | None:
    """%RSD = SD / mean × 100. Zero mean and single replicate have no %RSD."""
    centre = mean(values)
    spread = sample_sd(values)
    if centre is None or spread is None or centre == 0:
        return None
    return spread / centre * Decimal(100)


def accuracy(measured_mean: Decimal | None, nominal: Decimal) -> Decimal | None:
    """%Accuracy of a mean flow against its set point: (mean − nominal)/nominal × 100."""
    if measured_mean is None or nominal == 0:
        return None
    return (measured_mean - nominal) / nominal * Decimal(100)


@dataclass(slots=True)
class SetPointResult:
    index: int
    nominal: Decimal
    readings: list[Decimal | None]
    count: int
    complete: bool
    mean: Decimal | None
    sd: Decimal | None
    rsd_pct: Decimal | None
    accuracy_pct: Decimal | None
    lower_limit: Decimal
    upper_limit: Decimal
    accuracy_status: str
    rsd_status: str
    status: str

    def as_dict(self) -> dict[str, Any]:
        def shown(value: Decimal | None, places: int) -> str | None:
            return None if value is None else str(value.quantize(Decimal(1).scaleb(-places)))

        return {
            "index": self.index,
            "nominal": str(self.nominal),
            "readings": [None if r is None else str(r) for r in self.readings],
            "count": self.count,
            "complete": self.complete,
            "mean": shown(self.mean, 4),
            "sd": shown(self.sd, 5),
            "rsd_pct": shown(self.rsd_pct, 3),
            "accuracy_pct": shown(self.accuracy_pct, 3),
            "lower_limit": str(self.lower_limit),
            "upper_limit": str(self.upper_limit),
            "accuracy_status": self.accuracy_status,
            "rsd_status": self.rsd_status,
            "status": self.status,
        }


@dataclass(slots=True)
class FlowRateEvaluation:
    set_points: list[SetPointResult]
    overall: str
    complete: bool
    max_abs_accuracy: Decimal | None
    max_rsd: Decimal | None
    accuracy_limit: Decimal
    rsd_limit: Decimal

    def as_dict(self) -> dict[str, Any]:
        def shown(value: Decimal | None, places: int) -> str | None:
            return None if value is None else str(value.quantize(Decimal(1).scaleb(-places)))

        return {
            "set_points": [sp.as_dict() for sp in self.set_points],
            "overall": self.overall,
            "complete": self.complete,
            "max_abs_accuracy": shown(self.max_abs_accuracy, 3),
            "max_rsd": shown(self.max_rsd, 3),
            "accuracy_limit": str(self.accuracy_limit),
            "rsd_limit": str(self.rsd_limit),
            "acceptance": {
                "accuracy_pct": str(self.accuracy_limit),
                "rsd_pct": str(self.rsd_limit),
                "accuracy_band": f"{Decimal(100) - self.accuracy_limit}–{Decimal(100) + self.accuracy_limit}",
            },
        }


def evaluate_flow_rate(
    readings: list[list[Any]],
    *,
    accuracy_limit: Decimal = ACCURACY_PCT,
    rsd_limit: Decimal = MAX_RSD_PCT,
) -> FlowRateEvaluation:
    """Evaluate three rows of ten readings.

    ``readings`` is outer-indexed by set point (0 → 1.000 mL/min, 1 → 1.500, 2 → 2.000) and
    inner-indexed by replicate. Rows may be shorter than ten or contain empty cells: the
    statistics use what is present and ``complete`` reports the shortfall.
    """
    results: list[SetPointResult] = []
    all_complete = True

    for index, nominal in enumerate(SET_POINTS):
        row = readings[index] if index < len(readings) else []
        cells = [_dec(v) for v in list(row)[:READINGS_PER_SET_POINT]]
        cells.extend([None] * (READINGS_PER_SET_POINT - len(cells)))
        values = [v for v in cells if v is not None]

        average = mean(values)
        spread = sample_sd(values)
        relative = rsd(values)
        acc = accuracy(average, nominal)

        upper = nominal * (Decimal(1) + accuracy_limit / Decimal(100))
        lower = nominal * (Decimal(1) - accuracy_limit / Decimal(100))

        # A set point with no readings is INCOMPLETE, not a failure: nothing has been
        # measured yet, and calling that a FAIL would put a red cell on an untouched page.
        if not values:
            accuracy_status = rsd_status = status = "INCOMPLETE"
        elif acc is None:
            accuracy_status = "INCOMPLETE"
            rsd_status = "PASS" if relative is None else ("PASS" if relative <= rsd_limit else "FAIL")
            status = "INCOMPLETE"
        else:
            accuracy_status = "PASS" if abs(acc) <= accuracy_limit else "FAIL"
            if relative is None:
                rsd_status = "INCOMPLETE"
            else:
                rsd_status = "PASS" if relative <= rsd_limit else "FAIL"
            if "FAIL" in (accuracy_status, rsd_status):
                status = "FAIL"
            elif "INCOMPLETE" in (accuracy_status, rsd_status):
                # one value in: accuracy decided, precision cannot be — the row is neither
                # certified nor failed, it is still being filled in
                status = "INCOMPLETE"
            else:
                status = "PASS"

        complete = len(values) == READINGS_PER_SET_POINT
        all_complete = all_complete and complete

        results.append(
            SetPointResult(
                index=index,
                nominal=nominal,
                readings=cells,
                count=len(values),
                complete=complete,
                mean=average,
                sd=spread,
                rsd_pct=relative,
                accuracy_pct=acc,
                lower_limit=lower.quantize(Decimal("0.001")),
                upper_limit=upper.quantize(Decimal("0.001")),
                accuracy_status=accuracy_status,
                rsd_status=rsd_status,
                status=status,
            )
        )

    accuracies = [abs(sp.accuracy_pct) for sp in results if sp.accuracy_pct is not None]
    rsds = [sp.rsd_pct for sp in results if sp.rsd_pct is not None]
    max_abs_accuracy = max(accuracies) if accuracies else None
    max_rsd = max(rsds) if rsds else None

    statuses = [sp.status for sp in results]
    if "FAIL" in statuses:
        overall = "FAIL"
    elif all(s == "PASS" for s in statuses):
        overall = "PASS"
    else:
        overall = "INCOMPLETE"

    return FlowRateEvaluation(
        set_points=results,
        overall=overall,
        complete=all_complete,
        max_abs_accuracy=max_abs_accuracy,
        max_rsd=max_rsd,
        accuracy_limit=accuracy_limit,
        rsd_limit=rsd_limit,
    )


def to_payload(readings: list[list[Any]]) -> dict[str, list[float]]:
    """Shape the grid for the generic engine: three protocol series fields.

    The generic execution endpoint accepts ``raw_inputs[test_code]`` as a mapping of field
    key to a list of numbers, so the dedicated page hands the server the same structure any
    other screen would — one code path evaluates a T02 run, whichever page produced it.
    """
    keys = ("flow_p1000", "flow_p1500", "flow_p2000")
    payload: dict[str, list[float]] = {}
    for position, key in enumerate(keys):
        row = readings[position] if position < len(readings) else []
        values = [_dec(v) for v in list(row)[:READINGS_PER_SET_POINT]]
        payload[key] = [float(v) for v in values if v is not None]
    return payload

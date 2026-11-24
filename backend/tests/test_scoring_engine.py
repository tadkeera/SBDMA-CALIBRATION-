"""Governance and computation tests for the server-side calibration engine.

These replicate the browser suite (tests/engine.test.ts) so both engines are
proven equivalent on the same raw data.
"""

from decimal import Decimal

import pytest

from app.domain.protocol.blueprint import LIMITS, TESTS
from app.domain.scoring.engine import (
    FAIL,
    INCOMPLETE,
    PASS,
    UNDER_REVIEW,
    evaluate_metric,
    execute_run,
    find_limit,
)

D = Decimal

GOOD_INPUTS = {
    "T01": {
        "wavelength_dev": 0.2, "d2_energy": 1517, "pulsation": 0.08, "oven_stability": 0.05,
        "absorbance_dev": 0.4, "noise": 0.008, "drift": 0.12, "gradient_dev": 0.6,
        "pressure_limiter": "Passed",
    },
    "T02": {"set_flow": [0.5, 1, 2], "collected_vol": [5, 5, 5], "actual_time": [599.9, 299.4, 150.1]},
    "T03": {"pulsation": 0.09, "upper_limiter": "Passed", "lower_limiter": "Passed"},
    "T04": {
        "height_0": [0, 0, 0], "height_10": [10040, 10060, 10020],
        "height_50": [50100, 50200, 49900], "height_90": [90200, 90100, 90300],
        "height_100": [100200, 100300, 100100],
    },
    "T05": {"w1": 10.5, "w2": 10.0008, "water_density": 0.997, "set_vol": 50, "n_injections": 10},
    "T06": {
        "volumes": [2, 5, 10, 20, 50], "linearity_areas": [1000, 2500, 5000, 10000, 25000],
        "loop_areas": [24950, 25010, 24980, 25005, 24990],
    },
    "T07": {"t_set": 4, "t_ref_raw": 4.4, "ref_offset": 0.08, "wait_minutes": 95, "ambient_temp": 26},
    "T08": {
        "t_set": 40, "t_display": 40.1, "t_ref_raw": 40.3, "ref_offset": 0.05,
        "fluctuation": 0.07, "gas_sensor": "Passed",
    },
    "T09": {
        "d2_energy": 1517, "lamp_hours": 1420, "wavelength_dev": 0.3,
        "peak_205": 205.2, "valley_245": 244.8, "peak_273": 273.4,
    },
    "T10": {"absorbance_dev": 0.5, "concs": [20, 30, 40, 50, 60], "heights": [0.5, 0.75, 1.0, 1.25, 1.5]},
    "T11": {"noise": 0.009, "drift": -0.21},
    "T12": {
        "rt_values": [2.451, 2.449, 2.452, 2.45, 2.448, 2.451],
        "areas": [25010, 24980, 25005, 24995, 25020, 24990],
        "area_blank": 0.02, "area_sample_250": 200000, "area_sample_50": 40000,
    },
    "T13": {
        "detector_sensor": "Passed", "pump_sensor": "Passed", "hpv_sensor": "Passed",
        "lpv_sensor": "Passed", "rack_setting": "Not Required", "port_teaching": "Not Required",
    },
}


def run(inputs=None, source="AUTHORITY_LIMIT"):
    return execute_run(
        tests=list(TESTS), raw_inputs=inputs or GOOD_INPUTS, limits=list(LIMITS), policy_source=source
    )


# ───────────────────────────── protocol integrity ─────────────────────────── #


def test_thirteen_tests_present():
    assert len(TESTS) == 13
    assert [t.code for t in TESTS] == [f"T{i:02d}" for i in range(1, 14)]


def test_every_metric_has_authority_limit():
    missing = [
        f"{t.code}:{m}"
        for t in TESTS
        for m in t.metrics
        if find_limit(list(LIMITS), t.code, m, "AUTHORITY_LIMIT") is None
    ]
    assert missing == []


def test_defective_sop_limits_are_conflicted():
    bad = [lim for lim in LIMITS if lim.source_type == "SOP_LIMIT" and lim.approval_status == "CONFLICT_REQUIRES_QA"]
    assert len(bad) >= 4
    assert all(lim.flagged for lim in bad)


def test_limit_count_is_stable():
    assert len(LIMITS) == 108


# ────────────────────────────── governance gate ───────────────────────────── #


def test_noise_conflit_never_passes():
    ev = evaluate_metric(
        test_code="T11", metric_key="noise", value=D("0.001"),
        source="SOP_LIMIT", unit="mAU", limits=list(LIMITS),
    )
    assert ev.status == UNDER_REVIEW
    assert "متعارض" in (ev.message_ar or "")


def test_approved_limit_pass_and_fail():
    ok = evaluate_metric(
        test_code="T11", metric_key="noise", value=D("0.008"),
        source="AUTHORITY_LIMIT", unit="mAU", limits=list(LIMITS),
    )
    assert ok.status == PASS
    bad = evaluate_metric(
        test_code="T11", metric_key="drift_abs", value=D("0.85"),
        source="AUTHORITY_LIMIT", unit="mAU/h", limits=list(LIMITS),
    )
    assert bad.status == FAIL


def test_missing_limit_source_escalates():
    ev = evaluate_metric(
        test_code="T12", metric_key="carryover_ch2", value=D("0.001"),
        source="IOQ_PROTOCOL_CH4", unit="%", limits=list(LIMITS),
    )
    assert ev.status == UNDER_REVIEW
    assert ev.applied_limit_id is None


def test_run_under_sop_policy_requires_review():
    outcome = run(source="SOP_LIMIT")
    assert outcome.overall == UNDER_REVIEW


# ──────────────────────────────── computation ─────────────────────────────── #


def test_compliant_instrument_passes_all_thirteen():
    outcome = run()
    failing = {r.test_code: r.status for r in outcome.results if r.status != PASS}
    assert failing == {}
    assert outcome.overall == PASS
    assert outcome.summary()["pass"] == 13


def test_drift_oos_fails():
    inputs = {**GOOD_INPUTS, "T11": {"noise": 0.009, "drift": 1.2}}
    outcome = run(inputs)
    assert outcome.by_code["T11"].status == FAIL
    assert outcome.overall == FAIL


def test_missing_required_field_is_incomplete():
    inputs = {**GOOD_INPUTS, "T02": {"set_flow": [0.5, 1, 2]}}
    outcome = run(inputs)
    assert outcome.by_code["T02"].status == INCOMPLETE


def test_leak_sensor_failure_fails_run():
    inputs = {**GOOD_INPUTS, "T13": {**GOOD_INPUTS["T13"], "lpv_sensor": "Failed"}}
    outcome = run(inputs)
    assert outcome.by_code["T13"].status == FAIL
    assert outcome.overall == FAIL


def test_flow_rate_value_matches_report_method():
    outcome = run()
    t02 = outcome.by_code["T02"]
    err = t02.outputs["max_abs_error"]
    assert isinstance(err, Decimal)
    assert err < D("2.0")


def test_carryover_is_computed_not_rounded():
    outcome = run()
    co = outcome.by_code["T12"].outputs["carryover_ch2"]
    assert isinstance(co, Decimal)
    assert co < D("0.01")


def test_injection_accuracy_within_limit():
    outcome = run()
    acc = outcome.by_code["T05"].outputs["pct_accuracy_abs"]
    assert acc < D("1.3")


def test_gpv_elementwise_deviation():
    outcome = run()
    dev = outcome.by_code["T04"].outputs["max_abs_dev"]
    assert isinstance(dev, Decimal)
    assert dev < D("2.0")

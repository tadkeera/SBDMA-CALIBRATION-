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

# The reference dataset is authored once, next to the API suite, and shared with the
# browser tests and the E2E run (e2e/fixtures/compliant_inputs.json). Two hand-kept
# copies of "a compliant instrument" is how the two engines would silently diverge.
from tests.test_api_runs import COMPLIANT_INPUTS as GOOD_INPUTS  # noqa: E402


def run(inputs=None, source="AUTHORITY_LIMIT"):
    return execute_run(
        tests=list(TESTS), raw_inputs=inputs or GOOD_INPUTS, limits=list(LIMITS), policy_source=source
    )


# ───────────────────────────── protocol integrity ─────────────────────────── #


def test_twenty_tests_present():
    """Protocol v2.0.0 spans 20 tests; the numbering must be gapless."""
    assert len(TESTS) == 20
    assert [t.code for t in TESTS] == [f"T{i:02d}" for i in range(1, 21)]


def test_every_metric_has_authority_limit():
    missing = [
        f"{t.code}:{m}"
        for t in TESTS
        for m in t.metrics
        if find_limit(list(LIMITS), t.code, m, "AUTHORITY_LIMIT") is None
    ]
    assert missing == []


def test_the_looser_ioq_carryover_limit_is_conflicted():
    """v2.0.0 keeps exactly one conflict: the iOQ carryover limit 10× the adopted one."""
    bad = [lim for lim in LIMITS if lim.approval_status == "CONFLICT_REQUIRES_QA"]
    assert [(lim.test_code, lim.metric_key, lim.source_type) for lim in bad] == [
        ("T12", "carryover_pct", "IOQ_PROTOCOL_CH4")
    ]
    assert all(lim.flagged for lim in bad)
    authority = find_limit(list(LIMITS), "T12", "carryover_pct", "AUTHORITY_LIMIT")
    assert authority is not None and authority.max_value == D("0.01")
    assert bad[0].max_value == D("0.1")


def test_limit_count_is_stable():
    assert len(LIMITS) == 93


# ────────────────────────────── governance gate ───────────────────────────── #


def test_conflict_limit_never_passes():
    ev = evaluate_metric(
        test_code="T12", metric_key="carryover_pct", value=D("0.05"),
        source="IOQ_PROTOCOL_CH4", unit="%", limits=list(LIMITS),
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
        test_code="T12", metric_key="rt_rsd", value=D("0.2"),
        source="MANUFACTURER_SPEC", unit="%", limits=list(LIMITS),
    )
    assert ev.status == UNDER_REVIEW
    assert ev.applied_limit_id is None


def test_run_under_sop_policy_requires_review():
    outcome = run(source="SOP_LIMIT")
    assert outcome.overall == UNDER_REVIEW


# ──────────────────────────────── computation ─────────────────────────────── #


def test_compliant_instrument_passes_all_twenty():
    outcome = run()
    failing = {r.test_code: r.status for r in outcome.results if r.status != PASS}
    assert failing == {}
    assert outcome.overall == PASS
    assert outcome.summary()["pass"] == 20


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
    inputs = {**GOOD_INPUTS, "T13": {**GOOD_INPUTS["T13"], "leak_lpv": "FAIL"}}
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
    co = outcome.by_code["T12"].outputs["carryover_pct"]
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

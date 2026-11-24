"""Conformance tests for the authoritative server-side math engine.

These vectors are shared with the browser twin (frontend tests/engine.test.ts) so
both engines must produce identical results for the same raw data.
"""

from decimal import Decimal

import pytest

from app.domain.math_engine.ast_engine import (
    UnsafeExpression,
    evaluate,
    mean,
    ols,
    round_for_display,
    rs_deviation,
    rsd,
    sd,
)

D = Decimal


def test_arithmetic_precedence():
    assert evaluate("2 + 3 * 4") == D(14)
    assert evaluate("(2 + 3) * 4") == D(20)
    assert evaluate("-3^2") == D(-9)
    assert evaluate("2^3^2") == D(512)


def test_flow_rate_formula():
    actual = evaluate("(collected_vol * 60) / actual_time", {"collected_vol": "5.0", "actual_time": "299.4"})
    error = evaluate("((actual_flow - set_flow) / set_flow) * 100", {"actual_flow": actual, "set_flow": "1.0"})
    assert actual.quantize(D("0.0001")) == D("1.0020")
    assert abs(error) < D("0.5")


def test_gravimetric_injection_volume():
    vol = evaluate(
        "((w1 - w2) * 1000) / water_density",
        {"w1": "10.5000", "w2": "10.0008", "water_density": "0.997"},
    )
    acc = evaluate("((measured_vol / (set_vol * n)) - 1) * 100", {"measured_vol": vol, "set_vol": "50", "n": "10"})
    assert abs(acc) < D("1.3")


def test_gradient_formula_elementwise():
    out = evaluate(
        "((height_x - height_0) / (height_100 - height_0)) * 100",
        {"height_x": ["0", "1050", "50100", "90300", "100200"], "height_0": "0", "height_100": "100200"},
    )
    assert out[2].quantize(D("0.01")) == D("50.00")
    assert out[3].quantize(D("0.01")) == D("90.12")


@pytest.mark.parametrize(
    "expr",
    [
        "__import__('os').system('id')",
        "open('/etc/passwd').read()",
        "eval('1+1')",
        "exec('x=1')",
        "process.exit(1)",
        "1; import os",
        "[x for x in range(10)]",
        "lambda: 1",
        "a.b.c",
        "f'{__import__}'",
    ],
)
def test_forbidden_constructs(expr):
    with pytest.raises(UnsafeExpression):
        evaluate(expr, {})


def test_division_by_zero():
    with pytest.raises(UnsafeExpression):
        evaluate("1/0")


def test_ols_statistics():
    r = ols([20, 30, 40, 50, 60], [0.5, 0.75, 1.0, 1.25, 1.5])
    assert r["slope"].quantize(D("0.000001")) == D("0.025000")
    assert abs(r["intercept"]) < D("1e-20")
    assert r["r2"].quantize(D("1e-10")) == D("1.0000000000")


def test_sd_and_rsd_use_n_minus_one():
    xs = [100, 101, 99, 100, 100]
    assert sd(xs).quantize(D("0.0001")) == D("0.7071")
    assert rsd(xs).quantize(D("0.001")) == D("0.707")


def test_relative_sensitivity_deviation():
    dev = rs_deviation([20, 30, 40, 50, 60], [20, 30, 40, 50, 60])
    assert max(abs(x) for x in dev) < D("1e-20")


def test_rounding_only_at_display():
    assert round_for_display(D("0.123456789"), 3) == "0.123"
    assert round_for_display(D("2.0005"), 3) == "2.000"


def test_carryover_formulas():
    ch2 = evaluate("(area_blank / area_sample_250) * 100", {"area_blank": "0.02", "area_sample_250": "200000"})
    ioq = evaluate("(area_blank / (5 * area_sample_50)) * 100", {"area_blank": "0.02", "area_sample_50": "40000"})
    assert abs(ch2 - D("0.00001")) < D("1e-15")
    assert abs(ioq - D("0.00001")) < D("1e-15")


def test_mean_of_empty_series_rejected():
    with pytest.raises(UnsafeExpression):
        mean([])

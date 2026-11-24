"""Safe AST maths engine — authoritative server-side implementation.

Design rules (from the master specification):
  * No ``eval()`` / ``exec()`` / ``compile()`` anywhere in the request path.
  * ``decimal.Decimal`` for every scalar operation so ``NUMERIC(20, 8)`` storage
    never loses precision through binary floating point.
  * Whitelisted AST node types only — anything else raises ``UnsafeExpression``.
  * Whitelisted function names with fixed arity.

The expression grammar is identical to the browser twin in
``frontend/src/core/engine/safeMath.ts``; both are exercised by the same
conformance vectors in ``backend/tests/test_math_engine.py``.
"""

from __future__ import annotations

import ast
import re
from decimal import Decimal, getcontext
from statistics import mean as _mean
from typing import Any, Callable, Mapping, Sequence

getcontext().prec = 40

D = Decimal
Num = Decimal | list[Decimal]

ALLOWED_NODES = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Constant,
    ast.Name,
    ast.Load,
    ast.Call,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Mod,
    ast.Pow,
    ast.USub,
    ast.UAdd,
    ast.Tuple,
    ast.List,
)

ALLOWED_FUNCTIONS = {
    "abs",
    "min",
    "max",
    "mean",
    "sd",
    "rsd",
    "sum",
    "sqrt",
    "ln",
    "log10",
    "exp",
    "round",
    "ols_r2",
    "ols_slope",
    "ols_intercept",
    "rs_deviation",
    "pct_error",
    "count",
}


class UnsafeExpression(ValueError):
    """Raised when an expression contains a forbidden construct."""


def _check(node: ast.AST) -> None:
    if not isinstance(node, ALLOWED_NODES):
        raise UnsafeExpression(f"forbidden AST node: {type(node).__name__}")
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise UnsafeExpression("only direct function calls are permitted")
        if node.func.id not in ALLOWED_FUNCTIONS:
            raise UnsafeExpression(f"function not allowed: {node.func.id}")
        if node.keywords:
            raise UnsafeExpression("keyword arguments are not permitted")
    for child in ast.iter_child_nodes(node):
        _check(child)


_CARET = re.compile(r"(?<!\*)\^(?!\*)")


def normalise(expression: str) -> str:
    """Map the portable ``^`` power operator onto Python's ``**``.

    The browser twin treats ``^`` as exponentiation (right-associative), so the
    server must do exactly the same; ``^`` is never treated as XOR.
    """
    return _CARET.sub("**", expression)


def parse(expression: str) -> ast.Expression:
    """Parse and validate; returns a checked AST that is safe to walk."""
    if len(expression) > 2000:
        raise UnsafeExpression("expression too long")
    try:
        tree = ast.parse(normalise(expression), mode="eval")
    except SyntaxError as exc:  # pragma: no cover - defensive
        raise UnsafeExpression(f"syntax error: {exc.msg}") from exc
    _check(tree)
    return tree


# ------------------------------- statistics -------------------------------- #


def _dec_list(values: Sequence[Any]) -> list[Decimal]:
    out: list[Decimal] = []
    for v in values:
        out.append(v if isinstance(v, Decimal) else D(str(v)))
    return out


def mean(values: Sequence[Any]) -> Decimal:
    xs = _dec_list(values)
    if not xs:
        raise UnsafeExpression("mean of an empty series")
    return sum(xs, D(0)) / D(len(xs))


def sd(values: Sequence[Any]) -> Decimal:
    """Sample standard deviation with n-1 (identical to the browser engine)."""
    xs = _dec_list(values)
    if len(xs) < 2:
        raise UnsafeExpression("sd requires at least two points")
    m = mean(xs)
    ss = sum(((x - m) ** 2 for x in xs), D(0))
    return (ss / D(len(xs) - 1)).sqrt()


def rsd(values: Sequence[Any]) -> Decimal:
    xs = _dec_list(values)
    m = mean(xs)
    if m == 0:
        raise UnsafeExpression("rsd on a zero mean")
    return sd(xs) / m * D(100)


def ols(xs: Sequence[Any], ys: Sequence[Any]) -> dict[str, Any]:
    """Ordinary least squares with residuals — matches the JS implementation."""
    X = _dec_list(xs)
    Y = _dec_list(ys)
    if len(X) != len(Y) or len(X) < 2:
        raise UnsafeExpression("ols requires equal-length series of at least two points")
    mx, my = mean(X), mean(Y)
    sxx = sum(((x - mx) ** 2 for x in X), D(0))
    sxy = sum(((x - mx) * (y - my) for x, y in zip(X, Y)), D(0))
    syy = sum(((y - my) ** 2 for y in Y), D(0))
    if sxx == 0:
        raise UnsafeExpression("ols on a degenerate x series")
    slope = sxy / sxx
    intercept = my - slope * mx
    residuals = [y - (slope * x + intercept) for x, y in zip(X, Y)]
    ss_res = sum((r**2 for r in residuals), D(0))
    r2 = D(1) if syy == 0 else D(1) - ss_res / syy
    return {"slope": slope, "intercept": intercept, "r2": r2, "residuals": residuals}


def rs_deviation(heights: Sequence[Any], concs: Sequence[Any]) -> list[Decimal]:
    """Relative-sensitivity deviation per Integrity Guide Ch.2 §detector linearity."""
    h = _dec_list(heights)
    c = _dec_list(concs)
    if len(h) != len(c) or len(h) < 3:
        raise UnsafeExpression("rs_deviation requires at least three paired points")
    rs = [a / b for a, b in zip(h, c)]
    std = (rs[0] + rs[1] + rs[2]) / D(3)
    if std == 0:
        raise UnsafeExpression("rs_deviation baseline is zero")
    return [((r - std) / std) * D(100) for r in rs]


# ------------------------------- evaluation -------------------------------- #


def _call(name: str, args: list[Any]) -> Any:
    fn = FUNCTIONS.get(name)
    if fn is None:
        raise UnsafeExpression(f"function not allowed: {name}")
    return fn(args)


def _scalar_map(fn: Callable[[Decimal], Decimal]) -> Callable[[list[Any]], Any]:
    def inner(args: list[Any]) -> Any:
        v = args[0]
        if isinstance(v, list):
            return [fn(x) for x in v]
        return fn(v)

    return inner


FUNCTIONS: dict[str, Callable[[list[Any]], Any]] = {
    "abs": _scalar_map(abs),
    "sqrt": _scalar_map(lambda x: x.sqrt()),
    "ln": _scalar_map(lambda x: x.ln()),
    "log10": _scalar_map(lambda x: x.log10()),
    "exp": _scalar_map(lambda x: x.exp()),
    "round": lambda a: a[0].quantize(D(1).scaleb(-int(a[1] if len(a) > 1 else 0))),
    "min": lambda a: min(_flatten(a)),
    "max": lambda a: max(_flatten(a)),
    "sum": lambda a: sum(_dec_list(a[0]), D(0)),
    "mean": lambda a: mean(a[0]),
    "sd": lambda a: sd(a[0]),
    "rsd": lambda a: rsd(a[0]),
    "count": lambda a: D(len(a[0])),
    "ols_r2": lambda a: ols(a[0], a[1])["r2"],
    "ols_slope": lambda a: ols(a[0], a[1])["slope"],
    "ols_intercept": lambda a: ols(a[0], a[1])["intercept"],
    "rs_deviation": lambda a: rs_deviation(a[0], a[1]),
    "pct_error": lambda a: ((a[0] - a[1]) / a[1]) * D(100),
}


def _flatten(args: list[Any]) -> list[Decimal]:
    out: list[Decimal] = []
    for a in args:
        if isinstance(a, list):
            out.extend(_dec_list(a))
        else:
            out.append(a)
    return out


def _eval(node: ast.AST, scope: Mapping[str, Any]) -> Any:
    if isinstance(node, ast.Expression):
        return _eval(node.body, scope)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise UnsafeExpression("only numeric literals are permitted")
        return D(str(node.value))
    if isinstance(node, ast.Name):
        if node.id not in scope:
            raise UnsafeExpression(f"unknown variable: {node.id}")
        v = scope[node.id]
        return _dec_list(v) if isinstance(v, (list, tuple)) else (v if isinstance(v, Decimal) else D(str(v)))
    if isinstance(node, ast.UnaryOp):
        v = _eval(node.operand, scope)
        if isinstance(node.op, ast.USub):
            return [(-x) for x in v] if isinstance(v, list) else -v
        return v
    if isinstance(node, ast.BinOp):
        left = _eval(node.left, scope)
        right = _eval(node.right, scope)
        return _binop(node.op, left, right)
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_eval(e, scope) for e in node.elts]
    if isinstance(node, ast.Call):
        return _call(node.func.id, [_eval(a, scope) for a in node.args])  # type: ignore[attr-defined]
    raise UnsafeExpression(f"forbidden AST node: {type(node).__name__}")


def _binop(op: ast.operator, a: Any, b: Any) -> Any:
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            raise UnsafeExpression("series length mismatch")
        return [_binop(op, x, y) for x, y in zip(a, b)]
    if isinstance(a, list):
        return [_binop(op, x, b) for x in a]
    if isinstance(b, list):
        return [_binop(op, a, y) for y in b]
    if isinstance(op, ast.Add):
        return a + b
    if isinstance(op, ast.Sub):
        return a - b
    if isinstance(op, ast.Mult):
        return a * b
    if isinstance(op, ast.Div):
        if b == 0:
            raise UnsafeExpression("division by zero")
        return a / b
    if isinstance(op, ast.Mod):
        if b == 0:
            raise UnsafeExpression("modulo by zero")
        return a % b
    if isinstance(op, ast.Pow):
        return a**b
    raise UnsafeExpression(f"operator not allowed: {type(op).__name__}")


def evaluate(expression: str, scope: Mapping[str, Any] | None = None) -> Any:
    """Evaluate a validated expression and return Decimal or list[Decimal]."""
    return _eval(parse(expression), scope or {})


def round_for_display(value: Decimal, decimals: int) -> str:
    """Rounding is applied only at the presentation boundary."""
    return str(value.quantize(D(1).scaleb(-decimals)))

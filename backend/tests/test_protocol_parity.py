"""Conformance between the Python blueprint and the TypeScript twin.

`src/core/protocol.ts` is read as source text and structurally compared against
`app/domain/protocol/blueprint.py`. Running the TypeScript engine under Node is
not required: the two artefacts must agree on test codes, field keys, formula
expressions and every one of the 93 limits.

If this test fails, the frontend and the backend would score the same readings
differently — which is the single most dangerous defect this system can ship.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from app.domain.protocol.blueprint import LIMITS, TESTS

BACKEND = Path(__file__).resolve().parents[1]
FRONTEND = BACKEND.parent
PROTOCOL_TS = FRONTEND / "src" / "core" / "protocol.ts"

pytestmark = pytest.mark.skipif(
    not PROTOCOL_TS.exists(), reason="frontend twin not present in this checkout"
)


def _strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


@pytest.fixture(scope="module")
def ts_source() -> str:
    return _strip_comments(PROTOCOL_TS.read_text(encoding="utf-8"))


def test_all_twenty_test_codes_present(ts_source: str) -> None:
    codes = set(re.findall(r"code:\s*'(T\d\d)'", ts_source))
    expected = {t.code for t in TESTS}
    assert codes == expected, f"missing {expected - codes}, extra {codes - expected}"
    assert len(expected) == 20


def test_field_keys_match(ts_source: str) -> None:
    # TS fields are declared as `key: 'name'` inside the fields arrays
    for test in TESTS:
        for field_spec in test.fields:
            assert f"key: '{field_spec.key}'" in ts_source, (test.code, field_spec.key)


def test_formula_expressions_match(ts_source: str) -> None:
    py_expressions = {f.expression for t in TESTS for f in t.formulas}
    missing = [e for e in py_expressions if e not in ts_source]
    assert not missing, f"formula expressions missing from protocol.ts: {missing}"


def test_limit_count_and_sources(ts_source: str) -> None:
    calls = re.findall(
        r"L\(\s*'(T\d\d)'\s*,\s*'([^']+)'\s*,\s*'([A-Z_0-9]+)'\s*,\s*'(\w+)'\s*,"
        r"\s*([^,]+),\s*([^,]+),\s*'([^']*)'\s*,\s*([AC])",
        ts_source,
    )
    assert len(calls) == len(LIMITS) == 93, f"TS limits {len(calls)} vs Python {len(LIMITS)}"

    ts_set = {(t, m, s) for t, m, s, *_ in calls}
    py_set = {(l.test_code, l.metric_key, l.source_type) for l in LIMITS}
    assert ts_set == py_set


def test_conflict_limits_are_flagged_in_both(
    ts_source: str,
) -> None:
    """Every conflicted limit must be seeded as C in both twins."""
    ts_conflicts = {
        (t, m, s)
        for t, m, s, _op, _mn, _mx, _u, flag in re.findall(
            r"L\(\s*'(T\d\d)'\s*,\s*'([^']+)'\s*,\s*'([A-Z_0-9]+)'\s*,\s*'(\w+)'\s*,"
            r"\s*([^,]+),\s*([^,]+),\s*'([^']*)'\s*,\s*([AC])",
            ts_source,
        )
        if flag == "C"
    }
    py_conflicts = {
        (l.test_code, l.metric_key, l.source_type)
        for l in LIMITS
        if l.approval_status == "CONFLICT_REQUIRES_QA"
    }
    assert ts_conflicts == py_conflicts
    assert py_conflicts, "the defective SOP limits must be modelled as conflicts"


def test_breakdown_matrix_matches(ts_source: str) -> None:
    from app.domain.protocol.blueprint import BREAKDOWN_MATRIX

    for row in BREAKDOWN_MATRIX:
        assert f"key: '{row['key']}'" in ts_source or f"'{row['key']}'" in ts_source, row["key"]
        for code in row["tests"]:
            assert code in ts_source


def test_protocol_ts_is_generated_from_the_blueprint() -> None:
    """`src/core/protocol.ts` must be the generator's output, byte for byte.

    The table is no longer hand-maintained: `scripts/export_protocol_ts.py` derives it
    from the same blueprint the seeder writes to PostgreSQL. Regenerating and
    comparing turns "we forgot to update the twin" from a production incident into a
    failing build.
    """
    import subprocess

    generator = FRONTEND / "scripts" / "export_protocol_ts.py"
    assert generator.is_file(), "the protocol generator is missing"
    result = subprocess.run(
        [sys.executable, str(generator), "--check"],
        cwd=FRONTEND,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_protocol_reference_document_is_generated_from_the_blueprint() -> None:
    """`docs/protocol.md` is generated too — a stale limit in a document is a defect.

    A laboratory that reads an acceptance limit the engine does not enforce will sign
    a report that is wrong and believe it is compliant.
    """
    generator = FRONTEND / "scripts" / "export_protocol_doc.py"
    assert generator.is_file(), "the protocol document generator is missing"
    result = subprocess.run(
        [sys.executable, str(generator), "--check"],
        cwd=FRONTEND,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


TS_HARNESS = FRONTEND / "tests" / "parity" / "run_ts_engine.ts"
ESBUILD = FRONTEND / "node_modules" / ".bin" / "esbuild"

# One reference dataset, re-used from the API suite so both engines are fed
# exactly the readings a real analyst enters.
REFERENCE_INPUTS = __import__("tests.test_api_runs", fromlist=["COMPLIANT_INPUTS"]).COMPLIANT_INPUTS


@pytest.fixture(scope="module")
def ts_bundle(tmp_path_factory) -> Path:
    if shutil.which("node") is None:
        pytest.skip("node is not available")
    if not ESBUILD.exists():
        pytest.skip("esbuild is not installed (run npm install)")
    out = tmp_path_factory.mktemp("parity") / "ts_engine.mjs"
    result = subprocess.run(
        [str(ESBUILD), str(TS_HARNESS), "--bundle", "--platform=node",
         "--format=esm", f"--outfile={out}", "--log-level=warning"],
        cwd=FRONTEND, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    return out


@pytest.mark.parametrize("policy", ["AUTHORITY_LIMIT", "SOP_LIMIT", "MANUFACTURER_SPEC"])
def test_both_engines_score_identically(ts_bundle: Path, tmp_path: Path, policy: str) -> None:
    """Identical readings must produce identical verdicts in both engines.

    Every test status *and* every individual metric evaluation is compared. A
    divergence here means the browser could show a PASS where the server stored
    a FAIL — the single most dangerous defect this system can ship.
    """
    from app.domain.scoring.engine import execute_run

    payload = tmp_path / "payload.json"
    payload.write_text(
        json.dumps({"policySource": policy, "inputs": REFERENCE_INPUTS}), encoding="utf-8"
    )
    ts = json.loads(
        subprocess.run(
            ["node", str(ts_bundle), str(payload)], capture_output=True, text=True, check=True
        ).stdout
    )
    py = execute_run(
        tests=list(TESTS), raw_inputs=REFERENCE_INPUTS, limits=list(LIMITS), policy_source=policy
    )

    assert ts["overall"] == py.overall
    ts_by_code = {r["testCode"]: r for r in ts["results"]}
    assert set(ts_by_code) == {r.test_code for r in py.results}

    divergences: list[tuple] = []
    for result in py.results:
        ts_result = ts_by_code[result.test_code]
        if ts_result["status"] != result.status:
            divergences.append((result.test_code, "test status", ts_result["status"], result.status))
        ts_metrics = {m["metricKey"]: m["status"] for m in ts_result["metrics"]}
        for evaluation in result.metric_evaluations:
            if ts_metrics.get(evaluation.metric_key) != evaluation.status:
                divergences.append(
                    (result.test_code, evaluation.metric_key,
                     ts_metrics.get(evaluation.metric_key), evaluation.status)
                )
    assert not divergences, f"engine divergence under {policy}: {divergences[:10]}"


def test_reference_run_passes_under_authority_limits() -> None:
    from app.domain.scoring.engine import execute_run

    outcome = execute_run(
        tests=list(TESTS), raw_inputs=REFERENCE_INPUTS, limits=list(LIMITS),
        policy_source="AUTHORITY_LIMIT",
    )
    assert outcome.overall == "PASS"

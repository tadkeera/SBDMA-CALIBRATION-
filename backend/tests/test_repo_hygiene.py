"""Repository hygiene that is cheap to enforce and expensive to discover late.

One test, one claim: the tracked tree contains no committed credential. It runs the
same script CI runs, so a developer sees the failure before the pipeline does, and the
allowlist it consults lives in the repo with a written reason per entry.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_no_secrets_are_committed() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/scan_secrets.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "the secret scanner found something:\n" + result.stdout + result.stderr
    )

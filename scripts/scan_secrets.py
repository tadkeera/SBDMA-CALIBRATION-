#!/usr/bin/env python
"""Scan the tracked tree for committed secrets, with a reviewable allowlist.

Why not only a third-party scanner in CI
----------------------------------------
A scanner whose findings nobody can reproduce locally is a scanner people learn to
ignore. This one runs in the same checkout the developer has, in one second, with no
network, and its allowlist is a file in the repo with a written reason per entry — so
"why is this allowed" is answerable a year later.

What it looks for: provider token shapes (GitHub, AWS, Slack, Stripe, Google API,
private key blocks), and assignments whose *value* looks like a real credential
(``password = "…"``, ``secret: …``) while excluding placeholders and test fixtures.

Usage
    python scripts/scan_secrets.py            # exit 1 when something is found
    python scripts/scan_secrets.py --staged   # only what is about to be committed
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST = REPO_ROOT / ".github" / "secret-scan-allowlist.json"

#: Provider shapes. Anchored tightly enough that a UUID or a hash does not match.
PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("github-fine-grained", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{60,}\b")),
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("stripe-key", re.compile(r"\b[sr]k_live_[A-Za-z0-9]{20,}\b")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("vercel-token", re.compile(r"\bvcp_[A-Za-z0-9]{40,}\b")),
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----")),
    (
        "credential-assignment",
        re.compile(
            r"""(?i)\b(?:password|passwd|secret|api[_-]?key|token)\b\s*[:=]\s*['"]([^'"\n]{8,})['"]"""
        ),
    ),
)

#: Values that are obviously not secrets: fixtures, placeholders, documented demo accounts.
PLACEHOLDER = re.compile(
    r"(?i)^(?:"
    r"changeme|placeholder|example|dummy|redacted|your[-_ ]|xxx+|\*+|\$\{.*\}|\{\{.*\}\}"
    r"|[a-z_]+_here|<.*>|\.\.\.|none|null|true|false"
    r")"
)
TEST_MARKERS = ("test", "fixture", "example", "dev_pw", "sample", "fake", "demo")

SKIP_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".pdf", ".ico", ".woff", ".woff2",
    ".ttf", ".zip", ".docx", ".xlsx", ".pptx", ".dump", ".lock",
}
SKIP_PREFIXES = ("sbom/", "node_modules/", ".next/", ".venv/", "test-results/", "playwright-report/")


def _tracked_files(staged: bool) -> list[str]:
    cmd = ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"] if staged else [
        "git", "ls-files"
    ]
    result = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, check=True)
    return [line for line in result.stdout.splitlines() if line.strip()]


def _allowlist() -> list[dict]:
    if not ALLOWLIST.is_file():
        return []
    return json.loads(ALLOWLIST.read_text(encoding="utf-8")).get("allowed", [])


def _load_candidate(path: Path) -> str:  # pragma: no cover - trivial
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return ""


def scan_line(path: str, number: int, line: str, allowed: list[dict]) -> dict | None:
    for kind, pattern in PATTERNS:
        for match in pattern.finditer(line):
            value = match.group(1) if match.groups() else match.group(0)
            if kind == "credential-assignment":
                if PLACEHOLDER.match(value.strip()):
                    continue
                # a value that reads like a fixture is not a leak, but it must say so
                if any(marker in value.lower() for marker in TEST_MARKERS) and len(value) < 40:
                    continue
            for entry in allowed:
                if entry.get("path") and entry["path"] != path:
                    continue
                if entry.get("match") and entry["match"] not in line:
                    continue
                if entry.get("path") or entry.get("match"):
                    return None
            return {
                "path": path,
                "line": number,
                "kind": kind,
                "excerpt": line.strip()[:160],
            }
    return None


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Scan tracked files for secrets")
    parser.add_argument("--staged", action="store_true", help="scan only staged changes")
    args = parser.parse_args(argv)

    allowed = _allowlist()
    findings: list[dict] = []
    scanned = 0
    for relative in _tracked_files(args.staged):
        if relative.startswith(SKIP_PREFIXES) or Path(relative).suffix.lower() in SKIP_SUFFIXES:
            continue
        text = _load_candidate(REPO_ROOT / relative)
        if not text:
            continue
        scanned += 1
        for number, line in enumerate(text.splitlines(), start=1):
            if len(line) > 2000:
                continue
            hit = scan_line(relative, number, line, allowed)
            if hit:
                findings.append(hit)

    if findings:
        print(f"{len(findings)} potential secret(s) in {scanned} files:")
        for hit in findings:
            print(f"  {hit['path']}:{hit['line']}  [{hit['kind']}]  {hit['excerpt']}")
        print(
            "\nRemove the value, or — if it is genuinely a published fixture — add an entry "
            "to .github/secret-scan-allowlist.json with a reason."
        )
        return 1
    print(f"no secrets found in {scanned} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

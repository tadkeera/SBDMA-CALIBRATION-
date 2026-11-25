#!/usr/bin/env python
"""Generate CycloneDX SBOMs for the backend and the frontend.

Why
---
"Which version of cryptography is in the build a regulator is asking about?" is a
question that arrives years after the answer was knowable. An SBOM makes it a file
instead of an archaeology project, and it is the artifact a security review asks for
first.

No extra dependency, on purpose: the SBOM generator is a supply-chain artefact too, so
it is written against the metadata that already exists in the repo — ``pip freeze`` of
the deployment interpreter and ``package-lock.json`` of the frontend. That means it
runs on a machine with no network and cannot itself be a compromised package.

Which interpreter
-----------------
Run it with an environment that has ``backend/requirements.txt`` installed and nothing
else — that is what ships. Generating from a developer's fully-loaded virtualenv
describes the developer: the first SBOM produced here carried pymupdf, onnxruntime and
numpy, none of which the application imports. The CI job therefore installs the runtime
requirements into a clean environment before running ``--check``.

Usage
    python scripts/generate_sbom.py                # writes sbom/*.cdx.json
    python scripts/generate_sbom.py --out dist    # elsewhere
    python scripts/generate_sbom.py --check        # verify the committed SBOM is current

The serial number is derived from the content, so re-running on an unchanged lockfile
produces an identical file: a diff means the dependency graph changed, never that it
was generated twice.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC_VERSION = "1.5"


def _serial(payload: dict) -> str:
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    # a deterministic UUIDv5-shaped serial: the same inputs, the same SBOM identity
    return f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, digest)}"


def _timestamp() -> str:
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch:
        moment = datetime.fromtimestamp(int(epoch), tz=timezone.utc)
    else:
        moment = datetime.now(timezone.utc).replace(microsecond=0)
    return moment.isoformat().replace("+00:00", "Z")


def _purl_clean(name: str) -> str:
    return name.replace("_", "-").lower()


def backend_components() -> list[dict]:
    """Every distribution visible to the deployment interpreter."""
    freeze = subprocess.run(
        [sys.executable, "-m", "pip", "freeze", "--all"],
        capture_output=True,
        text=True,
    )
    if freeze.returncode != 0:  # pragma: no cover - environment problem
        raise SystemExit(f"pip freeze failed:\n{freeze.stderr}")
    components = []
    for line in freeze.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or " @ " in line or line.startswith("-e"):
            continue
        name, _, version = line.partition("==")
        if not version:
            continue
        components.append(
            {
                "type": "library",
                "name": name,
                "version": version,
                "purl": f"pkg:pypi/{_purl_clean(name)}@{version}",
                "scope": "required",
            }
        )
    return sorted(components, key=lambda c: c["name"].lower())


def frontend_components() -> list[dict]:
    """Every package resolved into the frontend bundle, from the lockfile."""
    lock_path = REPO_ROOT / "package-lock.json"
    if not lock_path.is_file():  # pragma: no cover
        raise SystemExit("package-lock.json is missing: npm ci produces it")
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    packages = lock.get("packages") or {}
    components = []
    for path, meta in packages.items():
        if not path or path == "":
            continue  # the root project itself
        if not meta.get("version"):
            continue
        # node_modules/<name> or node_modules/<scope>/<name> (nested copies too)
        name = path.split("node_modules/")[-1]
        if not name:
            continue
        components.append(
            {
                "type": "library",
                "name": name,
                "version": meta["version"],
                "purl": f"pkg:npm/{name.replace('/', '%2F')}@{meta['version']}",
                "scope": "required" if not meta.get("dev") else "optional",
            }
        )
    return sorted({(c["name"], c["version"]): c for c in components}.values(),
                  key=lambda c: (c["name"].lower(), c["version"]))


def build(name: str, components: list[dict]) -> dict:
    payload = {
        "bomFormat": "CycloneDX",
        "specVersion": SPEC_VERSION,
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "name": name,
                "version": (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip(),
            }
        },
        "components": components,
    }
    payload["serialNumber"] = _serial(payload)
    payload["metadata"]["timestamp"] = _timestamp()
    return payload


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Generate CycloneDX SBOMs")
    parser.add_argument("--out", default=str(REPO_ROOT / "sbom"))
    parser.add_argument("--check", action="store_true", help="fail if the committed SBOM is stale")
    args = parser.parse_args(argv)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    targets = {
        "backend": ("sbdma-calibration-api", backend_components),
        "frontend": ("sbdma-calibration-web", frontend_components),
    }
    stale: list[str] = []
    for key, (name, collect) in targets.items():
        payload = build(name, collect())
        path = out / f"{key}.cdx.json"
        # the timestamp is the one field that legitimately differs run to run
        comparable = json.loads(json.dumps(payload))
        body = json.dumps(comparable, indent=2, ensure_ascii=False) + "\n"
        if args.check:
            if not path.is_file() or _strip_time(path.read_text(encoding="utf-8")) != _strip_time(body):
                stale.append(
                    str(path.relative_to(REPO_ROOT)) if REPO_ROOT in path.parents else str(path)
                )
            continue
        path.write_text(body, encoding="utf-8")
        label = path.relative_to(REPO_ROOT) if REPO_ROOT in path.parents else path
        print(f"{label}: {len(payload['components'])} components")

    if args.check:
        if stale:
            print("stale SBOM (regenerate with `python scripts/generate_sbom.py`):")
            for item in stale:
                print(f"  - {item}")
            return 1
        print("SBOM is current")
    return 0


def _strip_time(body: str) -> str:
    payload = json.loads(body)
    payload.get("metadata", {}).pop("timestamp", None)
    return json.dumps(payload, sort_keys=True, ensure_ascii=False)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

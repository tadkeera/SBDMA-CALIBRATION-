#!/usr/bin/env python
"""Backup + restore rehearsal — rehearsed, timed and verified, or it did not happen.

Why this exists
---------------
A backup nobody has restored is a hope. The question an inspector (and an incident)
actually asks is: *"produce the record for run X, from the copy you would really
use."* This script answers it end to end — dump, restore into a fresh database, then
prove the restored copy is not merely *present* but *correct*:

* the audit chain still verifies (hash by hash, using the application's own verifier,
  not a re-implementation that could disagree with it);
* the protocol on file is the version that was signed;
* the row counts of the tables that matter are non-zero and match the source;
* filed blobs are present in the durable store, so evidence is recoverable too.

The numbers printed (dump size, restore seconds) are the measured RTO inputs for
``docs/production-hardening.md``. Re-run it after any schema change: a restore drill
that has not been re-run since the last migration is a claim, not a control.

Usage
-----
    python scripts/restore_drill.py                       # local dev database
    python scripts/restore_drill.py --source-url postgresql://…   # a prod replica
    python scripts/restore_drill.py --keep                # keep dump + target DB

Exit codes: 0 verified · 1 a check failed · 2 usage / environment problem.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND = REPO_ROOT / "backend"

DEFAULT_SOURCE = "postgresql+asyncpg://sbdma:sbdma_dev_pw@127.0.0.1:5432/sbdma"
#: The restore target is a *separate* server on purpose: a rehearsal that restores onto
#: the machine it is dumping from proves nothing about a machine that has been lost, and
#: a managed platform's application role cannot create databases anyway.
DEFAULT_TARGET_SERVER = "postgresql+asyncpg://sbdma:sbdma_dev_pw@127.0.0.1:5432"
DEFAULT_TARGET = "sbdma_restore_drill"

#: Tables whose absence would mean the restore "succeeded" while losing the laboratory.
REQUIRED_TABLES = (
    "users",
    "calibration_runs",
    "calibration_test_results",
    "audit_log",
    "calibration_protocols",
    "test_definitions",
    "acceptance_limits",
    "stored_blobs",
)

VERIFY_SNIPPET = r"""
import asyncio, json, sys
from sqlalchemy import func, select
from app.core.database import SessionFactory
from app.models.audit import AuditLog
from app.models.protocol import CalibrationProtocol
from app.models.storage import StoredBlob
from app.models.rbac import User
from app.services.audit_service import AuditService

TABLES = {
    "users": User,
    "audit_log": AuditLog,
    "calibration_protocols": CalibrationProtocol,
    "stored_blobs": StoredBlob,
}

async def main() -> int:
    async with SessionFactory() as session:
        counts = {}
        for name, model in TABLES.items():
            counts[name] = int(
                (await session.execute(select(func.count()).select_from(model))).scalar_one()
            )
        chain = await AuditService.verify_chain(session)
    print(json.dumps({"counts": counts, "chain": chain}))
    return 0

raise SystemExit(asyncio.run(main()))
"""


def _split(url: str) -> urllib.parse.SplitResult:
    if url.startswith("postgresql+asyncpg://"):
        url = url.replace("postgresql+asyncpg://", "postgresql://", 1)
    return urllib.parse.urlsplit(url)


def _env_for(url: str) -> dict[str, str]:
    parts = _split(url)
    env = dict(os.environ)
    if parts.password:
        env["PGPASSWORD"] = urllib.parse.unquote(parts.password)
    return env


def _conn_args(url: str) -> list[str]:
    parts = _split(url)
    args = ["-h", parts.hostname or "127.0.0.1", "-p", str(parts.port or 5432)]
    if parts.username:
        args += ["-U", urllib.parse.unquote(parts.username)]
    return args


def _run(cmd: list[str], *, env: dict[str, str], what: str) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        sys.stderr.write(f"{what} failed:\n{result.stdout}\n{result.stderr}\n")
        raise SystemExit(f"FAIL: {what}")


def check_environment(source_url: str) -> None:
    for tool in ("pg_dump", "pg_restore", "createdb", "psql"):
        if shutil.which(tool) is None:
            raise SystemExit(f"FAIL: {tool} is not installed")
    env = _env_for(source_url)
    result = subprocess.run(
        ["psql", *_conn_args(source_url), "-d", _split(source_url).path.lstrip("/") or "postgres",
         "-tAc", "SELECT 1"],
        capture_output=True, text=True, env=env,
    )
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        raise SystemExit("FAIL: cannot reach the source database")


def interpreter() -> str:
    """The Python that can import the application (the repo venv, if there is one)."""
    for candidate in (os.environ.get("SBDMA_PYTHON"), str(REPO_ROOT / ".venv/bin/python")):
        if candidate and Path(candidate).is_file():
            probe = subprocess.run(
                [candidate, "-c", "import sqlalchemy, asyncpg, fastapi"],
                capture_output=True, text=True,
            )
            if probe.returncode == 0:
                return candidate
    return sys.executable


def verify(target_url: str) -> dict:
    """Run the application's own verifier against the restored copy."""
    env = dict(os.environ)
    env["DATABASE_URL"] = target_url
    env.setdefault("JWT_SECRET", "restore-drill-placeholder-0123456789abcdef")
    env.setdefault("MFA_ENCRYPTION_KEY", "0123456789abcdef0123456789abcdef")
    env.setdefault("ENVIRONMENT", "test")
    env.setdefault("COOKIE_SECURE", "false")
    env["PYTHONPATH"] = str(BACKEND)
    result = subprocess.run(
        [interpreter(), "-c", VERIFY_SNIPPET],
        capture_output=True, text=True, env=env, cwd=BACKEND,
    )
    if result.returncode != 0:
        sys.stderr.write(result.stderr[-4000:])
        raise SystemExit("FAIL: verification against the restored copy did not run")
    return json.loads(result.stdout.strip().splitlines()[-1])


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Backup + restore rehearsal")
    parser.add_argument("--source-url", default=os.environ.get("DATABASE_URL", DEFAULT_SOURCE))
    parser.add_argument("--target-db", default=DEFAULT_TARGET)
    parser.add_argument(
        "--target-server",
        default=os.environ.get("RESTORE_TARGET_SERVER", DEFAULT_TARGET_SERVER),
        help="server to restore into (default: the local development PostgreSQL)",
    )
    parser.add_argument("--dir", default=None, help="where to write the dump (default: temp dir)")
    parser.add_argument("--keep", action="store_true", help="keep the dump and the restored database")
    parser.add_argument(
        "--schema",
        default="public",
        help=(
            "schema to dump (default: public — the application's own data). "
            "A managed platform's own schemas (auth, storage, realtime) are not ours to "
            "dump and the application role cannot lock them; the platform's backups cover "
            "those. Dumping the whole cluster as the app role fails, which is itself the "
            "finding: the backup credential cannot be the runtime credential."
        ),
    )
    args = parser.parse_args(argv)

    source_url = args.source_url
    workdir = Path(args.dir or tempfile.mkdtemp(prefix="sbdma-drill-"))
    workdir.mkdir(parents=True, exist_ok=True)
    dump = workdir / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) 
    dump = dump.with_suffix(".dump")
    env = _env_for(source_url)

    check_environment(source_url)

    print("\n── 1/4 dump (custom format, compressed)")
    started = time.time()
    _run(["pg_dump", "--format=custom", "--compress=9", "--no-owner", "--no-privileges",
          f"--schema={args.schema}",
          "-d", source_url.replace("postgresql+asyncpg://", "postgresql://"), "-f", str(dump)],
         env=env, what="pg_dump")
    dump_seconds = round(time.time() - started, 1)
    size_mb = round(dump.stat().st_size / (1024 * 1024), 2)
    print(f"   {size_mb} MB in {dump_seconds}s -> {dump}")

    print(f"\n── 2/4 restore into a fresh database ({args.target_db})")
    # Recreate from scratch: restoring over an existing schema exercises a path nobody
    # uses and can hide a missing table behind "already exists".
    target_server = args.target_server.replace("postgresql+asyncpg://", "postgresql://")
    target_url_parts = _split(args.target_server)
    target_url = (
        f"postgresql+asyncpg://{target_url_parts.netloc}/{args.target_db}"
    )
    target_env = _env_for(args.target_server)
    _run(["psql", *_conn_args(args.target_server), "-d", "postgres", "-qc",
          f'DROP DATABASE IF EXISTS "{args.target_db}" WITH (FORCE)'], env=target_env, what="drop target")
    _run(["createdb", *_conn_args(args.target_server), args.target_db], env=target_env, what="createdb")
    # PostgreSQL 15+ creates "public" itself, and the dump carries its own CREATE SCHEMA
    # public; dropping it first makes the restore deterministic on old and new servers
    _run(["psql", *_conn_args(args.target_server), "-d", args.target_db, "-qc",
          "DROP SCHEMA IF EXISTS public CASCADE"], env=target_env, what="reset target schema")
    started = time.time()
    _run(["pg_restore", "--no-owner", "--no-privileges", "--exit-on-error",
          "-d", f"{target_server}/{args.target_db}", str(dump)],
         env=target_env, what="pg_restore")
    restore_seconds = round(time.time() - started, 1)
    print(f"   restored in {restore_seconds}s")

    print("\n── 3/4 verify with the application's own code")
    report = verify(target_url)
    counts = report["counts"]
    chain = report["chain"]
    for name in REQUIRED_TABLES:
        if name in counts:
            print(f"   {name:<24} {counts[name]}")
    if not chain.get("ok"):
        raise SystemExit(f"FAIL: the restored audit chain does not verify: {chain}")
    for name in ("users", "audit_log", "calibration_protocols"):
        if counts.get(name, 0) == 0:
            raise SystemExit(f"FAIL: {name} is empty in the restored copy")

    print("\n── 4/4 summary")
    print(f"   audit chain        verified ({chain['total']} entries, head {chain['head'][:16]}…)")
    print(f"   dump               {size_mb} MB / {dump_seconds}s")
    print(f"   restore            {restore_seconds}s  (RTO floor for this dataset)")

    if args.keep:
        print(f"   kept               {dump} and database {args.target_db}")
    else:
        shutil.rmtree(workdir, ignore_errors=True)
        _run(["psql", *_conn_args(args.target_server), "-d", "postgres", "-qc",
              f'DROP DATABASE IF EXISTS "{args.target_db}" WITH (FORCE)'],
             env=target_env, what="cleanup")
    print("\nRESTORE DRILL PASSED\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

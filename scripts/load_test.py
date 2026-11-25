#!/usr/bin/env python
"""Load test for the calibration API — reads and the governed write path.

Stage 09 requires performance, not just function: a calibration platform whose
dashboard takes four seconds under three analysts will be worked around, and a
workaround is where data integrity goes to die. This harness answers one question
honestly — *at this concurrency, what does a user wait for, and is that acceptable?*

It is dependency-free on purpose (asyncio + httpx, both already runtime
dependencies) so it can run in the same container as the API, in CI, or on a
laptop, without a separate toolchain:

    python scripts/load_test.py --users 20 --duration 30 --write-ratio 0.2

Exit status is 1 when a budget is breached, so it can gate a pipeline:

    --p95-budget-ms 1500 --max-error-rate 0.01

Writes are real: each write iteration creates a run and executes the protocol
against the reference dataset. Point it at a disposable database (the E2E one),
never at production data.

One session, many users: the virtual population shares a single authenticated
session, because the sign-in route is deliberately rate limited to five attempts
per minute per address and that limit is a security control, not a performance
target. Pass `--login-per-user` when the deployment raises
`RATE_LIMIT_AUTH_PER_MINUTE` and you want to measure sign-in under load too.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
import os
import random
import statistics
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "e2e" / "fixtures"
ACCOUNTS = FIXTURES / "accounts.json"
INPUTS = FIXTURES / "compliant_inputs.json"


@dataclass
class Sample:
    path: str
    method: str
    status: int
    ms: float


@dataclass
class Report:
    samples: list[Sample] = field(default_factory=list)

    def add(self, sample: Sample) -> None:
        self.samples.append(sample)

    def summary(self) -> dict:
        by_path: dict[str, list[Sample]] = defaultdict(list)
        for sample in self.samples:
            by_path[f"{sample.method} {sample.path}"].append(sample)

        rows = []
        for label, items in sorted(by_path.items()):
            times = sorted(item.ms for item in items)
            errors = [item for item in items if item.status >= 400]
            rows.append(
                {
                    "endpoint": label,
                    "requests": len(items),
                    "errors": len(errors),
                    "rps": round(len(items) / max(WALL[0], 1e-9), 2),
                    "p50": round(_percentile(times, 0.50), 1),
                    "p95": round(_percentile(times, 0.95), 1),
                    "p99": round(_percentile(times, 0.99), 1),
                    "max": round(times[-1], 1),
                    "mean": round(statistics.fmean(times), 1),
                }
            )
        all_times = sorted(sample.ms for sample in self.samples)
        total = len(self.samples)
        failed = sum(1 for sample in self.samples if sample.status >= 400)
        return {
            "duration_s": round(WALL[0], 1),
            "requests": total,
            "throughput_rps": round(total / max(WALL[0], 1e-9), 2),
            "errors": failed,
            "error_rate": round(failed / total, 4) if total else 0.0,
            "p50": round(_percentile(all_times, 0.50), 1),
            "p95": round(_percentile(all_times, 0.95), 1),
            "p99": round(_percentile(all_times, 0.99), 1),
            "endpoints": rows,
        }


WALL = [0.0]


def _percentile(ordered: list[float], q: float) -> float:
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
    return ordered[index]


async def _timed(
    client: httpx.AsyncClient, report: Report, method: str, path: str, **kwargs
) -> httpx.Response | None:
    started = time.perf_counter()
    try:
        response = await client.request(method, path, **kwargs)
    except Exception:  # noqa: BLE001 - a transport failure is a failed sample
        report.add(Sample(path=path, method=method, status=0, ms=(time.perf_counter() - started) * 1000))
        return None
    report.add(
        Sample(
            path=path,
            method=method,
            status=response.status_code,
            ms=(time.perf_counter() - started) * 1000,
        )
    )
    return response


class User:
    """One virtual user: signs in once, then mixes reads and governed writes."""

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        write_ratio: float,
        token: str | None = None,
    ) -> None:
        self.base_url = base_url
        self.username = username
        self.password = password
        self.write_ratio = write_ratio
        self.token = token
        self.report = Report()
        self.instrument_id: str | None = None

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    async def sign_in(self, client: httpx.AsyncClient) -> None:
        if self.token:
            return
        response = await _timed(
            client,
            self.report,
            "POST",
            "/auth/login",
            json={"username": self.username, "password": self.password},
        )
        if response is None or response.status_code >= 400:
            raise SystemExit(
                f"sign-in failed for {self.username}: "
                f"{response.status_code if response is not None else 'no response'} "
                f"{response.text[:200] if response is not None else ''}"
            )
        self.token = response.json()["data"]["access_token"]

    async def run(self, client: httpx.AsyncClient, deadline: float, inputs: dict) -> None:
        await self.sign_in(client)
        instruments = await _timed(client, self.report, "GET", "/instruments", headers=self.headers)
        if instruments is not None and instruments.status_code == 200:
            rows = instruments.json()["data"]
            if rows:
                self.instrument_id = rows[0]["id"]

        while time.perf_counter() < deadline:
            if random.random() < self.write_ratio and self.instrument_id:
                await self.write_cycle(client, inputs)
            else:
                await self.read_cycle(client)

    async def read_cycle(self, client: httpx.AsyncClient) -> None:
        for path in ("/health", "/runs?limit=20", "/kpis", "/instruments", "/branding"):
            await _timed(client, self.report, "GET", path, headers=self.headers)

    async def write_cycle(self, client: httpx.AsyncClient, inputs: dict) -> None:
        """Create → execute → read back: the path an analyst walks after a run."""
        created = await _timed(
            client,
            self.report,
            "POST",
            "/runs",
            headers={**self.headers, "Idempotency-Key": str(uuid.uuid4())},
            json={
                "instrument_id": self.instrument_id,
                "run_type": "ROUTINE",
                "ambient_temp_c": 24.5,
                "ambient_humidity": 55.0,
                "notes": "load test",
            },
        )
        if created is None or created.status_code >= 300:
            return
        run_id = created.json()["data"]["id"]
        await _timed(
            client,
            self.report,
            "POST",
            f"/runs/{run_id}/execute",
            headers=self.headers,
            json={"raw_inputs": inputs},
        )
        await _timed(client, self.report, "GET", f"/runs/{run_id}", headers=self.headers)


async def main() -> int:
    parser = argparse.ArgumentParser(description="Load test the calibration API")
    parser.add_argument("--base-url", default=os.environ.get("API_BASE_URL", "http://127.0.0.1:8000/api/v1"))
    parser.add_argument("--users", type=int, default=10)
    parser.add_argument("--duration", type=float, default=20.0, help="seconds of steady load")
    parser.add_argument("--write-ratio", type=float, default=0.2, help="0 = reads only, 1 = writes only")
    parser.add_argument("--p95-budget-ms", type=float, default=2000.0)
    parser.add_argument("--max-error-rate", type=float, default=0.01)
    parser.add_argument("--out", default="", help="write the JSON report here")
    parser.add_argument("--label", default="", help="name this run (stored in the report)")
    parser.add_argument("--login-per-user", action="store_true", help="each user signs in separately")
    parser.add_argument("--username", default="")
    parser.add_argument("--password", default="")
    args = parser.parse_args()

    accounts = json.loads(ACCOUNTS.read_text())
    username = args.username or accounts["analyst"]["username"]
    password = args.password or os.environ.get("E2E_ANALYST_PASSWORD") or accounts["analyst"]["password"]
    inputs = json.loads(INPUTS.read_text())

    users = [User(args.base_url, username, password, args.write_ratio) for _ in range(args.users)]
    limits = httpx.Limits(max_connections=args.users * 2, max_keepalive_connections=args.users)
    timeout = httpx.Timeout(60.0)

    started = time.perf_counter()
    deadline = started + args.duration
    async with httpx.AsyncClient(base_url=args.base_url, limits=limits, timeout=timeout) as client:
        # one sign-in first, so we fail fast and honestly if credentials are wrong
        await users[0].sign_in(client)
        if not args.login_per_user:
            shared = users[0].token
            for user in users[1:]:
                user.token = shared
        workers = [user.run(client, deadline, inputs) for user in users]
        await asyncio.gather(*workers, return_exceptions=True)
    WALL[0] = time.perf_counter() - started

    combined = Report()
    for user in users:
        combined.samples.extend(user.report.samples)
    summary = combined.summary()
    summary["label"] = args.label
    summary["users"] = args.users
    summary["write_ratio"] = args.write_ratio
    summary["base_url"] = args.base_url

    print(f"\n{'endpoint':<34}{'req':>7}{'err':>6}{'p50':>9}{'p95':>9}{'p99':>9}{'max':>9}")
    for row in summary["endpoints"]:
        print(
            f"{row['endpoint']:<34}{row['requests']:>7}{row['errors']:>6}"
            f"{row['p50']:>9.0f}{row['p95']:>9.0f}{row['p99']:>9.0f}{row['max']:>9.0f}"
        )
    print(
        f"\n{summary['users']} users · {summary['duration_s']}s · {summary['throughput_rps']} req/s · "
        f"{summary['requests']} requests · error rate {summary['error_rate'] * 100:.2f}% · "
        f"p50 {summary['p50']:.0f}ms · p95 {summary['p95']:.0f}ms · p99 {summary['p99']:.0f}ms"
    )

    if args.out:
        Path(args.out).write_text(json.dumps(summary, indent=2) + "\n")
        print(f"report written to {args.out}")

    breaches = []
    if summary["p95"] > args.p95_budget_ms:
        breaches.append(f"p95 {summary['p95']:.0f}ms > budget {args.p95_budget_ms:.0f}ms")
    if summary["error_rate"] > args.max_error_rate:
        breaches.append(f"error rate {summary['error_rate'] * 100:.2f}% > {args.max_error_rate * 100:.2f}%")
    if breaches:
        print("\nBUDGET BREACHED: " + "; ".join(breaches))
        return 1
    print("\nwithin budget")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

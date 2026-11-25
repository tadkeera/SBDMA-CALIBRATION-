# Load test — the API under concurrent analysts

Stage 09 asks for a measured answer to one question: *at realistic concurrency,
what does a user wait for?* This document records how that was measured, the
numbers, and the two defects the measurement exposed.

Harness: [`scripts/load_test.py`](../scripts/load_test.py) — asyncio + `httpx`, no
extra tooling, runs anywhere the API runs.

```bash
# 5 analysts, mixed traffic, 15 s
.venv/bin/python scripts/load_test.py --users 5 --duration 15 --write-ratio 0.4 \
    --p95-budget-ms 2000 --out load.json
```

Each write iteration walks the real governed path: create the run with an
`Idempotency-Key`, execute the 20-test protocol against the reference dataset, then
read the stored run back. Reads are the dashboard's four calls plus `/branding`.

## Environment

| | |
|---|---|
| Container | 2 vCPU, 1 GB RAM |
| API | uvicorn, **one** worker process, `--host 0.0.0.0` |
| Database | PostgreSQL 17, same host, pool 10 + 20 overflow |
| Broker | Redis 7, same host, same CPU budget as the API |
| Load generator | same container (it steals CPU from the server under test) |
| Rate limits | raised for the run: every request arrives from one address, and the per-address limiter (120/min) is a security control, not a performance target |
| Session | one authenticated analyst session shared by the virtual users — the sign-in route allows 5 attempts/min per address by design |

Read the numbers as a *floor*, not a ceiling: generator and server share two cores.

## Results

**5 users, reads only, 15 s** — 81 requests, 0 errors, 5.1 req/s

| endpoint | p50 | p95 | p99 |
|---|---:|---:|---:|
| `GET /instruments` | 34 ms | 40 ms | 54 ms |
| `GET /kpis` | 65 ms | 83 ms | 1 065 ms |
| `GET /runs?limit=20` | 53 ms | 3 060 ms | 4 050 ms |

**5 users, 40 % writes, 15 s** — 91 requests, 1 error, 5.6 req/s

| endpoint | p50 | p95 |
|---|---:|---:|
| `GET /branding` | 16 ms | 1 029 ms |
| `GET /instruments` | 38 ms | 2 047 ms |
| `GET /runs?limit=20` | 49 ms | 2 055 ms |
| `POST /runs/{id}/execute` (20 tests) | 108 ms | 2 183 ms |

**20 users, 20 % writes, 30 s** — 200 requests, 2 % errors, 5.5 req/s.
Twenty users on two cores is beyond this box: the medians hold (`/branding` 103 ms,
`/instruments` 190 ms) but the tail collapses (`/health` p95 16 s), and the rate
limiter logs `Timeout reading from 127.0.0.1:6379` — Redis starving because the
whole container is CPU-bound.

## What the measurement found

1. **The scoring engine ran on the event loop.** `execute_run` evaluates 75
   formulas at thirty significant digits — pure CPU, no I/O. On the event loop it
   froze the *entire* API for ~1 s per calibration (visible in the first run as
   `/health` p50 = 2 021 ms with no writes in flight). It now runs via
   `asyncio.to_thread`; an execution costs 104–108 ms of server time and other
   requests keep flowing.
2. **Report generation had the same bug.** ReportLab lays out a three-page
   certificate and shapes Arabic text; `build_run_xlsx`, `build_kpi_pdf` and
   `build_certificate_pdf` are now all offloaded the same way.

## Deployment guidance

* **Concurrency is per process.** One uvicorn worker saturates at a handful of
  concurrent analysts on two cores; the K8s deployment already runs N replicas
  behind the Service, which is where concurrency is meant to come from. Do not
  raise `--workers` inside a small pod — the DB pool (10 + 20) is per process and
  Postgres `max_connections` is finite.
* **Keep the CPU work off the loop.** Any future CPU-bound step (new report
  renderers, hashing large files) must use `asyncio.to_thread` or a worker, not the
  request coroutine. The load test catches regressions: p95 spikes in *every*
  endpoint at once, not just the slow one.
* **Budget.** A calibration run taking ~110 ms of server CPU is the design point:
  ten runs a minute fits comfortably on one replica; a batch of 200 nightly runs
  belongs on the Celery worker, not in a browser request.
* **Tail latency on this host** is dominated by the co-located database and the
  load generator. Run the harness on a separate machine before quoting numbers to
  anyone.

## Reading a failure

The harness exits non-zero when a budget is breached, so CI can gate on it:

```
BUDGET BREACHED: p95 4042ms > budget 4000ms; error rate 1.10% > 1.00%
```

A budget breach is not automatically a defect — check first whether the write path
or the whole box is saturated (compare `/health` p95 with `/branding` p95: if both
move together, nobody's query is slow, the CPU is).

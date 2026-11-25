"""Shared (cross-replica) rate limiting.

Why this module exists
----------------------
The API runs as several replicas (``infra/k8s/api-deployment.yaml`` asks for three).
The previous limiter kept its sliding window in process memory, so every replica
enforced its own private budget: an operator who configured *five sign-ins per
minute* was in practice allowing fifteen, and a brute-force run simply spread
itself across replicas. A limit that depends on which replica answers is not a
limit, it is a coincidence.

Design constraints, in the order they matter
-------------------------------------------
1. **A Redis outage must not remove the control and must not take the API down.**
   On any Redis error the request falls back to a per-process window and the
   degraded state is reported by ``/health``. The limit becomes weaker for the
   duration of the outage — it does not become absent, and it does not become a
   500. Failing open silently would be worse: the operator would never learn the
   limit had stopped being shared.
2. **One connection pool per event loop.** The Celery work proved what happens
   when a pool created under one loop is used under another ("attached to a
   different loop"): the first caller succeeds and the next one dies. The test
   suite, the ASGI transport and any embedded caller each bring their own loop, so
   the client is cached per running loop and stale loops are dropped.
3. **A true sliding window** (a sorted set of request timestamps), not a fixed
   bucket. A fixed minute allows twice the budget across a bucket boundary, which
   for a five-per-minute sign-in limit is the difference between a control and a
   speed bump. The whole check is one Lua script so that read-modify-write is
   atomic across replicas; a Python-side INCR-then-EXPIRE pair is not.

The in-memory implementation stays — it is the fallback, and it is what a
single-process development instance uses when ``REDIS_URL`` is unset.
"""

from __future__ import annotations

import asyncio
import threading
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger("sbdma.ratelimit")

#: Atomic sliding window: drop entries older than the window, count what is left,
#: and only record the hit when it is allowed. Returns ``{allowed, remaining}``.
_SLIDING_WINDOW_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window_ms = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]

redis.call('ZREMRANGEBYSCORE', key, 0, now - window_ms)
local used = redis.call('ZCARD', key)
if used >= limit then
  return {0, 0}
end
redis.call('ZADD', key, now, member)
redis.call('PEXPIRE', key, window_ms)
return {1, limit - used - 1}
"""


@dataclass(frozen=True)
class Decision:
    """The answer to "may this caller proceed?", with which policy answered it."""

    allowed: bool
    remaining: int
    backend: str  # "redis" | "memory"


class InMemoryLimiter:
    """Per-process sliding window.

    Used when no broker is configured, and as the fallback while Redis is
    unreachable. Guarded by a lock because the middleware is async but a caller
    (a worker, a script) may reach it from another thread.
    """

    backend = "memory"

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window_seconds: int = 60) -> tuple[bool, int]:
        now = time.monotonic()
        with self._lock:
            bucket = self._hits[key]
            while bucket and now - bucket[0] > window_seconds:
                bucket.popleft()
            if len(bucket) >= limit:
                return False, 0
            bucket.append(now)
            return True, limit - len(bucket)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


class SharedRateLimiter:
    """Redis-backed limiter with an in-memory fallback.

    ``redis_url=None`` means "no broker configured": the limiter is honestly
    in-process and ``/health`` says so, rather than claiming a shared control it
    does not have.
    """

    def __init__(self, redis_url: str | None = None, prefix: str = "sbdma:rl:v1") -> None:
        self._redis_url = redis_url
        self._prefix = prefix
        self._fallback = InMemoryLimiter()
        # id(loop) -> (loop, client). Keyed by identity so a closed test loop's
        # client is replaced instead of reused across loops.
        self._clients: dict[int, tuple[asyncio.AbstractEventLoop, object]] = {}
        self._script = None
        self._degraded_reason: str | None = None

    # ------------------------------------------------------------------ state
    @property
    def backend(self) -> str:
        if not self._redis_url:
            return "memory"
        return "memory(redis-unavailable)" if self._degraded_reason else "redis"

    @property
    def configured_backend(self) -> str:
        return "redis" if self._redis_url else "memory"

    @property
    def degraded_reason(self) -> str | None:
        return self._degraded_reason

    # ----------------------------------------------------------------- clients
    def _client_for_loop(self):  # noqa: ANN202 - redis type is optional at import
        loop = asyncio.get_running_loop()
        entry = self._clients.get(id(loop))
        if entry is not None and entry[0] is loop and not loop.is_closed():
            return entry[1]

        import redis.asyncio as aioredis

        client = aioredis.from_url(
            self._redis_url,
            socket_connect_timeout=1,
            socket_timeout=1,
            decode_responses=True,
            health_check_interval=30,
        )
        # Drop clients whose loop is gone; without this a long-lived process that
        # creates loops (tests, embedded runs) would leak one pool per loop.
        for key, (other_loop, _) in list(self._clients.items()):
            if other_loop.is_closed():
                self._clients.pop(key, None)
        self._clients[id(loop)] = (loop, client)
        self._script = None
        return client

    # ----------------------------------------------------------------- acquire
    async def acquire(
        self, key: str, limit: int, window_seconds: int = 60
    ) -> Decision:
        if not self._redis_url:
            allowed, remaining = self._fallback.allow(key, limit, window_seconds)
            return Decision(allowed, remaining, self._fallback.backend)

        full_key = f"{self._prefix}:{key}"
        try:
            client = self._client_for_loop()
            if self._script is None:
                self._script = client.register_script(_SLIDING_WINDOW_LUA)
            allowed, remaining = await self._script(
                keys=[full_key],
                args=[
                    int(time.time() * 1000),
                    window_seconds * 1000,
                    limit,
                    f"{time.time():.6f}:{uuid.uuid4().hex}",
                ],
            )
            if self._degraded_reason is not None:
                log.warning("rate limiter recovered: policy is shared again")
                self._degraded_reason = None
            return Decision(bool(allowed), int(remaining), "redis")
        except Exception as exc:  # noqa: BLE001 - any broker failure degrades, never 500
            if self._degraded_reason is None:
                log.error(
                    "rate limiter fell back to the in-process window",
                    extra={"extra_fields": {"error": str(exc)}},
                )
            self._degraded_reason = str(exc)
            allowed, remaining = self._fallback.allow(key, limit, window_seconds)
            return Decision(allowed, remaining, "memory")

    # ------------------------------------------------------------ maintenance
    def reset(self) -> None:
        """Clear the in-process window. Kept sync: existing callers are fixtures."""
        self._fallback.reset()

    async def clear(self) -> None:
        """Clear both windows. Tests and operators use this; it is not on a hot path."""
        self._fallback.reset()
        if not self._redis_url:
            return
        try:
            client = self._client_for_loop()
            async for key in client.scan_iter(match=f"{self._prefix}:*", count=500):
                await client.delete(key)
        except Exception as exc:  # noqa: BLE001 - clearing is best effort
            log.warning(
                "could not clear shared rate-limit keys",
                extra={"extra_fields": {"error": str(exc)}},
            )

    async def aclose(self) -> None:
        for loop, client in list(self._clients.values()):
            try:
                if not loop.is_closed():
                    await client.aclose()
            except Exception:  # noqa: BLE001 - shutdown must not raise
                pass
        self._clients.clear()
        self._script = None


def _build() -> SharedRateLimiter:
    settings = get_settings()
    backend = settings.rate_limit_backend
    if backend == "memory":
        return SharedRateLimiter(redis_url=None)
    # ``redis`` means "use it and complain if it is missing"; ``auto`` is the
    # default and also tolerates a broker-less development instance.
    return SharedRateLimiter(redis_url=settings.redis_url)


#: The one instance the middleware and ``/health`` both read. Two instances would
#: mean two budgets, which is the bug this module exists to remove.
limiter = _build()

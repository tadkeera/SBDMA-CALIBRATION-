"""Rate limiting: one budget or N of them?

The property this file exists to protect is *sharing*: with three API replicas, a
five-per-minute sign-in limit must mean five, not fifteen. The in-process window
cannot express that, so the tests first demonstrate the gap and then prove the
Redis-backed window closes it — against a real Redis, because a mocked broker would
gladly agree that a Lua script works.

Tests that need a broker skip when none is running; the fallback behaviour is
tested unconditionally, since "Redis is down" is exactly the state it must survive.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest

from app.core.ratelimit import InMemoryLimiter, SharedRateLimiter

REDIS_URL = os.environ.get("REDIS_URL") or "redis://127.0.0.1:6379/0"


async def _redis_available(url: str = REDIS_URL) -> bool:
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(url, socket_connect_timeout=1, socket_timeout=1)
        try:
            await client.ping()
            return True
        finally:
            await client.aclose()
    except Exception:  # noqa: BLE001 - unavailable is an expected outcome
        return False


@pytest.fixture()
async def shared() -> SharedRateLimiter:
    if not await _redis_available():
        pytest.skip("no Redis broker available")
    limiter = SharedRateLimiter(redis_url=REDIS_URL, prefix=f"test:rl:{uuid.uuid4().hex}")
    yield limiter
    await limiter.clear()
    await limiter.aclose()


# --------------------------------------------------------------- the gap itself
@pytest.mark.parametrize("window", [60])
async def test_two_in_process_limiters_do_not_share_a_budget(window: int) -> None:
    """The defect, stated as a test: N replicas each enforce their own budget.

    This is why the window moved to Redis. If this test ever starts failing because
    the two objects share state, the comment above ``SharedRateLimiter`` is wrong.
    """
    replica_a = SharedRateLimiter(redis_url=None)
    replica_b = SharedRateLimiter(redis_url=None)

    for _ in range(5):
        assert (await replica_a.acquire("ip:sign-in", 5, window)).allowed

    refused_a = await replica_a.acquire("ip:sign-in", 5, window)
    # a fresh process is a fresh budget: the client doubles its allowance by
    # reconnecting to another replica
    allowed_b = await replica_b.acquire("ip:sign-in", 5, window)
    assert refused_a.allowed is False
    assert allowed_b.allowed is True


# ------------------------------------------------------------ the shared window
async def test_a_shared_window_is_enforced_across_replicas(shared: SharedRateLimiter) -> None:
    key = f"198.51.100.7:{uuid.uuid4().hex}"
    decisions = [await shared.acquire(key, 5, 60) for _ in range(5)]
    assert all(d.allowed for d in decisions)
    assert decisions[-1].remaining == 0
    assert decisions[0].backend == "redis"

    # a *second* process with the same broker URL, i.e. the second API replica
    other = SharedRateLimiter(redis_url=REDIS_URL, prefix=shared._prefix)
    try:
        refused = await other.acquire(key, 5, 60)
        assert refused.allowed is False, "a second replica must see the first one's hits"
        assert refused.remaining == 0
    finally:
        await other.aclose()


async def test_limits_are_per_client_and_per_route(shared: SharedRateLimiter) -> None:
    limit = 2
    one = f"sign-in:{uuid.uuid4().hex}"
    two = f"read:{uuid.uuid4().hex}"

    assert (await shared.acquire(one, limit)).allowed
    assert (await shared.acquire(one, limit)).allowed
    assert (await shared.acquire(one, limit)).allowed is False
    # a different route keeps its own budget
    assert (await shared.acquire(two, limit)).allowed


async def test_the_window_slides_instead_of_resetting_on_a_boundary(
    shared: SharedRateLimiter,
) -> None:
    key = f"window:{uuid.uuid4().hex}"
    assert (await shared.acquire(key, 1, 1)).allowed
    assert (await shared.acquire(key, 1, 1)).allowed is False
    await asyncio.sleep(1.1)
    assert (await shared.acquire(key, 1, 1)).allowed


# ------------------------------------------------------------------ degradation
async def test_a_dead_broker_degrades_to_the_local_window_not_a_500() -> None:
    """A cache outage may weaken the control; it may not remove it, and it may not
    turn every request into an error. The degraded backend must be visible."""
    limiter = SharedRateLimiter(redis_url="redis://127.0.0.1:6390/0", prefix="dead")
    try:
        decision = await limiter.acquire("ip:route", 2, 60)
        assert decision.allowed is True
        assert decision.backend == "memory"
        assert limiter.backend == "memory(redis-unavailable)"
        assert limiter.degraded_reason
        # the fallback still enforces something — it is not an open door
        assert (await limiter.acquire("ip:route", 2, 60)).allowed is True
        assert (await limiter.acquire("ip:route", 2, 60)).allowed is False
    finally:
        await limiter.aclose()


def test_memory_limiter_counts_within_its_window() -> None:
    limiter = InMemoryLimiter()
    assert limiter.allow("k", 2)[0] is True
    assert limiter.allow("k", 2)[0] is True
    allowed, remaining = limiter.allow("k", 2)
    assert allowed is False and remaining == 0
    limiter.reset()
    assert limiter.allow("k", 2)[0] is True


# --------------------------------------------------------------- over HTTP
async def test_health_probes_are_never_rate_limited(client) -> None:  # noqa: ANN001
    for _ in range(12):  # twice the auth budget, all on a probe path
        response = await client.get("/api/v1/health/live")
        assert response.status_code == 200


async def test_the_sign_in_budget_is_announced_in_headers(client) -> None:  # noqa: ANN001
    from app.api.middleware import limiter as app_limiter

    response = await client.post(
        "/api/v1/auth/login", json={"username": "nobody", "password": "wrong-password"}
    )
    assert response.status_code == 401
    assert response.headers["X-RateLimit-Backend"] in {"memory", "redis"}
    assert int(response.headers["X-RateLimit-Limit"]) == 5
    assert int(response.headers["X-RateLimit-Remaining"]) == 4
    assert app_limiter.backend in {"memory", "redis"}


async def test_the_sixth_sign_in_in_a_minute_is_refused(client) -> None:  # noqa: ANN001
    for _ in range(5):
        first = await client.post(
            "/api/v1/auth/login", json={"username": "nobody", "password": "wrong-password"}
        )
        assert first.status_code == 401
    sixth = await client.post(
        "/api/v1/auth/login", json={"username": "nobody", "password": "wrong-password"}
    )
    assert sixth.status_code == 429
    assert sixth.headers["Retry-After"] == "60"
    body = sixth.json()
    assert body["success"] is False
    assert body["errors"][0]["code"] == "RATE_LIMITED"
    assert body["meta"]["backend"] in {"memory", "redis"}


async def test_health_declares_which_policy_is_enforcing(client) -> None:  # noqa: ANN001
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["data"]["components"]["rate_limit"] in {
        "redis",
        "memory",
        "memory(redis-unavailable)",
    }

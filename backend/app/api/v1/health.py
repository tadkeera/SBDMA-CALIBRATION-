"""Health, readiness and KPI endpoints.

KPIs are computed from live rows — the specification forbids synthetic numbers.
"""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from app.api.deps import PrincipalDep, SessionDep
from app.core.config import get_settings
from app.core.database import ping
from app.core.ratelimit import limiter
from app.schemas.common import ok
from app.services.kpi_service import KpiService

router = APIRouter(tags=["health"])
settings = get_settings()


@router.get("/health/live", summary="فحص الحياة")
async def live():
    return ok({"status": "alive", "version": settings.app_version})


@router.get("/health/ready", summary="فحص الجهوزية")
async def ready(session: SessionDep):
    db_ok = await ping()
    checks = {"database": db_ok, "cache": None, "workers": None}
    if db_ok:
        try:
            await session.execute(text("SELECT 1"))
        except Exception:
            checks["database"] = False
    status = "ready" if all(v is not False for v in checks.values()) else "degraded"
    return ok(
        {
            "status": status,
            "checks": checks,
            "unconfigured": [k for k, v in checks.items() if v is None],
        }
    )


@router.get("/health", summary="فحص صحة النظام الكامل")
async def health(session: SessionDep):
    """Report each component by probing it, not by reading its configuration.

    The previous version answered ``celery: not_configured`` as a constant string —
    true when the worker did not exist, and a lie the moment it did. A health
    endpoint that cannot be wrong is worth more than one that is optimistic.
    """
    db_ok = await ping()
    redis_state = await _probe_redis()
    worker_state = await _probe_workers()
    payload = {
        "status": "ok" if db_ok else "degraded",
        "version": settings.app_version,
        "environment": settings.environment,
        "components": {
            "postgresql": "up" if db_ok else "down",
            "redis": redis_state,
            "celery": worker_state,
            # Which policy is actually enforcing the request budget: "redis" is the
            # shared control, "memory" means each replica counts privately and the
            # effective limit is N times the configured one. Reporting it is the
            # difference between a degraded control and an invisible one.
            "rate_limit": limiter.backend,
            "storage": settings.storage_path,
        },
    }
    return ok(payload)


#: Redis and the worker are optional: the API must boot and serve without them.
#: They are reported as degraded-but-optional rather than taking the site down.


async def _probe_redis() -> str:
    if not settings.redis_url:
        return "not_configured"
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(settings.redis_url, socket_connect_timeout=1)
        try:
            await client.ping()
            return "up"
        finally:
            await client.aclose()
    except Exception:  # noqa: BLE001 - any failure is "down", none is fatal here
        return "down"


async def _probe_workers() -> str:
    """Ask the broker whether any worker is consuming the queue."""
    if not settings.redis_url:
        return "not_configured"
    try:
        from app.worker.celery_app import celery_app

        replies = celery_app.control.ping(timeout=1.0)
        return f"up:{len(replies)}" if replies else "down"
    except Exception:  # noqa: BLE001
        return "down"


@router.get("/kpis", summary="مؤشرات الأداء الحقيقية")
async def kpis(session: SessionDep, principal: PrincipalDep):
    """Live KPIs.

    Computed by ``KpiService`` rather than inline: the scheduled weekly report needs
    the same figures, and two implementations would eventually disagree — leaving
    whichever one an inspector did not read as the wrong answer.
    """
    principal.require("instruments.view")
    department_id = None if principal.is_supervisor() else principal.department_id
    return ok(await KpiService(session).compute(department_id=department_id))

"""Health, readiness and KPI endpoints.

KPIs are computed from live rows — the specification forbids synthetic numbers.
"""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from app.api.deps import PrincipalDep, SessionDep
from app.core.config import get_settings
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
    # The request already holds a connection. Asking a *second* one whether the database
    # is up doubles what a health probe costs the pooler, and on a plan with fifteen
    # clients that is how a health check starts causing the outage it is meant to detect.
    db_ok = await _session_is_alive(session)
    checks = {"database": db_ok, "cache": None, "workers": None}
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
    db_ok = await _session_is_alive(session)
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
            # the backend matters more than the path: "filesystem" on a serverless
            # platform means the evidence is in /tmp and will not survive the instance
            "storage": f"{settings.storage_path} ({settings.blob_backend})",
            # A managed pooler allows a fixed number of clients across *all* instances
            # (Supabase session mode: 15). Publishing the per-instance pool is what makes
            # that arithmetic possible before it is learned from EMAXCONNSESSION.
            "db_pool": f"{settings.db_pool_size}+{settings.db_max_overflow} per instance",
            # Prepared statements must be off behind a realistic pooler; publishing the
            # *effective* setting is how an operator confirms it in the deployment that is
            # actually serving, not in the source they are reading.
            "db_statements": _statement_cache_state(),
        },
    }
    return ok(payload)


async def _session_is_alive(session) -> bool:  # noqa: ANN001 - AsyncSession, kept loose
    """Is the database answering *this* session? One connection, the one already held."""
    try:
        await session.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # noqa: BLE001 - a health probe reports, never raises
        from app.core.logging import get_logger

        get_logger("sbdma.health").warning("health database probe failed: %s", exc)
        return False


def _statement_cache_state() -> str:
    """``uncached`` when the live engine disables prepared statements, ``cached`` if not."""
    from app.core.database import _connect_args

    if _connect_args.get("statement_cache_size") == 0 and (
        _connect_args.get("prepared_statement_cache_size") == 0
    ):
        return "uncached"
    return "cached"


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

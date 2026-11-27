"""API v1 router aggregation."""

from fastapi import APIRouter

from app.api.v1 import (
    auth,
    branding,
    catalogue,
    deviations,
    flow_rate,
    health,
    internal,
    notifications,
    reference_manual,
    reports,
    runs,
    test_workbench,
    users,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
# the letterhead is public by design: the sign-in screen shows it too
api_router.include_router(branding.router)
api_router.include_router(runs.router)
api_router.include_router(catalogue.router)
api_router.include_router(reports.router)
api_router.include_router(reference_manual.router)
api_router.include_router(flow_rate.router)
# per-test definition + live recomputation for the unit workbench
api_router.include_router(test_workbench.router)
api_router.include_router(users.router)
api_router.include_router(deviations.router)
api_router.include_router(notifications.router)
# scheduled work for serverless deployments — guarded by CRON_SECRET, not by a session
api_router.include_router(internal.router)

__all__ = ["api_router"]

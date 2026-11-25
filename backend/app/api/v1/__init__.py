"""API v1 router aggregation."""

from fastapi import APIRouter

from app.api.v1 import auth, catalogue, health, reports, runs, users

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(runs.router)
api_router.include_router(catalogue.router)
api_router.include_router(reports.router)
api_router.include_router(users.router)

__all__ = ["api_router"]

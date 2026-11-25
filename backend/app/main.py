"""FastAPI application entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse

from app.api.middleware import RateLimitMiddleware, RequestContextMiddleware
from app.api.v1 import api_router
from app.core.config import get_settings
from app.core.database import engine
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.ratelimit import limiter

settings = get_settings()
configure_logging(settings.log_level, as_json=settings.log_json)
log = get_logger("sbdma.startup")


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ANN201
    log.info(
        "starting",
        extra={
            "extra_fields": {
                "environment": settings.environment,
                "api_prefix": settings.api_prefix,
                "version": settings.app_version,
            }
        },
    )
    yield
    await limiter.aclose()
    await engine.dispose()
    log.info("stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title="SBDMA Laboratory Calibration & OQ Platform",
        version=settings.app_version,
        description=(
            "نظام إدارة ومعايرة الأجهزة المخبرية — الهيئة العليا للأدوية والمستحضرات الطبية\n\n"
            "ISO/IEC 17025 · 21 CFR Part 11 · ALCOA+"
        ),
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-Id"],
        expose_headers=["X-Request-Id", "X-RateLimit-Remaining", "X-Response-Time-ms"],
    )

    register_exception_handlers(app)
    app.include_router(api_router, prefix=settings.api_prefix)

    @app.get("/", include_in_schema=False)
    async def root():
        return RedirectResponse("/api/docs")

    @app.get("/healthz", include_in_schema=False)
    async def healthz():
        return JSONResponse({"status": "ok"})

    return app


app = create_app()

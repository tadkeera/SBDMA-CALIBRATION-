"""Request correlation, security headers and rate limiting.

The counting itself lives in :mod:`app.core.ratelimit` so the window is shared by
every replica rather than kept per process; this module only decides *which* budget
a request draws from, and how a refusal is phrased.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.core.config import get_settings
from app.core.logging import get_logger, request_id_ctx
from app.core.ratelimit import limiter

log = get_logger("sbdma.http")


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        rid = request.headers.get("X-Request-Id") or str(uuid.uuid4())
        request_id_ctx.set(rid)
        started = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - started) * 1000
        response.headers["X-Request-Id"] = rid
        response.headers["X-Response-Time-ms"] = f"{elapsed_ms:.1f}"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Cache-Control"] = response.headers.get("Cache-Control", "no-store")
        if request.url.path.startswith("/api/"):
            log.info(
                "request",
                extra={
                    "extra_fields": {
                        "method": request.method,
                        "path": request.url.path,
                        "status": response.status_code,
                        "ms": round(elapsed_ms, 1),
                    }
                },
            )
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Auth endpoints get a much tighter budget than the general API.

    Two exemptions, both deliberate:

    * ``/healthz`` and ``/api/v1/health*`` — the probes are the control plane. A
      rate-limited health check turns a broker outage into an outage report that
      cannot be delivered, and a Kubernetes liveness probe that is refused would
      restart a healthy pod.
    * anything outside the API prefix — the static frontend is served by nginx.
    """

    def __init__(self, app) -> None:  # noqa: ANN001
        super().__init__(app)
        self.settings = get_settings()

    def _budget(self, path: str) -> int | None:
        if path.startswith("/healthz"):
            return None
        if path.startswith(f"{self.settings.api_prefix}/health"):
            return None
        if path.startswith(f"{self.settings.api_prefix}/auth/"):
            return self.settings.rate_limit_auth_per_minute
        if path.startswith(self.settings.api_prefix):
            return self.settings.rate_limit_per_minute
        return None

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        limit = self._budget(request.url.path)
        if limit is None:
            return await call_next(request)

        client = request.client.host if request.client else "unknown"
        # The route is part of the key so a burst of ordinary reads cannot consume
        # the (much smaller) sign-in budget, and vice versa.
        decision = await limiter.acquire(
            f"{client}:{request.url.path}",
            limit,
            window_seconds=self.settings.rate_limit_window_seconds,
        )
        if not decision.allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "success": False,
                    "data": None,
                    "meta": {"backend": decision.backend},
                    "errors": [
                        {
                            "code": "RATE_LIMITED",
                            "field": None,
                            "message_ar": "تم تجاوز حد الطلبات المسموح — أعد المحاولة بعد دقيقة",
                            "message_en": "Rate limit exceeded — retry in a minute",
                            "details": {"backend": decision.backend},
                        }
                    ],
                },
                headers={
                    "Retry-After": str(self.settings.rate_limit_window_seconds),
                    "X-Request-Id": request_id_ctx.get(),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Backend": decision.backend,
                },
            )
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(decision.remaining)
        response.headers["X-RateLimit-Backend"] = decision.backend
        return response

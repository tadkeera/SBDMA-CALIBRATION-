"""Request correlation, security headers and in-process rate limiting.

Redis-backed rate limiting is used in production; the in-memory fallback keeps a
single-node deployment safe and is explicitly reported by /health.
"""

from __future__ import annotations

import time
import uuid
from collections import defaultdict, deque
from collections.abc import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.core.config import get_settings
from app.core.logging import get_logger, request_id_ctx

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


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, limit: int, window_seconds: int = 60) -> tuple[bool, int]:
        now = time.monotonic()
        bucket = self._hits[key]
        while bucket and now - bucket[0] > window_seconds:
            bucket.popleft()
        if len(bucket) >= limit:
            return False, 0
        bucket.append(now)
        return True, limit - len(bucket)

    def reset(self) -> None:
        self._hits.clear()


limiter = SlidingWindowLimiter()


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Auth endpoints get a much tighter budget than the general API."""

    def __init__(self, app) -> None:  # noqa: ANN001
        super().__init__(app)
        self.settings = get_settings()

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path
        if path.startswith(f"{self.settings.api_prefix}/auth/"):
            limit = self.settings.rate_limit_auth_per_minute
        elif path.startswith(self.settings.api_prefix):
            limit = self.settings.rate_limit_per_minute
        else:
            return await call_next(request)

        client = request.client.host if request.client else "unknown"
        allowed, remaining = limiter.allow(f"{client}:{path}", limit)
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "success": False,
                    "data": None,
                    "meta": None,
                    "errors": [
                        {
                            "code": "RATE_LIMITED",
                            "field": None,
                            "message_ar": "تم تجاوز حد الطلبات المسموح — أعد المحاولة بعد دقيقة",
                            "message_en": "Rate limit exceeded — retry in a minute",
                            "details": {},
                        }
                    ],
                },
                headers={"Retry-After": "60", "X-Request-Id": request_id_ctx.get()},
            )
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response

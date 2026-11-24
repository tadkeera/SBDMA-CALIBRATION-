"""Structured logging with request correlation (21 CFR Part 11 traceability)."""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")
user_ctx: ContextVar[str] = ContextVar("user", default="anonymous")
department_ctx: ContextVar[str] = ContextVar("department", default="-")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_ctx.get(),
            "user": user_ctx.get(),
            "department": department_ctx.get(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        for key, value in getattr(record, "extra_fields", {}).items():
            payload[key] = value
        return json.dumps(payload, ensure_ascii=False)


class PlainFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return (
            f"{datetime.now(timezone.utc).isoformat()} {record.levelname:<7} "
            f"[{request_id_ctx.get()}] {record.name}: {record.getMessage()}"
        )


def configure_logging(level: str = "INFO", as_json: bool = True) -> None:
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if as_json else PlainFormatter())
    root.addHandler(handler)
    root.setLevel(level.upper())
    # noisy third-party loggers are tamed so audit-relevant lines stay readable
    for noisy in ("uvicorn.access", "sqlalchemy.engine", "asyncpg"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)

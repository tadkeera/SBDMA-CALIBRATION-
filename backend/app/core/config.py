"""Centralised configuration.

Fail-fast policy: the application refuses to boot with a missing or weak secret.
No secret ever lives in source control (master spec §06.4).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PLACEHOLDER_MARKERS = ("change_me", "changeme", "secret_key", "password", "example")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- application ---
    app_name: str = "SBDMA Laboratory Calibration & OQ Platform"
    # kept in step with /VERSION; surfaced by /health and the OpenAPI metadata
    app_version: str = "1.3.0"
    environment: Literal["development", "test", "staging", "production"] = "development"
    api_prefix: str = "/api/v1"
    debug: bool = False

    # --- database ---
    database_url: str = "postgresql+asyncpg://sbdma:sbdma_dev_pw@127.0.0.1:5432/sbdma_calibration"
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_recycle_seconds: int = 1800
    db_statement_timeout_ms: int = 30_000

    # --- security ---
    jwt_secret: str = Field(default="dev_only_insecure_secret_replace_before_production")
    jwt_algorithm: str = "HS256"
    jwt_access_ttl_minutes: int = 30
    jwt_refresh_ttl_days: int = 7
    argon2_time_cost: int = 3
    argon2_memory_cost: int = 65536
    argon2_parallelism: int = 4
    max_failed_logins: int = 5
    lockout_minutes: int = 15
    cookie_secure: bool = True
    cookie_samesite: Literal["strict", "lax", "none"] = "strict"

    # --- cors ---
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # --- rate limiting ---
    rate_limit_per_minute: int = 120
    rate_limit_auth_per_minute: int = 5

    # --- integrations (optional, never required to boot) ---
    redis_url: str | None = None
    smtp_host: str | None = None
    storage_path: str = "/tmp/sbdma-storage"
    max_upload_mb: int = 25

    # --- observability ---
    log_level: str = "INFO"
    log_json: bool = True

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @field_validator("jwt_secret")
    @classmethod
    def _reject_weak_secret(cls, v: str, info):  # noqa: ANN001
        env = (info.data or {}).get("environment", "development")
        lowered = v.lower()
        weak = len(v) < 32 or any(m in lowered for m in PLACEHOLDER_MARKERS)
        if env in ("production", "staging") and weak:
            raise ValueError(
                "JWT_SECRET must be >=32 chars and must not contain placeholder words "
                "in staging/production"
            )
        return v

    @field_validator("database_url")
    @classmethod
    def _require_async_driver(cls, v: str) -> str:
        if not v.startswith("postgresql+asyncpg://"):
            raise ValueError("DATABASE_URL must use the postgresql+asyncpg:// driver")
        return v

    @property
    def sync_database_url(self) -> str:
        """Alembic runs migrations on a sync engine."""
        return self.database_url.replace("postgresql+asyncpg://", "postgresql+psycopg://")

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()

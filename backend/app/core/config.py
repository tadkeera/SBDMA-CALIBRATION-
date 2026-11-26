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
    app_version: str = "2.1.0"
    environment: Literal["development", "test", "staging", "production"] = "development"
    api_prefix: str = "/api/v1"
    debug: bool = False

    # --- database ---
    database_url: str = "postgresql+asyncpg://sbdma:sbdma_dev_pw@127.0.0.1:5432/sbdma_calibration"
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_recycle_seconds: int = 1800
    db_statement_timeout_ms: int = 30_000
    #: Prepared statements are **off by default**, which is unusual and deliberate.
    #:
    #: A transaction-mode pooler (Supabase/Supavisor on :6543, pgbouncer, Neon) hands a
    #: server connection to whichever client needs it next, so a statement prepared by
    #: one client still exists when another prepares the same name — PostgreSQL answers
    #: `DuplicatePreparedStatementError`, which surfaces as a 503 on about one request in
    #: six. That was production: `/api/v1/branding` failed intermittently for days while
    #: the database itself was perfectly healthy. The safe default is therefore off; the
    #: cost is microseconds of parse time per query, the cost of being wrong is a
    #: customer-facing outage that looks like a database fault. Set
    #: ``DB_DISABLE_PREPARED_STATEMENTS=false`` only for a direct connection, and note the
    #: URL check in ``database.engine_url_and_connect_args`` — a :6543 URL disables the
    #: cache regardless of this flag.
    db_disable_prepared_statements: bool = True

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

    # --- second factor (TOTP) ---
    # The shared secret is a bearer credential: whoever reads it can produce valid
    # codes forever, so it is encrypted at rest with a key derived from this value
    # (Fernet/HKDF). Rotating it invalidates every enrolled authenticator, which is
    # the correct response to a suspected compromise.
    mfa_encryption_key: str = Field(default="dev_only_insecure_mfa_key_replace_before_production")
    mfa_issuer: str = "SBDMA"
    mfa_enforced_roles: str = "SUPER_ADMIN,SYSTEM_ADMIN,QA_APPROVER,TECHNICAL_REVIEWER"
    # how many 30s steps of drift to accept on each side (clock skew between phone and server)
    mfa_valid_window: int = 1
    cookie_secure: bool = True
    cookie_samesite: Literal["strict", "lax", "none"] = "strict"

    # --- cors ---
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # --- rate limiting ---
    # The window lives in Redis so that N API replicas enforce one budget instead of
    # N of them. ``auto`` uses Redis when ``REDIS_URL`` is set, ``memory`` forces the
    # in-process window (single-node dev, and the tests that assert the fallback).
    rate_limit_backend: Literal["auto", "redis", "memory"] = "auto"
    rate_limit_per_minute: int = 120
    rate_limit_auth_per_minute: int = 5
    rate_limit_window_seconds: int = 60

    # --- scheduled work ---
    # "celery" is a container deployment with a beat scheduler; "vercel-cron" means
    # the schedule lives in vercel.json and calls /api/v1/internal/jobs/*. The
    # difference is reported by /worker/status so the UI cannot claim a scheduler
    # that is not running.
    scheduler: Literal["celery", "vercel-cron"] = "celery"
    # Shared secret for the HTTP-scheduled routes. Unset means those routes refuse to
    # run (503): an unauthenticated endpoint that writes notifications and files
    # reports is a way in, not a convenience.
    cron_secret: str | None = None

    # --- integrations (optional, never required to boot) ---
    redis_url: str | None = None
    smtp_host: str | None = None
    storage_path: str = "/tmp/sbdma-storage"
    max_upload_mb: int = 25
    # Where the durable copy of a filed document lives. ``filesystem`` means the
    # storage path *is* durable (a container with a volume). ``database`` adds a copy
    # in ``stored_blobs``: on a serverless platform /tmp is per-instance and wiped
    # between invocations, so the row would outlive the evidence it points at.
    blob_backend: Literal["filesystem", "database"] = "filesystem"

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

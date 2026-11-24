"""Immutable audit trail, notifications and system settings."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import INET, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, jsonb_column, sha256_column


class AuditLog(Base):
    """Append-only. PostgreSQL triggers reject UPDATE and DELETE (see Alembic).

    Rows are chained: hash = SHA-256(prev_hash | at | actor_id | action | entity |
    entity_id | old | new | reason). The chain is verified by the QA dashboard and
    by ``AuditService.verify_chain``.
    """

    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lab_departments.id"), index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), index=True
    )
    actor_label: Mapped[str] = mapped_column(String(120), nullable=False)
    role_label: Mapped[str | None] = mapped_column(String(48))
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    old_values: Mapped[dict[str, Any] | None] = jsonb_column()
    new_values: Mapped[dict[str, Any] | None] = jsonb_column()
    reason: Mapped[str | None] = mapped_column(Text)
    ip_address: Mapped[str | None] = mapped_column(INET)
    request_id: Mapped[str | None] = mapped_column(String(64))
    prev_hash: Mapped[str] = sha256_column(nullable=False)
    hash: Mapped[str] = sha256_column(nullable=False, unique=True)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), index=True
    )
    channel: Mapped[str] = mapped_column(String(24), nullable=False)  # in_app / email / sms
    severity: Mapped[str] = mapped_column(String(16), default="info", nullable=False)
    title_ar: Mapped[str] = mapped_column(String(255), nullable=False)
    body_ar: Mapped[str | None] = mapped_column(Text)
    payload_jsonb: Mapped[dict | None] = jsonb_column()
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(96), primary_key=True)
    category: Mapped[str] = mapped_column(String(48), nullable=False, default="general")
    value_jsonb: Mapped[dict | None] = jsonb_column()
    description_ar: Mapped[str | None] = mapped_column(Text)
    is_secret: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

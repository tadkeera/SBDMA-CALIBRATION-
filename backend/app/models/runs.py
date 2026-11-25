"""Calibration runs, per-test results, attachments and maintenance tickets."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    Base,
    Timestamped,
    UUIDPrimaryKey,
    jsonb_column,
    measurement,
    sha256_column,
)

RUN_TYPES = ("ROUTINE", "POST_BREAKDOWN", "INSTALLATION", "ANNUAL")
RESULT_STATUSES = ("PASS", "FAIL", "UNDER_REVIEW", "INCOMPLETE")
TICKET_STATUSES = ("OPEN", "IN_PROGRESS", "RESOLVED", "CLOSED")


class CalibrationRun(Base, UUIDPrimaryKey, Timestamped):
    __tablename__ = "calibration_runs"
    __table_args__ = (
        CheckConstraint("ambient_temp_c IS NULL OR ambient_temp_c > -50", name="ambient_temp_sane"),
    )

    execution_code: Mapped[str] = mapped_column(String(48), unique=True, nullable=False, index=True)
    department_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lab_departments.id"), nullable=False, index=True
    )
    instrument_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("instruments.id"), nullable=False, index=True
    )
    protocol_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calibration_protocols.id"), nullable=False
    )
    reference_equipment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reference_equipment.id")
    )
    run_type: Mapped[str] = mapped_column(
        Enum(*RUN_TYPES, name="run_type"), default="ROUTINE", nullable=False
    )
    ambient_temp_c: Mapped[float | None] = measurement()
    ambient_humidity: Mapped[float | None] = measurement()
    limit_source_policy: Mapped[str] = mapped_column(String(32), default="AUTHORITY_LIMIT", nullable=False)
    overall_status: Mapped[str] = mapped_column(
        Enum(*RESULT_STATUSES, name="overall_status"), default="INCOMPLETE", nullable=False, index=True
    )
    analyst_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    qa_approver_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    qa_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    certificate_hash: Mapped[str | None] = sha256_column()
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    breakdown_component: Mapped[str | None] = mapped_column(String(48))
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    results: Mapped[list["CalibrationTestResult"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        CheckConstraint("ambient_temp_c IS NULL OR ambient_temp_c > -50", name="ambient_temp_sane"),
        # Segregation of duties enforced at the storage layer too (21 CFR Part 11).
        CheckConstraint(
            "reviewer_id IS NULL OR reviewer_id <> analyst_id",
            name="sod_reviewer_differs",
        ),
        CheckConstraint(
            "qa_approver_id IS NULL OR qa_approver_id <> analyst_id",
            name="sod_qa_differs_analyst",
        ),
        CheckConstraint(
            "qa_approver_id IS NULL OR reviewer_id IS NULL OR qa_approver_id <> reviewer_id",
            name="sod_qa_differs_reviewer",
        ),
        # A locked run must carry a certificate fingerprint.
        CheckConstraint(
            "is_locked = FALSE OR certificate_hash IS NOT NULL",
            name="locked_requires_hash",
        ),
    )


class CalibrationTestResult(Base, UUIDPrimaryKey, Timestamped):
    __tablename__ = "calibration_test_results"

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calibration_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    test_definition_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("test_definitions.id"), nullable=False
    )
    test_code: Mapped[str] = mapped_column(String(16), nullable=False)
    applied_limit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("acceptance_limits.id")
    )
    applied_limit_source: Mapped[str | None] = mapped_column(String(32))
    raw_inputs_jsonb: Mapped[dict[str, Any] | None] = jsonb_column()
    calculated_outputs_jsonb: Mapped[dict[str, Any] | None] = jsonb_column()
    metric_evaluations_jsonb: Mapped[list | None] = jsonb_column()
    chart_series_jsonb: Mapped[dict | None] = jsonb_column()
    data_source: Mapped[str] = mapped_column(String(32), default="MANUAL", nullable=False)
    status: Mapped[str] = mapped_column(
        Enum(*RESULT_STATUSES, name="result_status"), default="INCOMPLETE", nullable=False
    )
    notes_ar: Mapped[str | None] = mapped_column(Text)
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    run: Mapped[CalibrationRun] = relationship(back_populates="results")


class CalibrationAttachment(Base, UUIDPrimaryKey, Timestamped):
    """A signed evidence file, addressed by its own SHA-256.

    GxP rule: nothing that was filed as evidence may be edited or deleted — not by
    the API and not by SQL. A correction is a *new* attachment that supersedes the
    old one, and both stay readable. The database enforces this (trg_attachment_immutable).
    """

    __tablename__ = "calibration_attachments"

    instrument_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("instruments.id"), index=True
    )
    test_result_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calibration_test_results.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calibration_runs.id", ondelete="CASCADE"), index=True
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_path: Mapped[str] = mapped_column(String(512), nullable=False)
    sha256_checksum: Mapped[str] = sha256_column(nullable=False)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    # human-readable justification, required by ALCOA+ for every filed record
    description_ar: Mapped[str | None] = mapped_column(Text)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calibration_attachments.id")
    )

    __table_args__ = (
        CheckConstraint("size_bytes > 0", name="attachment_size_positive"),
        CheckConstraint(
            "instrument_id IS NOT NULL OR run_id IS NOT NULL OR test_result_id IS NOT NULL",
            name="attachment_has_owner",
        ),
    )


class MaintenanceTicket(Base, UUIDPrimaryKey, Timestamped):
    __tablename__ = "maintenance_tickets"

    instrument_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("instruments.id"), nullable=False, index=True
    )
    component_affected: Mapped[str] = mapped_column(String(48), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    required_tests_jsonb: Mapped[list | None] = jsonb_column()
    status: Mapped[str] = mapped_column(
        Enum(*TICKET_STATUSES, name="ticket_status"), default="OPEN", nullable=False, index=True
    )
    reported_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

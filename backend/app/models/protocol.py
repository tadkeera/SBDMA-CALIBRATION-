"""Protocols, test definitions, acceptance limits and formulas."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamped, UUIDPrimaryKey, jsonb_column, measurement

LIMIT_SOURCES = (
    "INTEGRITY_GUIDE_CH2",
    "IOQ_PROTOCOL_CH4",
    "MANUFACTURER_SPEC",
    "SOP_LIMIT",
    "AUTHORITY_LIMIT",
)
LIMIT_OPERATORS = ("lte", "gte", "abs_lte", "between", "equals")
APPROVAL_STATUSES = ("UNAPPROVED", "APPROVED", "CONFLICT_REQUIRES_QA", "REJECTED")
PROTOCOL_STATUSES = ("DRAFT", "UNDER_REVIEW", "APPROVED", "SUPERSEDED", "RETIRED")


class CalibrationProtocol(Base, UUIDPrimaryKey, Timestamped):
    __tablename__ = "calibration_protocols"

    protocol_code: Mapped[str] = mapped_column(String(64), nullable=False)
    instrument_category: Mapped[str] = mapped_column(String(64), nullable=False)
    title_ar: Mapped[str] = mapped_column(String(255), nullable=False)
    title_en: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        Enum(*PROTOCOL_STATUSES, name="protocol_status"), default="DRAFT", nullable=False
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes_ar: Mapped[str | None] = mapped_column(Text)

    tests: Mapped[list["TestDefinition"]] = relationship(
        back_populates="protocol", order_by="TestDefinition.sequence_order", lazy="selectin"
    )

    __table_args__ = (UniqueConstraint("protocol_code", "version", name="uq_protocol_code_version"),)


class TestDefinition(Base, UUIDPrimaryKey, Timestamped):
    __tablename__ = "test_definitions"
    __table_args__ = (UniqueConstraint("protocol_id", "test_code", name="uq_test_protocol_code"),)

    protocol_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calibration_protocols.id", ondelete="CASCADE"), nullable=False
    )
    test_code: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    sequence_order: Mapped[int] = mapped_column(Integer, nullable=False)
    module: Mapped[str] = mapped_column(String(32), nullable=False)
    name_ar: Mapped[str] = mapped_column(String(255), nullable=False)
    name_en: Mapped[str] = mapped_column(String(255), nullable=False)
    standard_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    procedure_ar: Mapped[list | None] = jsonb_column()
    procedure_en: Mapped[list | None] = jsonb_column()
    input_schema_jsonb: Mapped[dict | None] = jsonb_column()
    chart_config_jsonb: Mapped[dict | None] = jsonb_column()
    is_mandatory: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    protocol: Mapped[CalibrationProtocol] = relationship(back_populates="tests")
    limits: Mapped[list["AcceptanceLimit"]] = relationship(
        back_populates="test_definition", lazy="selectin"
    )
    formulas: Mapped[list["FormulaDefinition"]] = relationship(
        back_populates="test_definition", lazy="selectin"
    )


class AcceptanceLimit(Base, UUIDPrimaryKey, Timestamped):
    __tablename__ = "acceptance_limits"
    __table_args__ = (
        UniqueConstraint(
            "test_definition_id", "metric_key", "source_type", name="uq_limit_test_metric_source"
        ),
        CheckConstraint("min_value IS NOT NULL OR max_value IS NOT NULL", name="needs_bound"),
    )

    test_definition_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("test_definitions.id", ondelete="CASCADE"), nullable=False
    )
    metric_key: Mapped[str] = mapped_column(String(64), nullable=False)
    source_type: Mapped[str] = mapped_column(
        Enum(*LIMIT_SOURCES, name="limit_source"), nullable=False, index=True
    )
    operator: Mapped[str] = mapped_column(Enum(*LIMIT_OPERATORS, name="limit_operator"), nullable=False)
    min_value: Mapped[float | None] = measurement()
    max_value: Mapped[float | None] = measurement()
    unit: Mapped[str] = mapped_column(String(24), nullable=False)
    approval_status: Mapped[str] = mapped_column(
        Enum(*APPROVAL_STATUSES, name="approval_status"), default="UNAPPROVED", nullable=False
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note_ar: Mapped[str | None] = mapped_column(Text)
    flagged: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    test_definition: Mapped[TestDefinition] = relationship(back_populates="limits")


class FormulaDefinition(Base, UUIDPrimaryKey, Timestamped):
    __tablename__ = "formula_definitions"
    __table_args__ = (
        UniqueConstraint("test_definition_id", "formula_key", "version", name="uq_formula_test_key_ver"),
    )

    test_definition_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("test_definitions.id", ondelete="CASCADE"), nullable=False
    )
    formula_key: Mapped[str] = mapped_column(String(64), nullable=False)
    description_ar: Mapped[str] = mapped_column(Text, nullable=False)
    description_en: Mapped[str] = mapped_column(Text, nullable=False)
    expression_text: Mapped[str] = mapped_column(Text, nullable=False)
    variables_jsonb: Mapped[dict | None] = jsonb_column()
    rounding_decimals: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))

    test_definition: Mapped[TestDefinition] = relationship(back_populates="formulas")

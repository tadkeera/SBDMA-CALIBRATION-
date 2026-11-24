"""Instruments, reference equipment and reference standards."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, Enum, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    SoftDeletable,
    Timestamped,
    UUIDPrimaryKey,
    jsonb_column,
    measurement,
)

INSTRUMENT_STATUS = ("ACTIVE", "OUT_OF_SERVICE", "UNDER_MAINTENANCE")


class Instrument(Base, UUIDPrimaryKey, Timestamped, SoftDeletable):
    __tablename__ = "instruments"

    department_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lab_departments.id"), nullable=False, index=True
    )
    asset_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    manufacturer: Mapped[str] = mapped_column(String(120), nullable=False)
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    part_number: Mapped[str | None] = mapped_column(String(80))
    serial_number: Mapped[str] = mapped_column(String(80), nullable=False)
    software_version: Mapped[str | None] = mapped_column(String(80))
    configuration_jsonb: Mapped[dict | None] = jsonb_column()
    calibration_freq_days: Mapped[int] = mapped_column(Integer, default=180, nullable=False)
    last_calibration_date: Mapped[date | None] = mapped_column(Date)
    next_due_date: Mapped[date | None] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(
        Enum(*INSTRUMENT_STATUS, name="instrument_status"), default="ACTIVE", nullable=False
    )
    d2_lamp_hours: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    __table_args__ = (
        CheckConstraint("calibration_freq_days > 0", name="freq_positive"),
        CheckConstraint("d2_lamp_hours >= 0", name="lamp_hours_non_negative"),
    )


class ReferenceEquipment(Base, UUIDPrimaryKey, Timestamped):
    __tablename__ = "reference_equipment"

    department_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lab_departments.id"), nullable=False, index=True
    )
    equipment_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name_ar: Mapped[str] = mapped_column(String(190), nullable=False)
    name_en: Mapped[str] = mapped_column(String(190), nullable=False)
    serial_number: Mapped[str] = mapped_column(String(80), nullable=False)
    certificate_no: Mapped[str] = mapped_column(String(80), nullable=False)
    calibrated_by: Mapped[str] = mapped_column(String(190), nullable=False)
    calibration_date: Mapped[date] = mapped_column(Date, nullable=False)
    expiry_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    correction_table_jsonb: Mapped[list | None] = jsonb_column()
    uncertainty: Mapped[float | None] = measurement()
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    __table_args__ = (
        CheckConstraint("expiry_date > calibration_date", name="expiry_after_calibration"),
    )


class ReferenceStandard(Base, UUIDPrimaryKey, Timestamped):
    __tablename__ = "reference_standards"

    department_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lab_departments.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(190), nullable=False)
    part_or_cat_no: Mapped[str | None] = mapped_column(String(80))
    lot_number: Mapped[str] = mapped_column(String(80), nullable=False)
    purity_percent: Mapped[float] = measurement(nullable=False)
    prepared_at: Mapped[date | None] = mapped_column(Date)
    expiry_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    __table_args__ = (
        CheckConstraint("purity_percent > 0 AND purity_percent <= 100", name="purity_range"),
    )

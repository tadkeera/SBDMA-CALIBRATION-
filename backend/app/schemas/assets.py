from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import ORMModel


class InstrumentCreate(BaseModel):
    """A unit of laboratory equipment.

    ``label_ar`` / ``label_en`` are the name the laboratory calls the unit — "HPLC (2)".
    When they are omitted the service composes them from the category and the next free
    circle number, so a caller that only knows the maker's details still gets a tile
    whose name matches the rest of the gallery.
    """

    #: Both are optional on purpose. The department defaults to the caller's own (a
    #: department-scoped principal may not register a unit into someone else's lab), and
    #: the asset code defaults to ``CATEGORY-NN`` from the circle number the server
    #: assigns — the register's identity must not depend on the operator inventing a code.
    department_id: uuid.UUID | None = None
    asset_code: str | None = Field(default=None, min_length=3, max_length=64)
    category: str = Field(min_length=2, max_length=64)
    manufacturer: str = Field(min_length=2, max_length=120)
    model: str = Field(min_length=1, max_length=160)
    part_number: str | None = Field(default=None, max_length=80)
    serial_number: str = Field(min_length=2, max_length=80)
    software_version: str | None = Field(default=None, max_length=80)
    configuration_jsonb: dict[str, Any] | None = None
    calibration_freq_days: int = Field(default=180, ge=1, le=3650)
    last_calibration_date: date | None = None
    d2_lamp_hours: int = Field(default=0, ge=0, le=100000)
    label_ar: str | None = Field(default=None, max_length=80)
    label_en: str | None = Field(default=None, max_length=80)


class InstrumentUpdate(BaseModel):
    category: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    part_number: str | None = None
    software_version: str | None = None
    configuration_jsonb: dict[str, Any] | None = None
    calibration_freq_days: int | None = Field(default=None, ge=1, le=3650)
    last_calibration_date: date | None = None
    d2_lamp_hours: int | None = Field(default=None, ge=0)
    status: Literal["ACTIVE", "OUT_OF_SERVICE", "UNDER_MAINTENANCE"] | None = None
    label_ar: str | None = Field(default=None, max_length=80)
    label_en: str | None = Field(default=None, max_length=80)


class InstrumentOut(ORMModel):
    id: uuid.UUID
    department_id: uuid.UUID
    asset_code: str
    category: str
    manufacturer: str
    model: str
    part_number: str | None
    serial_number: str
    software_version: str | None
    configuration_jsonb: dict[str, Any] | None
    calibration_freq_days: int
    last_calibration_date: date | None
    next_due_date: date | None
    status: str
    d2_lamp_hours: int
    #: the gallery tile: "HPLC (1)" and the number in the red circle
    label_ar: str | None = None
    label_en: str | None = None
    device_number: int | None = None


class ReferenceEquipmentOut(ORMModel):
    id: uuid.UUID
    department_id: uuid.UUID
    equipment_code: str
    name_ar: str
    name_en: str
    serial_number: str
    certificate_no: str
    calibrated_by: str
    calibration_date: date
    expiry_date: date
    correction_table_jsonb: list | None
    is_active: bool


class ReferenceStandardOut(ORMModel):
    id: uuid.UUID
    department_id: uuid.UUID
    name: str
    lot_number: str
    purity_percent: str
    prepared_at: date | None
    expiry_date: date


class LimitOut(ORMModel):
    id: uuid.UUID
    metric_key: str
    source_type: str
    operator: str
    min_value: str | None
    max_value: str | None
    unit: str
    approval_status: str
    note_ar: str | None
    flagged: bool


class FormulaOut(ORMModel):
    id: uuid.UUID
    formula_key: str
    description_ar: str
    description_en: str
    expression_text: str
    rounding_decimals: int
    version: int
    is_active: bool


class TestDefinitionOut(ORMModel):
    id: uuid.UUID
    test_code: str
    sequence_order: int
    module: str
    name_ar: str
    name_en: str
    standard_ref: str
    procedure_ar: list | None
    procedure_en: list | None = None
    input_schema_jsonb: dict[str, Any] | None
    chart_config_jsonb: dict[str, Any] | None
    is_mandatory: bool
    is_active: bool = True
    reference_jsonb: dict[str, Any] | None = None
    limits: list[LimitOut] = Field(default_factory=list)
    formulas: list[FormulaOut] = Field(default_factory=list)


class TestStatusUpdate(BaseModel):
    """Payload for the Control Center enable/disable switch.

    ``reason`` is mandatory: taking a test out of routine use is a governance decision
    and the audit trail must record why, not only what.
    """

    is_active: bool
    reason: str = Field(min_length=8, max_length=500)


class TestStatusOut(ORMModel):
    test_code: str
    name_ar: str
    name_en: str
    module: str
    sequence_order: int
    standard_ref: str
    is_active: bool
    is_mandatory: bool
    limits_count: int = 0
    updated_at: datetime | None = None


class ProtocolOut(ORMModel):
    id: uuid.UUID
    protocol_code: str
    instrument_category: str
    title_ar: str
    title_en: str
    version: str
    status: str
    tests: list[TestDefinitionOut] = Field(default_factory=list)


class LimitApproveRequest(BaseModel):
    approval_status: Literal["APPROVED", "UNAPPROVED", "CONFLICT_REQUIRES_QA", "REJECTED"]
    note_ar: str | None = Field(default=None, max_length=1000)


class MaintenanceTicketCreate(BaseModel):
    instrument_id: uuid.UUID
    component_affected: str = Field(min_length=2, max_length=48)
    description: str = Field(min_length=8, max_length=4000)


class MaintenanceTicketOut(ORMModel):
    id: uuid.UUID
    instrument_id: uuid.UUID
    component_affected: str
    description: str
    required_tests_jsonb: list | None
    status: str
    reported_by: uuid.UUID | None
    resolved_by: uuid.UUID | None
    resolved_at: Any | None = None


class AuditOut(ORMModel):
    id: uuid.UUID
    at: Any
    actor_label: str
    role_label: str | None
    action: str
    entity_type: str
    entity_id: str
    reason: str | None
    request_id: str | None
    prev_hash: str
    hash: str


class PaginationQuery(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=25, ge=1, le=100)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

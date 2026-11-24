from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

RunType = Literal["ROUTINE", "POST_BREAKDOWN", "INSTALLATION", "ANNUAL"]
LimitSource = Literal[
    "INTEGRITY_GUIDE_CH2", "IOQ_PROTOCOL_CH4", "MANUFACTURER_SPEC", "SOP_LIMIT", "AUTHORITY_LIMIT"
]


class RunCreateRequest(BaseModel):
    instrument_id: uuid.UUID
    reference_equipment_id: uuid.UUID | None = None
    run_type: RunType = "ROUTINE"
    ambient_temp_c: float | None = Field(default=None, ge=-50, le=100)
    ambient_humidity: float | None = Field(default=None, ge=0, le=100)
    limit_source_policy: LimitSource = "AUTHORITY_LIMIT"
    breakdown_component: str | None = Field(default=None, max_length=48)
    notes_ar: str | None = Field(default=None, max_length=2000)

    @field_validator("breakdown_component")
    @classmethod
    def _component_required_for_breakdown(cls, v, info):
        if info.data.get("run_type") == "POST_BREAKDOWN" and not v:
            raise ValueError("المكوّن المتعطل مطلوب في تشغيل ما بعد الأعطال")
        return v


class RawInputsPayload(BaseModel):
    """Raw readings keyed by test code then field key.

    Example:
        {"T02": {"set_flow": [0.5, 1, 2], "collected_vol": [5,5,5], "actual_time": [599.9,299.4,150.1]}}
    """

    model_config = ConfigDict(extra="forbid")
    # The concrete structure is validated against the protocol blueprint at execute time.
    tests: dict[str, dict[str, Any]]


class ExecuteRunRequest(BaseModel):
    raw_inputs: dict[str, dict[str, Any]] = Field(default_factory=dict)
    scope_tests: list[str] | None = Field(
        default=None,
        description="Restrict execution to these test codes (post-breakdown matrix). Defaults to all.",
    )


class MetricEvaluationOut(BaseModel):
    metric_key: str
    value: str | None
    unit: str
    applied_limit_id: str | None
    applied_source: str | None
    comparator: str
    limit_text: str
    status: str
    message_ar: str | None = None


class TestResultOut(BaseModel):
    test_code: str
    status: str
    metric_evaluations: list[MetricEvaluationOut]
    notes_ar: str | None = None
    formula_errors: list[str] = Field(default_factory=list)
    outputs: dict[str, Any] = Field(default_factory=dict)
    # Raw inputs exactly as captured and signed at execution time (ALCOA+: original).
    raw_inputs: dict[str, Any] = Field(default_factory=dict)


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    execution_code: str
    instrument_id: uuid.UUID
    instrument_label: str | None = None
    run_type: str
    overall_status: str
    analyst_id: uuid.UUID
    analyst_username: str | None = None
    reviewer_id: uuid.UUID | None = None
    reviewer_username: str | None = None
    qa_approver_id: uuid.UUID | None = None
    qa_approver_username: str | None = None
    limit_source_policy: str
    ambient_temp_c: str | None = None
    ambient_humidity: str | None = None
    certificate_hash: str | None = None
    is_locked: bool
    revision: int
    started_at: datetime
    completed_at: datetime | None = None
    reviewed_at: datetime | None = None
    qa_approved_at: datetime | None = None
    breakdown_component: str | None = None
    results: list[TestResultOut] = Field(default_factory=list)


class RunSummaryOut(BaseModel):
    id: uuid.UUID
    execution_code: str
    instrument_id: uuid.UUID
    overall_status: str
    run_type: str
    analyst_id: uuid.UUID
    is_locked: bool
    started_at: datetime
    completed_at: datetime | None = None

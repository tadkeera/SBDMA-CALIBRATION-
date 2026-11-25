"""Request bodies for the OOS deviation workflow."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.models.deviations import CAPA_ACTIONS, DEVIATION_CLASSES, ROOT_CAUSE_CATEGORIES


class RaiseDeviationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: uuid.UUID
    title: str = Field(min_length=8, max_length=200)
    description: str = Field(min_length=20, max_length=8000)
    #: CRITICAL | MAJOR | MINOR — validated against the enum in the service so the
    #: client receives a domain error rather than a schema error with a raw list.
    classification: str = Field(default="MAJOR")

    def model_post_init(self, _ctx) -> None:  # noqa: ANN001
        if self.classification not in DEVIATION_CLASSES:
            raise ValueError(f"classification must be one of {DEVIATION_CLASSES}")


class StartInvestigationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan: str = Field(min_length=20, max_length=8000)


class InvestigateDeviationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root_cause_category: str
    root_cause: str = Field(min_length=20, max_length=8000)
    immediate_action: str = Field(min_length=10, max_length=8000)

    def model_post_init(self, _ctx) -> None:  # noqa: ANN001
        if self.root_cause_category not in ROOT_CAUSE_CATEGORIES:
            raise ValueError(f"root_cause_category must be one of {ROOT_CAUSE_CATEGORIES}")


class CloseDeviationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capa_action: str
    capa_notes: str = Field(min_length=20, max_length=8000)
    closure_notes: str = Field(min_length=20, max_length=8000)
    #: the passing retest that resolves the deviation, when one was performed
    retest_run_id: uuid.UUID | None = None

    def model_post_init(self, _ctx) -> None:  # noqa: ANN001
        if self.capa_action not in CAPA_ACTIONS:
            raise ValueError(f"capa_action must be one of {CAPA_ACTIONS}")


class CancelDeviationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=20, max_length=2000)

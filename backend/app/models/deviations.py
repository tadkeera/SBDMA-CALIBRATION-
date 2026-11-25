"""OOS deviations — the record that closes the loop on a failing calibration.

A calibration that has failed (or come back INCOMPLETE) cannot be approved. Until
this table existed, the approval path told the operator to "raise an OOS
deviation" and there was nowhere to do it — the system asked for something it did
not offer, so a failed instrument had no route back into service.

The model encodes four rules:

1. **A deviation never rewrites the science.** It references the run; it does not
   alter its results. The failed run stays failed — on record, for ever. Approving
   is still refused; what the deviation provides is the *investigation* and the
   *retest* that produce a new, passing run.
2. **The phases are separate columns with separate actors.** Raise → investigate
   (root cause + immediate action) → close (CAPA + QA decision). Each transition
   demands its own permission, so the person who investigates cannot also declare
   their own investigation adequate.
3. **Status only moves forward.** The allowed transitions are enumerated below;
   anything else is a 409. A closed deviation cannot be reopened — a new one is
   raised, which keeps the history honest.
4. **Nothing is deleted.** Rows are append-only; a database trigger refuses DELETE
   and TRUNCATE, exactly as for the audit chain and attachments.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeletable, Timestamped, UUIDPrimaryKey

#: OPEN → INVESTIGATING → PENDING_VERIFICATION → CLOSED, or CANCELLED before work starts.
DEVIATION_STATUSES = (
    "OPEN",
    "INVESTIGATING",
    "PENDING_VERIFICATION",
    "CLOSED",
    "CANCELLED",
)

#: Which transitions are legal. Anything absent here is refused with 409.
ALLOWED_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "OPEN": ("INVESTIGATING", "CANCELLED"),
    "INVESTIGATING": ("PENDING_VERIFICATION", "CANCELLED"),
    "PENDING_VERIFICATION": ("CLOSED", "INVESTIGATING"),
    "CLOSED": (),
    "CANCELLED": (),
}

#: Classification per ICH Q7 / WHO guidance for out-of-specification results.
DEVIATION_CLASSES = ("CRITICAL", "MAJOR", "MINOR")

#: What the investigation concluded. The retest is the only path that can produce
#: a passing run; the others close the instrument's story without one.
ROOT_CAUSE_CATEGORIES = (
    "INSTRUMENT_FAULT",
    "METHOD_ERROR",
    "OPERATOR_ERROR",
    "MATERIAL_STANDARD",
    "ENVIRONMENTAL",
    "SOFTWARE",
    "NO_CAUSE_FOUND",
    "NOT_INVESTIGATED",
)

#: The QA decision that closes a deviation.
CAPA_ACTIONS = (
    "INSTRUMENT_RESTORED",
    "RECALIBRATION_PERFORMED",
    "METHOD_REVISED",
    "RETRAINING_REQUIRED",
    "INSTRUMENT_RETIRED",
    "NO_ACTION_REQUIRED",
)


class Deviation(Base, UUIDPrimaryKey, Timestamped, SoftDeletable):
    __tablename__ = "deviations"

    #: Human-facing identifier, e.g. DEV-20261125-0001 (assigned by the service).
    reference: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calibration_runs.id"), nullable=False, index=True
    )
    instrument_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("instruments.id"), nullable=False, index=True
    )
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lab_departments.id")
    )

    classification: Mapped[str] = mapped_column(
        Enum(*DEVIATION_CLASSES, name="deviation_class"), default="MAJOR", nullable=False
    )
    status: Mapped[str] = mapped_column(
        Enum(*DEVIATION_STATUSES, name="deviation_status"),
        default="OPEN",
        nullable=False,
        index=True,
    )

    #: Why it was raised — free text plus the observed symptom, both mandatory.
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # ── phase 1: raise ───────────────────────────────────────────────────────
    raised_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    raised_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # ── phase 2: investigate ────────────────────────────────────────────────
    root_cause_category: Mapped[str | None] = mapped_column(
        Enum(*ROOT_CAUSE_CATEGORIES, name="root_cause_category")
    )
    root_cause: Mapped[str | None] = mapped_column(Text)
    immediate_action: Mapped[str | None] = mapped_column(Text)
    investigated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    investigated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # ── phase 3: close ──────────────────────────────────────────────────────
    capa_action: Mapped[str | None] = mapped_column(Enum(*CAPA_ACTIONS, name="capa_action"))
    capa_notes: Mapped[str | None] = mapped_column(Text)
    #: The retest run this deviation authorises, if one was performed.
    retest_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calibration_runs.id")
    )
    closed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closure_notes: Mapped[str | None] = mapped_column(Text)


def can_transition(current: str, target: str) -> bool:
    return target in ALLOWED_TRANSITIONS.get(current, ())

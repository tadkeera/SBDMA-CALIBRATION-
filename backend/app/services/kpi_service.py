"""KPI computation, extracted so the dashboard and the scheduled report agree.

The numbers were previously computed inline in the HTTP handler. Once a background
job needs the same figures, two copies would be two answers to "what is our pass
rate" — and the wrong one would be whichever an inspector did not read. The handler
now calls this service, and the scheduled report calls the same one.

Every figure is scoped by department: a supervisor sees the site, everyone else sees
their own department, and the report is generated per scope rather than globally
with a filter applied afterwards.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assets import Instrument, ReferenceEquipment, ReferenceStandard
from app.models.deviations import Deviation
from app.models.rbac import LabDepartment
from app.models.runs import CalibrationRun, MaintenanceTicket


class KpiService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def compute(
        self, *, department_id: uuid.UUID | None, today: date | None = None
    ) -> dict:
        """KPI payload. ``department_id=None`` means site-wide (supervisors only)."""
        today = today or date.today()
        soon = today + timedelta(days=30)

        dept = [] if department_id is None else [Instrument.department_id == department_id]
        run_dept = [] if department_id is None else [CalibrationRun.department_id == department_id]

        async def count(stmt) -> int:  # noqa: ANN001
            return int((await self.session.execute(stmt)).scalar_one())

        total_instruments = await count(
            select(func.count()).select_from(Instrument).where(
                Instrument.deleted_at.is_(None), *dept
            )
        )
        overdue = await count(
            select(func.count()).select_from(Instrument).where(
                Instrument.deleted_at.is_(None),
                Instrument.next_due_date.is_not(None),
                Instrument.next_due_date < today,
                *dept,
            )
        )
        due_soon = await count(
            select(func.count()).select_from(Instrument).where(
                Instrument.deleted_at.is_(None),
                Instrument.next_due_date.is_not(None),
                Instrument.next_due_date >= today,
                Instrument.next_due_date <= soon,
                *dept,
            )
        )
        completed = await count(
            select(func.count()).select_from(CalibrationRun).where(
                CalibrationRun.overall_status.in_(["PASS", "FAIL", "UNDER_REVIEW"]), *run_dept
            )
        )
        passed = await count(
            select(func.count()).select_from(CalibrationRun).where(
                CalibrationRun.overall_status == "PASS", *run_dept
            )
        )
        failed = await count(
            select(func.count()).select_from(CalibrationRun).where(
                CalibrationRun.overall_status == "FAIL", *run_dept
            )
        )
        pending_approval = await count(
            select(func.count()).select_from(CalibrationRun).where(
                CalibrationRun.is_locked.is_(False),
                CalibrationRun.overall_status.in_(["PASS", "UNDER_REVIEW"]),
                *run_dept,
            )
        )
        locked = await count(
            select(func.count()).select_from(CalibrationRun).where(
                CalibrationRun.is_locked.is_(True), *run_dept
            )
        )
        avg_review = (
            await self.session.execute(
                select(
                    func.avg(
                        func.extract(
                            "epoch", CalibrationRun.qa_approved_at - CalibrationRun.started_at
                        )
                        / 86400.0
                    )
                ).where(CalibrationRun.qa_approved_at.is_not(None), *run_dept)
            )
        ).scalar_one()

        expired_refs = await count(
            select(func.count()).select_from(ReferenceEquipment).where(
                ReferenceEquipment.expiry_date < today
            )
        )
        expired_standards = await count(
            select(func.count()).select_from(ReferenceStandard).where(
                ReferenceStandard.expiry_date < today
            )
        )
        open_tickets = await count(
            select(func.count()).select_from(MaintenanceTicket).where(
                MaintenanceTicket.status.in_(["OPEN", "IN_PROGRESS"])
            )
        )
        lamp_alerts = await count(
            select(func.count()).select_from(Instrument).where(
                Instrument.deleted_at.is_(None), Instrument.d2_lamp_hours >= 1800
            )
        )

        dev_dept = [] if department_id is None else [Deviation.department_id == department_id]
        open_deviations = await count(
            select(func.count()).select_from(Deviation).where(
                Deviation.status.notin_(["CLOSED", "CANCELLED"]),
                Deviation.deleted_at.is_(None),
                *dev_dept,
            )
        )
        critical_open = await count(
            select(func.count()).select_from(Deviation).where(
                Deviation.status.notin_(["CLOSED", "CANCELLED"]),
                Deviation.classification == "CRITICAL",
                Deviation.deleted_at.is_(None),
                *dev_dept,
            )
        )

        return {
            "scope": "SITE" if department_id is None else "DEPARTMENT",
            "department_id": str(department_id) if department_id else None,
            "instruments": {
                "total": total_instruments,
                "in_calibration": total_instruments - overdue,
                "due_within_30_days": due_soon,
                "overdue": overdue,
            },
            "runs": {
                "completed": completed,
                "passed": passed,
                "failed": failed,
                "pass_rate_percent": round((passed / completed) * 100, 1) if completed else None,
                "pending_qa_approval": pending_approval,
                "locked": locked,
                "mean_approval_days": round(float(avg_review), 1) if avg_review is not None else None,
            },
            "deviations": {"open": open_deviations, "critical_open": critical_open},
            "compliance": {
                "expired_reference_equipment": expired_refs,
                "expired_reference_standards": expired_standards,
                "open_maintenance_tickets": open_tickets,
                "d2_lamp_alerts": lamp_alerts,
            },
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    async def all_departments(self) -> list[LabDepartment]:
        return list(
            (
                await self.session.execute(
                    select(LabDepartment).order_by(LabDepartment.code)
                )
            ).scalars().all()
        )

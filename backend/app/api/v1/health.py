"""Health, readiness and KPI endpoints.

KPIs are computed from live rows — the specification forbids synthetic numbers.
"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter
from sqlalchemy import func, select, text

from app.api.deps import PrincipalDep, SessionDep
from app.core.config import get_settings
from app.core.database import ping
from app.schemas.common import ok
from app.models.assets import Instrument, ReferenceEquipment, ReferenceStandard
from app.models.runs import CalibrationRun, MaintenanceTicket

router = APIRouter(tags=["health"])
settings = get_settings()


@router.get("/health/live", summary="فحص الحياة")
async def live():
    return ok({"status": "alive", "version": settings.app_version})


@router.get("/health/ready", summary="فحص الجهوزية")
async def ready(session: SessionDep):
    db_ok = await ping()
    checks = {"database": db_ok, "cache": None, "workers": None}
    if db_ok:
        try:
            await session.execute(text("SELECT 1"))
        except Exception:
            checks["database"] = False
    status = "ready" if all(v is not False for v in checks.values()) else "degraded"
    return ok(
        {
            "status": status,
            "checks": checks,
            "unconfigured": [k for k, v in checks.items() if v is None],
        }
    )


@router.get("/health", summary="فحص صحة النظام الكامل")
async def health(session: SessionDep):
    db_ok = await ping()
    payload = {
        "status": "ok" if db_ok else "degraded",
        "version": settings.app_version,
        "environment": settings.environment,
        "components": {
            "postgresql": "up" if db_ok else "down",
            "redis": "not_configured" if not settings.redis_url else "configured",
            "celery": "not_configured",
            "storage": settings.storage_path,
        },
    }
    return ok(payload)


@router.get("/kpis", summary="مؤشرات الأداء الحقيقية")
async def kpis(session: SessionDep, principal: PrincipalDep):
    principal.require("instruments.view")
    today = date.today()
    soon = today + timedelta(days=30)

    dept_filter = [] if principal.is_supervisor() else [Instrument.department_id == principal.department_id]

    total_instruments = (
        await session.execute(
            select(func.count()).select_from(Instrument).where(
                Instrument.deleted_at.is_(None), *dept_filter
            )
        )
    ).scalar_one()
    overdue = (
        await session.execute(
            select(func.count()).select_from(Instrument).where(
                Instrument.deleted_at.is_(None),
                Instrument.next_due_date.is_not(None),
                Instrument.next_due_date < today,
                *dept_filter,
            )
        )
    ).scalar_one()
    due_soon = (
        await session.execute(
            select(func.count()).select_from(Instrument).where(
                Instrument.deleted_at.is_(None),
                Instrument.next_due_date.is_not(None),
                Instrument.next_due_date >= today,
                Instrument.next_due_date <= soon,
                *dept_filter,
            )
        )
    ).scalar_one()
    in_calibration = int(total_instruments) - int(overdue)

    run_filter = [] if principal.is_supervisor() else [CalibrationRun.department_id == principal.department_id]
    completed = (
        await session.execute(
            select(func.count()).select_from(CalibrationRun).where(
                CalibrationRun.overall_status.in_(["PASS", "FAIL", "UNDER_REVIEW"]), *run_filter
            )
        )
    ).scalar_one()
    passed = (
        await session.execute(
            select(func.count()).select_from(CalibrationRun).where(
                CalibrationRun.overall_status == "PASS", *run_filter
            )
        )
    ).scalar_one()
    pending_approval = (
        await session.execute(
            select(func.count()).select_from(CalibrationRun).where(
                CalibrationRun.is_locked.is_(False),
                CalibrationRun.overall_status.in_(["PASS", "UNDER_REVIEW"]),
                *run_filter,
            )
        )
    ).scalar_one()
    locked = (
        await session.execute(
            select(func.count()).select_from(CalibrationRun).where(
                CalibrationRun.is_locked.is_(True), *run_filter
            )
        )
    ).scalar_one()

    avg_review = (
        await session.execute(
            select(
                func.avg(
                    func.extract("epoch", CalibrationRun.qa_approved_at - CalibrationRun.started_at)
                    / 86400.0
                )
            ).where(CalibrationRun.qa_approved_at.is_not(None), *run_filter)
        )
    ).scalar_one()

    expired_refs = (
        await session.execute(
            select(func.count()).select_from(ReferenceEquipment).where(
                ReferenceEquipment.expiry_date < today
            )
        )
    ).scalar_one()
    expired_standards = (
        await session.execute(
            select(func.count()).select_from(ReferenceStandard).where(
                ReferenceStandard.expiry_date < today
            )
        )
    ).scalar_one()
    open_tickets = (
        await session.execute(
            select(func.count()).select_from(MaintenanceTicket).where(
                MaintenanceTicket.status.in_(["OPEN", "IN_PROGRESS"])
            )
        )
    ).scalar_one()
    lamp_alerts = (
        await session.execute(
            select(func.count()).select_from(Instrument).where(
                Instrument.deleted_at.is_(None), Instrument.d2_lamp_hours >= 1800
            )
        )
    ).scalar_one()

    return ok(
        {
            "instruments": {
                "total": int(total_instruments),
                "in_calibration": in_calibration,
                "due_within_30_days": int(due_soon),
                "overdue": int(overdue),
            },
            "runs": {
                "completed": int(completed),
                "passed": int(passed),
                "pass_rate_percent": round((passed / completed) * 100, 1) if completed else None,
                "pending_qa_approval": int(pending_approval),
                "locked": int(locked),
                "mean_approval_days": round(float(avg_review), 1) if avg_review is not None else None,
            },
            "compliance": {
                "expired_reference_equipment": int(expired_refs),
                "expired_reference_standards": int(expired_standards),
                "open_maintenance_tickets": int(open_tickets),
                "d2_lamp_alerts": int(lamp_alerts),
            },
            "generated_at": __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ).isoformat(),
        }
    )

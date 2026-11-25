"""In-app notifications and the operations controls for the background jobs.

Two audiences share this router:

* **Everyone** reads their own notices. A notice is addressed to a person, and a
  person may only see and mark their own — the department scoping used elsewhere
  would be wrong here, because "unread" is a per-user fact.
* **qa.manager / super admin** may trigger a job by hand and read what the worker
  has produced. That exists for the ordinary operational reason: when the nightly
  job did not run, someone must be able to run it and see the result without
  shelling into a container. A manual run is audited with the operator's name, so
  it is distinguishable from a scheduled one in the trail.
"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Query, Request

from app.api.deps import PrincipalDep, SessionDep, client_ip
from app.schemas.common import ok
from app.services.audit_service import AuditService
from app.services.notification_service import NotificationService
from app.worker.celery_app import celery_app

router = APIRouter(tags=["notifications"])


def _serialise(row) -> dict:  # noqa: ANN001
    return {
        "id": str(row.id),
        "channel": row.channel,
        "severity": row.severity,
        "title_ar": row.title_ar,
        "title_en": (row.payload_jsonb or {}).get("title_en"),
        "body_ar": row.body_ar,
        "payload": row.payload_jsonb,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "sent_at": row.sent_at.isoformat() if row.sent_at else None,
        "read_at": row.read_at.isoformat() if row.read_at else None,
    }


@router.get("/notifications", summary="إشعارات المستخدم الحالي")
async def my_notifications(
    session: SessionDep,
    principal: PrincipalDep,
    unread_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
):
    rows = await NotificationService(session).for_user(
        principal.user_id, unread_only=unread_only, limit=limit
    )
    return ok([_serialise(row) for row in rows])


@router.get("/notifications/unread-count", summary="عدد الإشعارات غير المقروءة")
async def unread_count(session: SessionDep, principal: PrincipalDep):
    rows = await NotificationService(session).for_user(
        principal.user_id, unread_only=True, limit=200
    )
    return ok({"unread": len(rows)})


@router.get("/notifications/due-preview", summary="معاينة ما سيُشعر به دون إنشاء")
async def due_preview(session: SessionDep, principal: PrincipalDep):
    """What the next run would create. Read-only, so it is safe to inspect."""
    principal.require("instruments.view")
    summary = await NotificationService(session).generate_due_notices(dry_run=True)
    return ok(summary)


@router.post("/notifications/generate", summary="تشغيل توليد الإشعارات يدوياً")
async def generate_now(request: Request, session: SessionDep, principal: PrincipalDep):
    """Run the nightly job by hand.

    Restricted to ``qa.manager``: it is an operational control, not something every
    analyst should be able to spray across the site's inboxes.
    """
    principal.require("calibration.approve")
    summary = await NotificationService(session).generate_due_notices()
    await AuditService(session).record(
        action="NOTIFICATIONS_GENERATED_MANUALLY",
        entity_type="notification",
        entity_id=uuid.uuid4(),
        actor_label=principal.username,
        actor_id=principal.user_id,
        role_label=principal.primary_role,
        department_id=principal.department_id,
        new_values=summary,
        reason="تشغيل يدوي لمهمة إشعارات الانتهاء",
        ip_address=client_ip(request),
    )
    await session.commit()
    return ok(summary)


@router.post("/reports/kpi/run", summary="توليد تقرير مؤشرات الأداء الآن")
async def run_kpi_report(
    request: Request,
    session: SessionDep,
    principal: PrincipalDep,
    for_date: date | None = Query(default=None),
):
    """Generate the weekly KPI register on demand.

    Deliberately *inline* rather than enqueued: the caller wants the answer, and a
    task id it cannot inspect is a worse answer than a slightly slower request. The
    same function is what Celery runs, so the schedule and the button cannot drift.
    """
    principal.require("reports.export")
    from app.tasks.reports import _build_kpi_report

    summary = await _build_kpi_report(session, for_date=for_date)
    await AuditService(session).record(
        action="KPI_REPORT_REQUESTED",
        entity_type="report",
        entity_id=uuid.uuid4(),
        actor_label=principal.username,
        actor_id=principal.user_id,
        role_label=principal.primary_role,
        department_id=principal.department_id,
        new_values={"period": summary["period"], "documents": len(summary["documents"])},
        reason="طلب توليد تقرير مؤشرات الأداء من الواجهة",
        ip_address=client_ip(request),
    )
    await session.commit()
    return ok(summary)


@router.get("/worker/status", summary="حالة العامل والمهام المجدولة")
async def worker_status(principal: PrincipalDep):
    """What the schedule actually is, as the app configured it.

    The beat schedule is read from the live app rather than restated in the docs, so
    this endpoint cannot claim a schedule the worker is not running.
    """
    principal.require("audit.view")
    schedule = [
        {
            "name": name,
            "task": entry["task"],
            "schedule": str(entry["schedule"]),
        }
        for name, entry in celery_app.conf.beat_schedule.items()
    ]
    registered = sorted(
        name for name in celery_app.tasks if name.startswith("sbdma.")
    )
    from app.core.config import get_settings as _get_settings

    mode = _get_settings().scheduler
    return ok(
        {
            "scheduler": mode,
            # On a serverless deployment there is no beat process: the schedule is
            # vercel.json's `crons`, and reporting beat's schedule here would describe
            # a scheduler that is not running.
            "scheduler_source": "vercel.json (crons)" if mode == "vercel-cron" else "celery beat",
            "broker_configured": bool(celery_app.conf.broker_url not in (None, "memory://")),
            "broker": celery_app.conf.broker_url,
            "scheduled": [] if mode == "vercel-cron" else schedule,
            "registered_tasks": registered,
            "note_ar": "الإشعارات تُخزَّن داخل التطبيق؛ لا مزوّد بريد مُعدّ بعد.",
            "note_en": "Notices are stored in-app; no mail provider is wired yet.",
        }
    )


@router.post("/notifications/{notification_id}/read", summary="تعليم إشعار كمقروء")
async def mark_read(
    notification_id: uuid.UUID, session: SessionDep, principal: PrincipalDep
):
    changed = await NotificationService(session).mark_read(
        principal.user_id, notification_id
    )
    await session.commit()
    return ok({"id": str(notification_id), "marked": changed})

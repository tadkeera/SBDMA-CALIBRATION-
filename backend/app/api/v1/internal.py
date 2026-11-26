"""Scheduled jobs triggered over HTTP (serverless deployments).

Why this route exists
---------------------
Vercel Functions are request-scoped: there is no process to run ``celery beat``, so
on a Vercel deployment the schedule lives in ``vercel.json`` under ``crons`` and each
cron calls one of these routes. The *work* is not reimplemented here — both triggers
call the same services:

* ``sbdma.notify.calibration_due`` (Celery) / ``POST jobs/calibration-due`` (cron)
  → :class:`app.services.notification_service.NotificationService`
* ``sbdma.reports.kpi_report`` (Celery) / ``POST jobs/kpi-report`` (cron)
  → :func:`app.services.kpi_report_service.build_kpi_report`
* ``python -m app.seed`` (shell) / ``POST jobs/seed`` (cron)
  → :func:`app.seed.seed_protocol.seed_protocol`

A second implementation would eventually disagree with the first, and the reader
would have no way to tell which document an inspector is holding.

Guard
-----
* **No secret, no job.** With ``CRON_SECRET`` unset these routes answer ``503``
  instead of running. An unauthenticated endpoint that writes notifications, files
  PDFs and appends to the audit chain is not a convenience, it is a way in.
* The bearer token is compared with :func:`hmac.compare_digest`, so the check does
  not leak the secret one byte at a time.
* Vercel sends ``Authorization: Bearer $CRON_SECRET`` automatically when that
  variable exists, and ``x-vercel-cron`` / ``x-vercel-id`` identify the trigger; the
  audit row records both, so "what ran the nightly job" stays answerable.
"""

from __future__ import annotations

import hmac
import uuid
from datetime import date

from fastapi import APIRouter, Query, Request

from app.api.deps import SessionDep, client_ip
from app.core.database import SessionFactory
from app.core.config import get_settings
from app.core.exceptions import AppError
from app.schemas.common import ok
from app.seed.seed_protocol import seed_protocol
from app.seed.seed_rbac import seed_rbac
from app.services.audit_service import AuditService
from app.services.kpi_report_service import build_kpi_report
from app.services.notification_service import NotificationService

router = APIRouter(prefix="/internal/jobs", tags=["internal"], include_in_schema=False)
settings = get_settings()


class CronUnauthorised(AppError):
    """Wrong or missing bearer token on a scheduler route."""

    status_code = 401
    code = "CRON_UNAUTHORISED"


class CronNotConfigured(AppError):
    """``CRON_SECRET`` is unset, so the route must not run at all."""

    status_code = 503
    code = "CRON_NOT_CONFIGURED"


def _authorise(request: Request) -> None:
    secret = settings.cron_secret
    if not secret:
        raise CronNotConfigured(
            message_ar="مهام الجدولة عبر HTTP غير مُهيّأة — CRON_SECRET غير مضبوط",
            message_en="HTTP-scheduled jobs are not configured: CRON_SECRET is unset",
        )
    provided = request.headers.get("authorization") or ""
    expected = f"Bearer {secret}"
    if not hmac.compare_digest(provided, expected):
        raise CronUnauthorised(
            message_ar="رمز جدولة غير صالح",
            message_en="Invalid scheduler token",
        )


def _trigger_details(request: Request) -> dict:
    """What invoked the job, as the platform reported it."""
    return {
        "trigger": "vercel-cron" if request.headers.get("x-vercel-cron") else "http",
        "vercel_id": request.headers.get("x-vercel-id"),
        "ip": client_ip(request),
    }


async def _record_failure(request: Request, job: str, exc: BaseException) -> None:
    """A scheduled job that fails must leave a trace someone can read.

    On a serverless platform the operator has no shell and no log tail: a 500 that
    only exists in the platform's log viewer is, for the laboratory, a job that
    silently did nothing. The failure is written to the audit chain in its own
    session — the request's transaction is already broken by definition — with the
    exception type and message and nothing that could carry a secret.
    """
    detail = f"{type(exc).__name__}: {exc}"[:500]
    try:
        async with SessionFactory() as session:
            await AuditService(session).record(
                action="CRON_JOB_FAILED",
                entity_type="scheduled_job",
                entity_id=uuid.uuid4(),
                actor_label=_actor_label(request),
                new_values={"job": job, "error": detail, **_trigger_details(request)},
                reason="فشل مهمة مجدولة — التفاصيل للأثر",
            )
            await session.commit()
    except Exception:  # pragma: no cover - the failure path must never mask the failure
        pass


def _actor_label(request: Request) -> str:
    return "system:vercel-cron" if request.headers.get("x-vercel-cron") else "system:cron"


@router.api_route(
    "/calibration-due",
    methods=["GET", "POST"],
    summary="إشعارات الانتهاء (بديل beat على البيئات الخادمية)",
)
async def calibration_due(
    request: Request,
    session: SessionDep,
    today: date | None = Query(default=None, description="لإعادة تشغيل يوم سابق"),
):
    _authorise(request)
    try:
        summary = await NotificationService(session).generate_due_notices(today=today)
    except Exception as exc:
        await _record_failure(request, "calibration-due", exc)
        raise
    await AuditService(session).record(
        action="CALIBRATION_DUE_JOB_RAN",
        entity_type="notification",
        entity_id=uuid.uuid4(),
        actor_label=_actor_label(request),
        new_values={**summary, **_trigger_details(request)},
        reason="تشغيل مجدول لمهمة إشعارات الانتهاء",
    )
    await session.commit()
    return ok(summary)


@router.api_route(
    "/kpi-report",
    methods=["GET", "POST"],
    summary="تقرير مؤشرات الأداء (بديل beat على البيئات الخادمية)",
)
async def kpi_report(
    request: Request,
    session: SessionDep,
    for_date: date | None = Query(default=None),
    force: bool = Query(
        default=False,
        description="أعد توليد التقرير حتى لو سُجّل الأسبوع (للتشغيل اليدوي فقط)",
    ),
):
    _authorise(request)
    try:
        summary = await build_kpi_report(
            session, for_date=for_date, actor_label=_actor_label(request), force=force
        )
    except Exception as exc:
        await _record_failure(request, "kpi-report", exc)
        raise
    await AuditService(session).record(
        action="KPI_REPORT_JOB_RAN",
        entity_type="report",
        entity_id=uuid.uuid4(),
        actor_label=_actor_label(request),
        new_values={
            "period": summary["period"],
            "documents": len(summary["documents"]),
            **_trigger_details(request),
        },
        reason="تشغيل مجدول لتقرير مؤشرات الأداء الأسبوعي",
    )
    await session.commit()
    return ok(summary)


@router.api_route(
    "/seed",
    methods=["GET", "POST"],
    summary="تسجيل بروتوكول المعايرة (بديل الوصول إلى قاعدة البيانات)",
)
async def seed(request: Request, session: SessionDep):
    """Register the shipped protocol version, idempotently.

    Why over HTTP
    -------------
    A serverless deployment has no shell: bumping ``PROTOCOL_VERSION`` in the
    blueprint would otherwise leave production executing last release's limits, and
    the only symptom is a report that quietly disagrees with the document. This route
    makes "the code and the database agree" a single authenticated POST.

    It also re-runs the RBAC seed, which is additive and idempotent, so a permission
    introduced by this release exists in the database without a shell.

    It is safe to call on every deploy: :func:`seed_protocol` returns
    ``{"skipped": 1}`` when that code/version already exists, and it never updates or
    deletes an existing protocol — a calibration record points at the version it was
    performed under.
    """
    _authorise(request)
    try:
        # RBAC first: a release that adds a permission must land it in the same call,
        # otherwise the Control Center switch has nothing to grant.
        summary = await seed_rbac(session) | await seed_protocol(session)
    except Exception as exc:
        await _record_failure(request, "seed", exc)
        raise
    await AuditService(session).record(
        action="PROTOCOL_SEED_JOB_RAN",
        entity_type="protocol",
        entity_id=uuid.uuid4(),
        actor_label=_actor_label(request),
        new_values={**summary, **_trigger_details(request)},
        reason="تسجيل بروتوكول المعايرة المُصدَّر مع الإصدار الحالي",
    )
    await session.commit()
    return ok(summary)

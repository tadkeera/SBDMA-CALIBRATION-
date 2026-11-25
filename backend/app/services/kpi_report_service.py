"""Weekly KPI register: build, file, hash, audit.

This lives in ``services`` rather than in the task module because the same job now
has two triggers:

* **Celery beat** in a container deployment (``sbdma.reports.kpi_report``);
* **Vercel Cron** on a serverless deployment, where no worker process can exist
  (``POST /api/v1/internal/jobs/kpi-report``).

Two triggers, one implementation. A second copy of this logic would eventually file
a report whose numbers disagree with the one produced the other way, and the reader
has no way to know which of the two an inspector is looking at.

The report is a *document*, not a query: written to the storage path with a
deterministic name, hashed, and recorded in the audit chain with that hash. A number
in a dashboard is a live view; a number in a filed report is a record, and a record
needs an identity and a fingerprint.
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.audit import AuditLog
from app.services.audit_service import AuditService
from app.services.branding_service import BrandingService
from app.services.kpi_service import KpiService
from app.services.report_service import build_kpi_pdf

settings = get_settings()


def iso_week_label(day: date) -> str:
    iso = day.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


async def already_filed(session: AsyncSession, period: str) -> bool:
    """Has a register for this ISO week already been filed?

    The scheduler must be idempotent for the same reason the due notices are: a
    retried or double-fired job that files a second report for the same week leaves
    two documents claiming to be *the* register, and no reader can tell which one is
    authoritative.
    """
    row = (
        await session.execute(
            select(AuditLog.id)
            .where(AuditLog.action == "KPI_REPORT_GENERATED")
            .where(AuditLog.new_values["period"].astext == period)
            .limit(1)
        )
    ).scalar_one_or_none()
    return row is not None


async def build_kpi_report(
    session: AsyncSession,
    *,
    for_date: date | None = None,
    actor_label: str = "system:celery",
    force: bool = True,
) -> dict:
    """Assemble and file the report using the caller's session.

    ``force`` defaults to ``True`` because a human pressing "generate now" in the UI
    is asking for a fresh copy and should get one. The scheduler passes
    ``force=False``: a retried cron must not file the week twice.
    """
    today = for_date or date.today()
    period = iso_week_label(today)
    if not force and await already_filed(session, period):
        return {
            "period": period,
            "documents": [],
            "skipped": True,
            "reason": f"a register for {period} was already filed",
        }
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    document_id = f"SBDMA-KPI-{period}-{stamp}-{uuid.uuid4().hex[:6].upper()}"

    service = KpiService(session)
    departments = await service.all_departments()
    # one read for the whole batch: every document in a run carries the same letterhead
    branding = await BrandingService(session).load()

    # Site-wide plus one per department: a department head should not have to
    # subtract two numbers to find their own.
    reports: list[tuple[str, dict]] = [
        ("SITE", await service.compute(department_id=None, today=today))
    ]
    for dept in departments:
        reports.append(
            (dept.code, await service.compute(department_id=dept.id, today=today))
        )

    written: list[dict] = []
    target_dir = Path(settings.storage_path) / "kpi-reports" / period
    target_dir.mkdir(parents=True, exist_ok=True)

    for scope, payload in reports:
        payload = dict(payload)
        payload.update(
            {
                "document_id": f"{document_id}-{scope}",
                "page_total": 1,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "scope_label": scope,
                "period_label": period,
                "branding": branding,
            }
        )
        blob = await asyncio.to_thread(build_kpi_pdf, payload)
        digest = hashlib.sha256(blob).hexdigest()
        path = target_dir / f"{period}-{scope}-kpi.pdf"
        path.write_bytes(blob)
        # the file on disk must hash to what is about to be recorded
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise RuntimeError(f"written KPI report does not match its hash: {path}")
        written.append(
            {
                "scope": scope,
                "document_id": payload["document_id"],
                "path": str(path),
                "bytes": len(blob),
                "sha256": digest,
            }
        )

    if written:
        await AuditService(session).record(
            action="KPI_REPORT_GENERATED",
            entity_type="report",
            entity_id=uuid.uuid4(),
            actor_label=actor_label,
            reason=f"توليد تقرير مؤشرات الأداء الأسبوعي {period}",
            new_values={
                "period": period,
                "documents": [
                    {k: w[k] for k in ("scope", "document_id", "bytes", "sha256")}
                    for w in written
                ],
            },
        )
    await session.commit()
    return {"period": period, "documents": written}

"""Scheduled report generation.

The weekly KPI report is a *document*, not a query: it is written to the storage
path with a deterministic name, hashed, and recorded in the audit chain with that
hash. A number in a dashboard is a live view; a number in a filed report is a
record, and a record needs an identity and a fingerprint.
"""

from __future__ import annotations

import hashlib
import logging
import os
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from app.core.config import get_settings
from app.services.audit_service import AuditService
from app.services.kpi_service import KpiService
from app.services.report_service import build_kpi_pdf
from app.worker.celery_app import celery_app
from app.worker.runner import run_with_session

log = logging.getLogger("sbdma.tasks")
settings = get_settings()


def _iso_week_label(day: date) -> str:
    iso = day.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


async def _build_kpi_report(session, *, for_date: date | None = None) -> dict:  # noqa: ANN001
    """Assemble and file the report using the caller's session."""
    today = for_date or date.today()
    period = _iso_week_label(today)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    document_id = f"SBDMA-KPI-{period}-{stamp}-{uuid.uuid4().hex[:6].upper()}"

    service = KpiService(session)
    departments = await service.all_departments()

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
            }
        )
        blob = build_kpi_pdf(payload)
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
            actor_label="system:celery",
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


def _generate_kpi_report(*, for_date: date | None = None) -> dict:
    """Task entry point: own engine, own loop, own session."""
    return run_with_session(lambda session: _build_kpi_report(session, for_date=for_date))


@celery_app.task(name="sbdma.reports.kpi_report", bind=True, max_retries=3)
def kpi_report(self, for_date_iso: str | None = None) -> dict:  # noqa: ANN001
    """Weekly KPI register for the site and every department."""
    for_date = date.fromisoformat(for_date_iso) if for_date_iso else None
    try:
        summary = _generate_kpi_report(for_date=for_date)
    except Exception as exc:  # noqa: BLE001
        log.exception("kpi_report failed")
        raise self.retry(exc=exc, countdown=120 * (self.request.retries + 1)) from exc

    log.info("kpi_report complete: %s documents", len(summary["documents"]))
    return summary

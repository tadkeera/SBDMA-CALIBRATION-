"""Scheduled report generation — the Celery trigger.

The report itself is built in :mod:`app.services.kpi_report_service`, because Vercel
Cron triggers the same job through HTTP on deployments where no worker can run. This
module only supplies the session and the loop.
"""

from __future__ import annotations

import logging
from datetime import date

from app.services.kpi_report_service import build_kpi_report as _build_kpi_report_impl
from app.services.kpi_report_service import iso_week_label as _iso_week_label  # noqa: F401
from app.worker.celery_app import celery_app
from app.worker.runner import run_with_session

log = logging.getLogger("sbdma.tasks")


async def _build_kpi_report(session, *, for_date: date | None = None) -> dict:  # noqa: ANN001
    """Task-side wrapper: the report logic lives in the service (two triggers)."""
    return await _build_kpi_report_impl(session, for_date=for_date, actor_label="system:celery")


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

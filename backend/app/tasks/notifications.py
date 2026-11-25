"""Scheduled notification tasks.

Each task is a thin wrapper: the work lives in a service so it can be tested without
a broker, and the task only supplies the session and the loop. That split is why the
test suite can assert the *behaviour* of the due-date logic on a machine with no
Redis at all.
"""

from __future__ import annotations

import logging
from datetime import date

from app.services.notification_service import NotificationService
from app.worker.celery_app import celery_app
from app.worker.runner import run_with_session

log = logging.getLogger("sbdma.tasks")


def _generate(today: date | None) -> dict:
    async def work(session):  # noqa: ANN001
        summary = await NotificationService(session).generate_due_notices(today=today)
        await session.commit()
        return summary

    return run_with_session(work)


@celery_app.task(name="sbdma.notify.calibration_due", bind=True, max_retries=3)
def calibration_due(self, today_iso: str | None = None) -> dict:  # noqa: ANN001
    """Nightly: notice for every instrument or reference material coming due.

    ``today_iso`` exists so the job can be replayed for a past date when
    investigating why a notice was or was not produced — a scheduled job whose
    output cannot be reproduced is not auditable.
    """
    today = date.fromisoformat(today_iso) if today_iso else None
    try:
        summary = _generate(today)
    except Exception as exc:  # noqa: BLE001 - retried below, logged either way
        log.exception("calibration_due failed")
        raise self.retry(exc=exc, countdown=60 * (self.request.retries + 1)) from exc

    log.info("calibration_due complete: %s", summary)
    return summary

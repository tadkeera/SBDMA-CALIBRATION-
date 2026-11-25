"""Celery application.

The worker is a *second writer* to the same database the web process uses, and that
shapes everything here:

* **It must not be required to boot.** ``redis_url`` is optional. Without it the
  tasks stay bound and run inline on call, so development and the test suite work
  with no broker at all, and ``/health`` says ``not_configured`` instead of
  pretending. A verification system that refuses to start because a cache is down
  is a verification system that gets worked around.
* **Every task is idempotent.** Celery delivers at least once: a worker killed after
  the work but before the ack re-runs the task. A notification that fires twice is a
  nuisance; a *calibration due* notice that fires twice is noise that trains people
  to ignore the notices, which is the real failure mode of an alerting system. Each
  job therefore records what it did and skips what is already done.
* **Appends go through the audit chain lock.** ``AuditService.record`` takes a
  transaction-scoped advisory lock, so a worker and a request can append at the
  same time without forking the chain.

Schedule times are in UTC. The beat schedule is deliberately at a quiet hour so a
long-running report cannot compete with the working day for database time.
"""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings

settings = get_settings()


def _broker() -> str | None:
    return settings.redis_url


def build_app() -> Celery:
    app = Celery(
        "sbdma",
        broker=_broker() or "memory://",
        backend=_broker() or None,
        include=["app.tasks.notifications", "app.tasks.reports"],
    )
    app.conf.update(
        # A worker may be killed at any time; refuse to accept work it cannot
        # finish quickly rather than holding a task hostage.
        # Celery 6 will make startup retries conditional on this; state it now so a
        # worker that starts before Redis is ready retries instead of dying.
        broker_connection_retry_on_startup=True,
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        task_time_limit=600,
        task_soft_time_limit=540,
        # One queue keeps operations simple at this size; the split only becomes
        # worth it when a slow report must not delay a due-date notice.
        task_default_queue="sbdma",
        timezone="UTC",
        enable_utc=True,
        # Results are not read back by anything: the notification row *is* the
        # durable record. Keeping them would grow Redis for no benefit.
        task_ignore_result=True,
        beat_schedule={
            # Daily: instruments and reference materials approaching expiry.
            "calibration-due-notices": {
                "task": "sbdma.notify.calibration_due",
                "schedule": crontab(hour=5, minute=15),
            },
            # Weekly: the KPI register for QA, so a trend is visible without anyone
            # opening the dashboard.
            "weekly-kpi-report": {
                "task": "sbdma.reports.kpi_report",
                "schedule": crontab(day_of_week=1, hour=4, minute=30),
            },
        },
    )
    return app


celery_app = build_app()

# Importing the task modules registers them on the app. ``include`` alone only
# works for a worker started from the CLI; a caller that imports this module and
# inspects ``celery_app.tasks`` (a test, a management script, ``task.apply``) would
# otherwise see an empty registry and conclude the schedule points at nothing.
from app.tasks import notifications as _notifications  # noqa: E402,F401
from app.tasks import reports as _reports  # noqa: E402,F401


if __name__ == "__main__":  # pragma: no cover - operational entry point
    celery_app.start()

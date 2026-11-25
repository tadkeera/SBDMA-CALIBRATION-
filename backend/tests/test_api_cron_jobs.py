"""HTTP-scheduled jobs: the serverless replacement for celery beat.

Vercel Functions are request-scoped, so a deployment there has no beat process. The
schedule lives in ``vercel.json`` and calls these routes. Two things must hold:

* the routes refuse to run without ``CRON_SECRET`` — an unauthenticated endpoint that
  writes notifications, files PDFs and appends to the audit chain is a way in;
* the work is the *same* code the Celery task runs, so a notice or a report cannot
  differ depending on which trigger produced it.
"""

from __future__ import annotations

import pytest

from app.core.config import get_settings

SECRET = "cron-test-secret-0123456789abcdef"


@pytest.fixture()
def cron_settings():
    """Point the route at a known secret, and restore it afterwards."""
    settings = get_settings()
    original = settings.cron_secret
    settings.cron_secret = SECRET
    yield settings
    settings.cron_secret = original


def _auth(secret: str = SECRET) -> dict[str, str]:
    return {"Authorization": f"Bearer {secret}"}


async def test_without_a_secret_the_route_refuses_to_run(client) -> None:  # noqa: ANN001
    settings = get_settings()
    original = settings.cron_secret
    settings.cron_secret = None
    try:
        for path in ("calibration-due", "kpi-report"):
            response = await client.post(f"/api/v1/internal/jobs/{path}")
            assert response.status_code == 503
            assert response.json()["errors"][0]["code"] == "CRON_NOT_CONFIGURED"
    finally:
        settings.cron_secret = original


async def test_a_wrong_token_is_refused(client, cron_settings) -> None:  # noqa: ANN001
    for headers in ({}, _auth("not-the-secret"), {"Authorization": SECRET}):
        response = await client.post(
            "/api/v1/internal/jobs/calibration-due", headers=headers
        )
        assert response.status_code == 401
        assert response.json()["errors"][0]["code"] == "CRON_UNAUTHORISED"


async def test_the_due_notice_job_runs_and_is_audited(client, cron_settings) -> None:  # noqa: ANN001
    response = await client.post(
        "/api/v1/internal/jobs/calibration-due", headers=_auth()
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert "due_items" in body["data"]

    from sqlalchemy import select

    from app.core.database import SessionFactory
    from app.models.audit import AuditLog

    async with SessionFactory() as session:
        row = (
            await session.execute(
                select(AuditLog)
                .where(AuditLog.action == "CALIBRATION_DUE_JOB_RAN")
                .order_by(AuditLog.chain_seq.desc())
                .limit(1)
            )
        ).scalar_one()
        # no user signed this: it is a machine action, and the audit row says which
        # machine and what invoked it
        assert row.actor_label == "system:cron"
        assert row.new_values["trigger"] == "http"


async def test_a_vercel_trigger_is_labelled_as_such(client, cron_settings) -> None:  # noqa: ANN001
    response = await client.get(
        "/api/v1/internal/jobs/calibration-due",
        headers={**_auth(), "x-vercel-cron": "1", "x-vercel-id": "fra1::abc123"},
    )
    assert response.status_code == 200  # GET, because that is what Vercel Cron sends

    from sqlalchemy import select

    from app.core.database import SessionFactory
    from app.models.audit import AuditLog

    async with SessionFactory() as session:
        row = (
            await session.execute(
                select(AuditLog)
                .where(AuditLog.action == "CALIBRATION_DUE_JOB_RAN")
                .order_by(AuditLog.chain_seq.desc())
                .limit(1)
            )
        ).scalar_one()
        assert row.actor_label == "system:vercel-cron"
        assert row.new_values["trigger"] == "vercel-cron"
        assert row.new_values["vercel_id"] == "fra1::abc123"


async def test_the_kpi_report_job_files_documents_and_hashes_them(
    client, cron_settings, tmp_path  # noqa: ANN001
) -> None:
    settings = get_settings()
    original_storage = settings.storage_path
    settings.storage_path = str(tmp_path)
    try:
        # a date of its own: the register is filed per ISO week, and two tests in the
        # same week would correctly refuse to file twice (see the retry test below)
        response = await client.post(
            "/api/v1/internal/jobs/kpi-report?for_date=2025-03-04", headers=_auth()
        )
        assert response.status_code == 200
        payload = response.json()["data"]
        # site-wide plus one per seeded department
        assert len(payload["documents"]) >= 2

        import hashlib
        from pathlib import Path

        for doc in payload["documents"]:
            path = Path(doc["path"])
            assert path.is_file() and path.stat().st_size > 0
            assert hashlib.sha256(path.read_bytes()).hexdigest() == doc["sha256"]
    finally:
        settings.storage_path = original_storage


async def test_a_retried_cron_does_not_file_the_same_week_twice(
    client, cron_settings, tmp_path  # noqa: ANN001
) -> None:
    """Celery delivers at least once and a cron can be retried; neither may leave two
    documents claiming to be the same week's register."""
    settings = get_settings()
    original_storage = settings.storage_path
    settings.storage_path = str(tmp_path)
    try:
        first = await client.post(
            "/api/v1/internal/jobs/kpi-report?for_date=2025-04-08", headers=_auth()
        )
        assert first.status_code == 200
        assert first.json()["data"]["documents"]

        second = await client.post(
            "/api/v1/internal/jobs/kpi-report?for_date=2025-04-08", headers=_auth()
        )
        assert second.status_code == 200
        assert second.json()["data"]["skipped"] is True
        assert second.json()["data"]["documents"] == []

        # a human pressing "generate now" still gets a fresh copy
        forced = await client.post(
            "/api/v1/internal/jobs/kpi-report?for_date=2025-04-08&force=true", headers=_auth()
        )
        assert forced.status_code == 200
        assert forced.json()["data"]["documents"]
    finally:
        settings.storage_path = original_storage


async def test_scheduled_routes_are_not_in_the_public_api_document(client) -> None:  # noqa: ANN001
    openapi = (await client.get("/api/openapi.json")).json()
    assert not [p for p in openapi["paths"] if "/internal/" in p]


async def test_the_worker_status_names_the_actual_scheduler(client, admin_session) -> None:  # noqa: ANN001
    settings = get_settings()
    original = settings.scheduler
    try:
        settings.scheduler = "vercel-cron"
        response = await client.get(
            "/api/v1/worker/status", headers=admin_session["hash"]
        )
        data = response.json()["data"]
        assert data["scheduler"] == "vercel-cron"
        assert data["scheduler_source"] == "vercel.json (crons)"
        # beat's schedule is not reported as if it were running
        assert data["scheduled"] == []
    finally:
        settings.scheduler = original

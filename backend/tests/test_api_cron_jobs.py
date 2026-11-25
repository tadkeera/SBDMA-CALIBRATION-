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
        for path in ("calibration-due", "kpi-report", "seed"):
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


async def test_the_seed_job_registers_the_protocol_once_and_is_audited(
    client, cron_settings
) -> None:  # noqa: ANN001
    """The serverless replacement for ``python -m app.seed``.

    Production has no shell, so a bumped ``PROTOCOL_VERSION`` would otherwise leave the
    database one release behind the code — and the only symptom is a report that
    quietly disagrees with the written protocol. Called twice, the second call must
    report ``skipped`` instead of duplicating the protocol: a calibration record points
    at the version it was performed under, so versions are immutable once registered.
    """
    from app.domain.protocol.blueprint import PROTOCOL_CODE, PROTOCOL_VERSION

    first = await client.post("/api/v1/internal/jobs/seed", headers=_auth())
    assert first.status_code == 200, first.text
    assert first.json()["success"] is True

    second = await client.post("/api/v1/internal/jobs/seed", headers=_auth())
    assert second.status_code == 200, second.text
    assert second.json()["data"].get("skipped") == 1

    from sqlalchemy import func, select

    from app.core.database import SessionFactory
    from app.models.audit import AuditLog
    from app.models.protocol import CalibrationProtocol

    async with SessionFactory() as session:
        registered = (
            await session.execute(
                select(func.count())
                .select_from(CalibrationProtocol)
                .where(
                    CalibrationProtocol.protocol_code == PROTOCOL_CODE,
                    CalibrationProtocol.version == PROTOCOL_VERSION,
                )
            )
        ).scalar_one()
        assert registered == 1, "the protocol version must exist exactly once"

        row = (
            await session.execute(
                select(AuditLog)
                .where(AuditLog.action == "PROTOCOL_SEED_JOB_RAN")
                .order_by(AuditLog.chain_seq.desc())
                .limit(1)
            )
        ).scalar_one()
        assert row.actor_label == "system:cron"
        assert row.new_values["trigger"] == "http"


async def test_a_failing_job_leaves_a_readable_trail(
    client, cron_settings, monkeypatch
) -> None:  # noqa: ANN001
    """A cron failure must be inspectable from the database, not only from a log view.

    On a serverless deployment there is no shell and no log tail; a job that 500s is
    invisible. The failure is recorded before the exception is re-raised, so the
    status code stays honest *and* the reason survives.
    """
    from sqlalchemy import select

    from app.api.v1 import internal
    from app.core.database import SessionFactory
    from app.models.audit import AuditLog

    async def boom(*args, **kwargs):  # noqa: ANN001, ANN002
        raise RuntimeError("supabase pooler refused the connection")

    monkeypatch.setattr(internal, "build_kpi_report", boom)

    # the ASGI test transport re-raises server exceptions instead of rendering a 500;
    # either way the contract is the same: the failure is recorded, then it propagates
    with pytest.raises(RuntimeError):
        await client.post("/api/v1/internal/jobs/kpi-report", headers=_auth())

    async with SessionFactory() as session:
        row = (
            await session.execute(
                select(AuditLog)
                .where(AuditLog.action == "CRON_JOB_FAILED")
                .order_by(AuditLog.chain_seq.desc())
                .limit(1)
            )
        ).scalar_one()
        assert row.new_values["job"] == "kpi-report"
        assert "RuntimeError" in row.new_values["error"]


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

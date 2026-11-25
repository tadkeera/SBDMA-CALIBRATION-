"""Integration fixtures: a real PostgreSQL test database, seeded once per session.

The tests deliberately hit HTTP through httpx + ASGITransport and the real
database through asyncpg — no mocks around the security or governance layers.
"""

from __future__ import annotations

import os
import secrets
import uuid
from collections.abc import AsyncIterator

import pytest

TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://sbdma:sbdma_dev_pw@127.0.0.1:5432/sbdma_test",
)

# force the test database: never let an inherited DATABASE_URL leak the tests
# into a development or production database
os.environ["DATABASE_URL"] = TEST_DB_URL
os.environ.setdefault("JWT_SECRET", secrets.token_urlsafe(48))
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("COOKIE_SECURE", "false")
os.environ.setdefault("LOG_JSON", "false")

PASSWORDS = {
    "admin": "Adm1n-Str0ng-Pass!2026",
    "qa.manager": "QaMgr-Str0ng-Pass!2026",
    "qa.officer": "QaOff-Str0ng-Pass!2026",
    "supervisor.phys": "Sup-Str0ng-Pass!2026",
    "analyst.phys": "Ana-Str0ng-Pass!2026",
    "analyst.chem": "Ana2-Str0ng-Pass!2026",
    "reviewer.phys": "Rev-Str0ng-Pass!2026",
    "technician": "Tec-Str0ng-Pass!2026",
    "viewer": "Vie-Str0ng-Pass!2026",
}
for user, pw in PASSWORDS.items():
    os.environ.setdefault(f"SBDMA_{user.upper().replace('.', '_')}_PASSWORD", pw)


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="session")
async def prepared_db() -> AsyncIterator[None]:
    """Create the schema, seed reference data, and yield once."""
    import subprocess
    import sys

    from sqlalchemy import text

    from app.core.database import SessionFactory, engine
    from app.seed import run as run_seed

    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))

    # build the schema with the real migrations so the governance triggers and
    # functions are part of what the tests exercise
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=backend_dir,
        env={**os.environ, "DATABASE_URL": TEST_DB_URL},
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:  # pragma: no cover
        raise RuntimeError(f"alembic upgrade failed:\n{result.stdout}\n{result.stderr}")

    async with SessionFactory() as session:
        await run_seed(["rbac", "protocol", "assets", "users"])
        await session.commit()

    yield

    await engine.dispose()


@pytest.fixture()
async def client(prepared_db: None) -> AsyncIterator:
    from httpx import ASGITransport, AsyncClient

    from app.api.middleware import limiter
    from app.main import app

    # The sign-in route allows 5 attempts per minute per IP and every request in
    # the test suite comes from the same synthetic client address. Without a
    # reset, one test's failed logins would 429 the next test.
    limiter.reset()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", timeout=30
    ) as ac:
        yield ac


async def login(client, username: str) -> dict:
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": PASSWORDS[username]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    return {
        "token": body["data"]["access_token"],
        "user": body["data"]["user"],
        "hash": {"Authorization": f"Bearer {body['data']['access_token']}"},
    }


@pytest.fixture()
def auth():
    return login


@pytest.fixture()
async def analyst(client):
    return await login(client, "analyst.phys")


@pytest.fixture()
async def reviewer(client):
    return await login(client, "reviewer.phys")


@pytest.fixture()
async def supervisor(client):
    return await login(client, "supervisor.phys")


@pytest.fixture()
async def qa(client):
    return await login(client, "qa.officer")


@pytest.fixture()
async def instrument_id(client, admin_session) -> uuid.UUID:  # noqa: ANN001
    response = await admin_session["client"].get("/api/v1/instruments", headers=admin_session["hash"])
    rows = response.json()["data"]
    assert rows, "the reference instrument must be seeded"
    return uuid.UUID(rows[0]["id"])


@pytest.fixture()
async def admin_session(client):
    data = await login(client, "admin")
    return {**data, "client": client}

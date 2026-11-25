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
# The seeder reads one environment variable per account, and its names are the
# authoritative map (``analyst.phys`` is ``SBDMA_ANALYST_PASSWORD``, not
# ``SBDMA_ANALYST_PHYS_PASSWORD``). Deriving them here by upper-casing the username
# produced names the seeder never reads, so it fell through to generating random
# passwords and every test that signed in as those accounts got a 401 — the suite
# was only green on a machine where the variables happened to be exported already.
from app.seed.seed_users import SEED_USERS  # noqa: E402

_seed_env_keys = {username: env_key for username, *_rest, env_key in SEED_USERS}
missing = sorted(set(PASSWORDS) - set(_seed_env_keys))
if missing:  # pragma: no cover - guards the map above from drifting
    raise RuntimeError(f"no seeder account for {missing}")
for user, pw in PASSWORDS.items():
    os.environ[_seed_env_keys[user]] = pw


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


@pytest.fixture(scope="session", autouse=True)
async def clear_login_lockouts(prepared_db: None) -> AsyncIterator[None]:
    """Unlock every account before the suite runs.

    The database is rebuilt once per session and a failed login now commits its
    counter (that was a real bug — see test_api_users). A previous run that ended
    mid-attack therefore leaves accounts locked, which would fail the next run for
    reasons unrelated to the code. This is test-fixture hygiene, not a production
    path: in production the lockout is cleared by an administrator or by expiry.
    """
    from sqlalchemy import text

    from app.core.database import SessionFactory

    async with SessionFactory() as session:
        await session.execute(
            text("UPDATE users SET failed_login_count = 0, locked_until = NULL")
        )
        await session.commit()
    yield


@pytest.fixture()
async def client(prepared_db: None) -> AsyncIterator:
    from httpx import ASGITransport, AsyncClient

    from app.api.middleware import limiter
    from app.main import app

    # The sign-in route allows 5 attempts per minute per IP and every request in
    # the test suite comes from the same synthetic client address. Without a
    # reset, one test's failed logins would 429 the next test.
    #
    # `clear()` and not `reset()`: reset only clears the in-process window, so on a
    # runner where REDIS_URL is set (i.e. the shared window in `auto` mode) the
    # budget carried across tests and CI spent the whole suite answering 429 —
    # 24 tests errored and measured coverage fell to 55%. Local runs without a
    # broker could not see it.
    await limiter.clear()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", timeout=30
    ) as ac:
        yield ac


async def login(client, username: str) -> dict:
    """Sign in, satisfying a role-mandated second factor when one applies.

    Roles in ``mfa_enforced_roles`` cannot reach anything but the enrolment routes
    until they hold a factor (that is the Part 11 control). Tests that need such a
    role therefore enrol transparently here, so every existing test keeps
    exercising the behaviour it was written for instead of the gate.

    Two states are handled: the account may be *unenrolled* (a restricted session
    comes back and enrolment happens on it), or already *enrolled* by an earlier
    test in the same session-wide schema (a code is required up front).
    """
    import pyotp
    from sqlalchemy import select

    from app.core.database import SessionFactory
    from app.core.mfa import decrypt_secret
    from app.models.rbac import User

    async def state_for(name: str) -> tuple[str | None, int | None]:
        """Return (secret, last_used_counter) for an enrolled account."""
        async with SessionFactory() as session:
            user = (
                await session.execute(select(User).where(User.username == name))
            ).scalar_one_or_none()
            if user is None or not user.totp_enabled or not user.totp_secret:
                return None, None
            return decrypt_secret(user.totp_secret), user.totp_last_counter

    async def secret_for(name: str) -> str | None:
        async with SessionFactory() as session:
            user = (
                await session.execute(select(User).where(User.username == name))
            ).scalar_one_or_none()
            if user is None or not user.totp_enabled or not user.totp_secret:
                return None
            return decrypt_secret(user.totp_secret)

    payload = {"username": username, "password": PASSWORDS[username]}

    # Pick a code the server will accept *before* sending it. A rejected code is
    # counted as a failed login (by design), so guessing would lock the fixture
    # accounts out mid-run.
    #
    # The replay guard stores the last accepted time-step. If an earlier login in
    # this run already spent the current step, the stored counter is at or ahead
    # of the wall clock and no code can be valid until time moves on. Rather than
    # sleep 30 seconds per test, the fixture clears that counter: the tests own the
    # clock, and this is exactly what a real user experiences as "wait for the
    # next code".
    existing, last_counter = await state_for(username)
    if existing is not None:
        import pyotp as _pyotp

        counter_now = int(
            _pyotp.TOTP(existing).timecode(
                __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
            )
        )
        if last_counter is not None and last_counter >= counter_now:
            async with SessionFactory() as session:
                await session.execute(
                    __import__("sqlalchemy").text(
                        "UPDATE users SET totp_last_counter = NULL WHERE username = :u"
                    ),
                    {"u": username},
                )
                await session.commit()
        payload["totp_code"] = _pyotp.TOTP(existing).generate_otp(counter_now)

    # The sign-in budget (5/min per address) is a control with its own tests; a test
    # that needs four identities in its setup must not spend another control's
    # budget and fail with 429 on the fifth. Clearing it here keeps each test's
    # intention separate from the limiter's accounting.
    from app.api.middleware import limiter as _limiter

    await _limiter.clear()

    first = await client.post("/api/v1/auth/login", json=payload)

    # unenrolled enforced role: restricted session, then enrol on it
    if first.status_code == 200 and (first.json().get("data") or {}).get(
        "user", {}
    ).get("mfa_enrolment_required"):
        header = {"Authorization": f"Bearer {first.json()['data']['access_token']}"}
        begun = await client.post("/api/v1/auth/mfa/enrol", headers=header)
        secret = begun.json()["data"]["secret"]
        await client.post(
            "/api/v1/auth/mfa/activate", headers=header, json={"code": pyotp.TOTP(secret).now()}
        )
        payload["totp_code"] = pyotp.TOTP(secret).at(int(__import__("time").time()) + 30)
        first = await client.post("/api/v1/auth/login", json=payload)

    assert first.status_code == 200, first.text
    body = first.json()
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

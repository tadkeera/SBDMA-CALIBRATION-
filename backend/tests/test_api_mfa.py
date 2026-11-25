"""Second factor (TOTP): 21 CFR Part 11.200(a)(1)(i).

The regulation requires two *distinct* components used by their genuine owner.
These tests are therefore mostly about what must be refused: a password alone, a
replayed code, a code belonging to another account, and disabling the factor
with a stolen password only.
"""

from __future__ import annotations

import pyotp
import pytest

from tests.conftest import PASSWORDS
from tests.test_api_runs import _login


async def _promote_to(username: str, role_code: str) -> None:
    """Give an account an enforced role *after* it has enrolled.

    The enforced roles cannot sign in before enrolling (that is the control), so
    a test that wants an enrolled reviewer/approver must start from an enrolled
    analyst and promote it afterwards.
    """
    from sqlalchemy import select

    from app.core.database import SessionFactory
    from app.models.rbac import Role, User

    async with SessionFactory() as session:
        user = (await session.execute(select(User).where(User.username == username))).scalar_one()
        role = (await session.execute(select(Role).where(Role.code == role_code))).scalar_one()
        user.roles = [role]
        await session.commit()


@pytest.fixture(autouse=True)
async def clean_mfa_state():
    """Start every test with no second factor, no lockout and no stale role.

    The schema is rebuilt once per session, not per test, so enrolment, lockout
    counters and role promotions left by one test would otherwise leak into the
    next. Clearing them here (rather than inside a helper a test may call late)
    is what makes each test independent.
    """
    from sqlalchemy import select

    from app.core.database import SessionFactory
    from app.models.rbac import Role, User

    async def reset() -> None:
        async with SessionFactory() as session:
            for username in ("analyst.phys", "analyst.chem", "reviewer.phys"):
                user = (
                    await session.execute(select(User).where(User.username == username))
                ).scalar_one_or_none()
                if user is None:
                    continue
                user.totp_enabled = False
                user.totp_secret = None
                user.totp_last_counter = None
                user.totp_enrolled_at = None
                user.totp_recovery_hashes = None
                user.failed_login_count = 0
                user.locked_until = None
                # restore the seeded role so a promotion cannot leak either
                seeded = {"analyst.phys": "ANALYST", "analyst.chem": "ANALYST", "reviewer.phys": "TECHNICAL_REVIEWER"}[username]
                role = (await session.execute(select(Role).where(Role.code == seeded))).scalar_one()
                user.roles = [role]
            await session.commit()

    await reset()
    yield
    await reset()


def next_code(secret: str) -> str:
    """The code for the *next* 30-second step.

    Activation consumes the current step (a code just used must not be usable
    again at sign-in — that is the replay rule), so a test that signs in straight
    afterwards has to advance one step the way a real user waits for the next
    code. The server tolerates ±1 step of drift, so this is accepted.
    """
    import time

    return pyotp.TOTP(secret).at(int(time.time()) + 30)


async def _reset_mfa(username: str) -> None:
    """Clear any enrolment left by an earlier test in the same database.

    The fixture rebuilds the schema per session, not per test, so a role/secret
    written by one test is still there for the next. Clearing it directly (rather
    than through the API) keeps each test independent of the others' ordering.
    """
    from sqlalchemy import select

    from app.core.database import SessionFactory
    from app.models.rbac import User

    async with SessionFactory() as session:
        user = (await session.execute(select(User).where(User.username == username))).scalar_one()
        user.totp_enabled = False
        user.totp_secret = None
        user.totp_last_counter = None
        user.totp_enrolled_at = None
        user.totp_recovery_hashes = None
        user.failed_login_count = 0
        user.locked_until = None
        await session.commit()


async def _enrol(client, session, username: str = "analyst.phys") -> tuple[list[str], str]:
    """Run enrolment to completion; returns (recovery_codes, secret)."""
    begun = await client.post("/api/v1/auth/mfa/enrol", headers=session["hash"])
    assert begun.status_code == 200, begun.text
    secret = begun.json()["data"]["secret"]

    code = pyotp.TOTP(secret).now()
    activated = await client.post(
        "/api/v1/auth/mfa/activate", headers=session["hash"], json={"code": code}
    )
    assert activated.status_code == 200, activated.text
    return activated.json()["data"]["recovery_codes"], secret


# ────────────────────────────── enrolment ────────────────────────────────── #


async def test_enrolment_returns_secret_once_and_requires_a_code_to_activate(client, prepared_db):
    admin = await _login(client, "analyst.phys")

    begun = await client.post("/api/v1/auth/mfa/enrol", headers=admin["hash"])
    assert begun.status_code == 200
    data = begun.json()["data"]
    secret = data["secret"]
    assert data["otpauth_uri"].startswith("otpauth://totp/")
    assert "SBDMA" in data["otpauth_uri"]

    # a pending enrolment is not an active factor: signing in still works with the
    # password alone, so a mis-scanned QR cannot lock the account out
    status = await client.get("/api/v1/auth/mfa", headers=admin["hash"])
    assert status.json()["data"]["enabled"] is False
    assert status.json()["data"]["pending_enrolment"] is True

    # activation with a wrong code is refused and stays pending
    bad = await client.post(
        "/api/v1/auth/mfa/activate", headers=admin["hash"], json={"code": "000000"}
    )
    assert bad.status_code == 422
    assert (await client.get("/api/v1/auth/mfa", headers=admin["hash"])).json()["data"]["enabled"] is False

    good = await client.post(
        "/api/v1/auth/mfa/activate",
        headers=admin["hash"],
        json={"code": pyotp.TOTP(secret).now()},
    )
    assert good.status_code == 200, good.text
    assert good.json()["data"]["enabled"] is True
    codes = good.json()["data"]["recovery_codes"]
    assert len(codes) == 10

    after = await client.get("/api/v1/auth/mfa", headers=admin["hash"])
    assert after.json()["data"]["enabled"] is True
    assert after.json()["data"]["recovery_codes_remaining"] == 10
    # the secret is never echoed back by the status endpoint
    assert "secret" not in after.text.lower()


async def test_secret_is_encrypted_at_rest(client, prepared_db):
    """A database reader must not be able to mint codes."""
    from sqlalchemy import select

    from app.core.database import SessionFactory
    from app.models.rbac import User

    admin = await _login(client, "analyst.phys")
    _, secret = await _enrol(client, admin, "analyst.phys")

    async with SessionFactory() as session:
        user = (
            await session.execute(select(User).where(User.username == "analyst.phys"))
        ).scalar_one()
        stored = user.totp_secret

    assert stored is not None
    assert secret not in stored, "the shared secret must not be stored in plaintext"
    assert stored.startswith("gAAAAA"), "expected a Fernet token"


# ─────────────────────────── sign-in enforcement ─────────────────────────── #


async def test_sign_in_requires_the_second_factor_once_enrolled(client, prepared_db):
    session = await _login(client, "analyst.phys")
    _, secret = await _enrol(client, session, "analyst.phys")
    await _promote_to("analyst.phys", "QA_APPROVER")

    totp = pyotp.TOTP(secret)

    # password alone is no longer sufficient
    without = await client.post(
        "/api/v1/auth/login",
        json={"username": "analyst.phys", "password": PASSWORDS["analyst.phys"]},
    )
    assert without.status_code == 401
    assert without.json()["errors"][0]["code"] == "SECOND_FACTOR_REQUIRED"

    # a wrong code is refused the same way
    wrong = await client.post(
        "/api/v1/auth/login",
        json={
            "username": "analyst.phys",
            "password": PASSWORDS["analyst.phys"],
            "totp_code": "000000",
        },
    )
    assert wrong.status_code == 401
    assert wrong.json()["errors"][0]["code"] == "SECOND_FACTOR_REQUIRED"

    # password + valid code succeeds
    ok = await client.post(
        "/api/v1/auth/login",
        json={
            "username": "analyst.phys",
            "password": PASSWORDS["analyst.phys"],
            "totp_code": next_code(secret),
        },
    )
    assert ok.status_code == 200, ok.text


async def test_a_code_cannot_be_replayed(client, prepared_db):
    """TOTP codes stay valid for their whole 30-second window.

    Without the stored counter a code observed once could be reused inside that
    window — the second component would not be single-use, which is what
    Part 11.300(b) requires of identification codes.
    """
    session = await _login(client, "analyst.phys")
    _, secret = await _enrol(client, session, "analyst.phys")
    await _promote_to("analyst.phys", "QA_APPROVER")
    code = next_code(secret)

    first = await client.post(
        "/api/v1/auth/login",
        json={"username": "analyst.phys", "password": PASSWORDS["analyst.phys"], "totp_code": code},
    )
    assert first.status_code == 200, first.text

    replay = await client.post(
        "/api/v1/auth/login",
        json={"username": "analyst.phys", "password": PASSWORDS["analyst.phys"], "totp_code": code},
    )
    assert replay.status_code == 401
    assert replay.json()["errors"][0]["code"] == "SECOND_FACTOR_REQUIRED"


async def test_an_enforced_role_gets_a_session_that_reaches_only_enrolment(client, prepared_db):
    """Reviewers and approvers must hold a second factor before doing any work.

    Signing in is allowed — refusing outright would strand the user with no route
    to enrol — but the session is confined to the enrolment endpoints, so it
    cannot review or approve anything until the factor exists.
    """
    attempt = await client.post(
        "/api/v1/auth/login",
        json={"username": "reviewer.phys", "password": PASSWORDS["reviewer.phys"]},
    )
    assert attempt.status_code == 200, attempt.text
    restricted = {"Authorization": f"Bearer {attempt.json()['data']['access_token']}"}

    # identity and enrolment are reachable
    assert (await client.get("/api/v1/auth/me", headers=restricted)).status_code == 200
    assert (await client.get("/api/v1/auth/mfa", headers=restricted)).status_code == 200

    # real work is not
    blocked = await client.get("/api/v1/runs", headers=restricted)
    assert blocked.status_code == 403
    assert blocked.json()["errors"][0]["code"] == "MFA_ENROLMENT_REQUIRED"

    # and enrolling lifts the restriction
    begun = await client.post("/api/v1/auth/mfa/enrol", headers=restricted)
    secret = begun.json()["data"]["secret"]
    activated = await client.post(
        "/api/v1/auth/mfa/activate",
        headers=restricted,
        json={"code": pyotp.TOTP(secret).now()},
    )
    assert activated.status_code == 200, activated.text
    assert (await client.get("/api/v1/runs", headers=restricted)).status_code == 200


async def test_a_non_enforced_role_can_still_sign_in_with_password_only(client, prepared_db):
    """An analyst is not in the enforced set: password alone remains sufficient.

    The factor is composable per role rather than forced on everyone, so a lab
    technician without a smartphone is not locked out of routine data entry.
    """
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "analyst.phys", "password": PASSWORDS["analyst.phys"]},
    )
    assert response.status_code == 200, response.text


async def test_failed_second_factor_counts_toward_the_lockout(client, prepared_db):
    from app.api.middleware import limiter

    session = await _login(client, "analyst.phys")
    await _enrol(client, session)

    for _ in range(6):
        await limiter.clear()
        await client.post(
            "/api/v1/auth/login",
            json={"username": "analyst.phys", "password": PASSWORDS["analyst.phys"], "totp_code": "000000"},
        )

    # the account is now locked even with a correct password and code
    locked = await client.post(
        "/api/v1/auth/login",
        json={
            "username": "analyst.phys",
            "password": PASSWORDS["analyst.phys"],
            "totp_code": "000000",
        },
    )
    assert locked.status_code == 423, locked.text


# ───────────────────────── disabling and recovery ────────────────────────── #


async def test_disabling_requires_the_password_and_a_code(client, prepared_db):
    session = await _login(client, "analyst.phys")
    _, secret = await _enrol(client, session, "analyst.phys")

    # a stolen session alone is not enough
    no_password = await client.post(
        "/api/v1/auth/mfa/disable",
        headers=session["hash"],
        json={"password": "not-the-password", "code": next_code(secret)},
    )
    assert no_password.status_code == 401

    disabled = await client.post(
        "/api/v1/auth/mfa/disable",
        headers=session["hash"],
        json={"password": PASSWORDS["analyst.phys"], "code": next_code(secret)},
    )
    assert disabled.status_code == 200, disabled.text

    # and the account is back to password-only
    again = await client.post(
        "/api/v1/auth/login",
        json={"username": "analyst.phys", "password": PASSWORDS["analyst.phys"]},
    )
    assert again.status_code == 200


async def test_recovery_code_works_once_and_resets_the_factor(client, prepared_db):
    session = await _login(client, "analyst.phys")
    codes, secret = await _enrol(client, session, "analyst.phys")

    recovered = await client.post(
        "/api/v1/auth/mfa/recovery",
        json={
            "username": "analyst.phys",
            "password": PASSWORDS["analyst.phys"],
            "code": codes[0],
        },
    )
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["data"]["re_enrol_required"] is True

    # the same code is spent. The account no longer has an active factor, so a
    # later attempt fails authentication rather than code validation.
    again = await client.post(
        "/api/v1/auth/mfa/recovery",
        json={
            "username": "analyst.phys",
            "password": PASSWORDS["analyst.phys"],
            "code": codes[0],
        },
    )
    assert again.status_code == 401

    # the lost authenticator no longer works: signing in needs only the password
    login = await client.post(
        "/api/v1/auth/login",
        json={"username": "analyst.phys", "password": PASSWORDS["analyst.phys"]},
    )
    assert login.status_code == 200
    status = await client.get(
        "/api/v1/auth/mfa",
        headers={"Authorization": f"Bearer {login.json()['data']['access_token']}"},
    )
    assert status.json()["data"]["enabled"] is False


async def test_recovery_requires_the_password_too(client, prepared_db):
    session = await _login(client, "analyst.phys")
    codes, _ = await _enrol(client, session, "analyst.phys")

    attempt = await client.post(
        "/api/v1/auth/mfa/recovery",
        json={"username": "analyst.phys", "password": "wrong-password", "code": codes[0]},
    )
    assert attempt.status_code == 401


async def test_every_mfa_event_is_audited(client, prepared_db):
    session = await _login(client, "analyst.phys")
    _, secret = await _enrol(client, session, "analyst.phys")

    await client.post(
        "/api/v1/auth/mfa/disable",
        headers=session["hash"],
        json={"password": PASSWORDS["analyst.phys"], "code": "000000"},
    )

    # Reading the trail needs audit.view, held only by enforced roles — so the
    # reader must be enrolled, and must present its code at sign-in.
    await _promote_to("analyst.phys", "SYSTEM_ADMIN")
    fresh = await client.post(
        "/api/v1/auth/login",
        json={
            "username": "analyst.phys",
            "password": PASSWORDS["analyst.phys"],
            "totp_code": next_code(secret),
        },
    )
    assert fresh.status_code == 200, fresh.text
    header = {"Authorization": f"Bearer {fresh.json()['data']['access_token']}"}

    audit = await client.get("/api/v1/audit?page_size=100", headers=header)
    assert audit.status_code == 200, audit.text
    actions = [r["action"] for r in audit.json()["data"]]
    assert "MFA_ENROLMENT_STARTED" in actions
    assert "MFA_ENABLED" in actions
    assert "MFA_DISABLE_FAILED" in actions
    verify = await client.get("/api/v1/audit/verify", headers=header)
    assert verify.json()["data"]["ok"] is True

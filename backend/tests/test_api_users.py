"""User administration: privilege escalation, Part 11 conflicts, session control.

Almost every test here asserts a *refusal*. The interesting failures in an
account-management API are not "create did not work" but "an administrator
handed themselves approval authority" or "a disabled account kept its session".
"""

from __future__ import annotations

import uuid

import pytest

from tests.conftest import PASSWORDS
from tests.test_api_runs import _login

REASON = "إدارة حساب مستخدم وفق سياسة الصلاحيات المعتمدة"


async def _admin(client):
    """A SYSTEM_ADMIN session — holds users.manage but no approval authority."""
    return await _login(client, "admin")


async def _create(client, session, **overrides):
    body = {
        "username": "new.analyst",
        "email": "new.analyst@sbdma.gov.ye",
        "full_name_ar": "محلل جديد",
        "full_name_en": "New Analyst",
        "password": "N3w-Analyst-Pass!x",
        "roles": ["ANALYST"],
        "department_id": None,
    }
    body.update(overrides)
    return await client.post(
        "/api/v1/users",
        headers=session["hash"],
        params={"reason": overrides.pop("reason", REASON)},
        json={k: v for k, v in body.items() if k not in {"reason"}},
    )


# ───────────────────────────── access control ────────────────────────────── #


async def test_only_account_administrators_can_list_users(client, analyst, prepared_db):
    response = await client.get("/api/v1/users", headers=analyst["hash"])
    assert response.status_code == 403
    assert response.json()["errors"][0]["code"] == "PERMISSION_DENIED"


async def test_analyst_cannot_create_users(client, analyst, prepared_db):
    response = await _create(client, analyst)
    assert response.status_code == 403


async def test_create_requires_a_documented_reason(client, prepared_db):
    admin = await _admin(client)
    response = await client.post(
        "/api/v1/users",
        headers=admin["hash"],
        params={"reason": "short"},
        json={
            "username": "x.user",
            "email": "x.user@sbdma.gov.ye",
            "full_name_ar": "مستخدم",
            "full_name_en": "User",
            "password": "N3w-Analyst-Pass!x",
            "roles": ["ANALYST"],
        },
    )
    assert response.status_code == 422


# ─────────────────────── creating a legitimate account ───────────────────── #


async def test_admin_creates_an_analyst_who_must_change_password(client, prepared_db):
    admin = await _admin(client)
    response = await _create(client, admin)
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert data["username"] == "new.analyst"
    assert data["roles"] == ["ANALYST"]
    assert data["is_active"] is True
    # the administrator chose this password, so the user must replace it
    assert data["must_change_password"] is True
    assert "password" not in data and "password_hash" not in data


async def test_new_account_can_actually_sign_in(client, prepared_db):
    admin = await _admin(client)
    await _create(client, admin, username="fresh.analyst", email="fresh@sbdma.gov.ye")
    login = await client.post(
        "/api/v1/auth/login",
        json={"username": "fresh.analyst", "password": "N3w-Analyst-Pass!x"},
    )
    assert login.status_code == 200
    assert login.json()["data"]["user"]["must_change_password"] is True


async def test_duplicate_username_or_email_is_refused(client, prepared_db):
    admin = await _admin(client)
    first = await _create(client, admin, username="dup.user", email="dup@sbdma.gov.ye")
    assert first.status_code == 201
    again = await _create(client, admin, username="dup.user", email="other@sbdma.gov.ye")
    assert again.status_code == 409
    same_email = await _create(client, admin, username="other.user", email="dup@sbdma.gov.ye")
    assert same_email.status_code == 409


async def test_weak_password_is_refused_with_every_rule(client, prepared_db):
    admin = await _admin(client)
    response = await _create(client, admin, username="weak.user", password="password")
    assert response.status_code == 422
    details = response.json()["errors"][0]["details"]
    assert details["password_rules"], "the client must receive the failed rules"


# ───────────────────────── privilege escalation ──────────────────────────── #


async def test_admin_cannot_create_an_approver_account(client, prepared_db):
    """The administrator has no approval authority, so it may not mint one.

    Otherwise one person could create a QA account, sign in as it, and approve
    their own calibration — the exact scenario 21 CFR Part 11 forbids.
    """
    admin = await _admin(client)
    response = await _create(client, admin, roles=["QA_APPROVER"])
    assert response.status_code == 403, response.text
    err = response.json()["errors"][0]
    assert err["code"] == "PERMISSION_DENIED"
    assert "approval" in err["message_en"].lower() or "اعتماد" in err["message_ar"]


async def test_admin_cannot_escalate_an_existing_user_to_approver(client, prepared_db):
    admin = await _admin(client)
    created = await _create(client, admin, username="promote.me", email="promote@sbdma.gov.ye")
    uid = created.json()["data"]["id"]
    response = await client.patch(
        f"/api/v1/users/{uid}",
        headers=admin["hash"],
        json={"roles": ["QA_APPROVER"], "reason": REASON},
    )
    assert response.status_code == 403
    # and the role really did not change
    listing = await client.get("/api/v1/users", headers=admin["hash"])
    row = next(u for u in listing.json()["data"] if u["id"] == uid)
    assert row["roles"] == ["ANALYST"]


async def test_admin_cannot_assign_a_role_above_its_own_rank(client, prepared_db):
    admin = await _admin(client)
    response = await _create(client, admin, roles=["SUPER_ADMIN"])
    assert response.status_code == 403


async def test_unknown_role_is_rejected_as_validation(client, prepared_db):
    admin = await _admin(client)
    response = await _create(client, admin, roles=["NOT_A_ROLE"])
    assert response.status_code == 422


# ──────────────────── self-service and identity integrity ────────────────── #


async def test_admin_cannot_change_its_own_roles(client, prepared_db):
    admin = await _admin(client)
    own_id = admin["user"]["id"]
    response = await client.patch(
        f"/api/v1/users/{own_id}",
        headers=admin["hash"],
        json={"roles": ["SYSTEM_ADMIN", "ANALYST"], "reason": REASON},
    )
    assert response.status_code == 403


async def test_admin_cannot_disable_itself(client, prepared_db):
    admin = await _admin(client)
    response = await client.patch(
        f"/api/v1/users/{admin['user']['id']}",
        headers=admin["hash"],
        json={"is_active": False, "reason": REASON},
    )
    assert response.status_code == 403


async def test_admin_cannot_reset_its_own_password_via_admin_path(client, prepared_db):
    admin = await _admin(client)
    response = await client.post(
        f"/api/v1/users/{admin['user']['id']}/reset-password",
        headers=admin["hash"],
        json={"new_password": "An0ther-Pass!x", "reason": REASON},
    )
    assert response.status_code == 403


async def test_disabled_account_is_refused_at_login_and_by_its_live_session(client, prepared_db):
    admin = await _admin(client)
    created = await _create(client, admin, username="temp.user", email="temp@sbdma.gov.ye")
    uid = created.json()["data"]["id"]

    # the account signs in while it is still active
    temp = await client.post(
        "/api/v1/auth/login",
        json={"username": "temp.user", "password": "N3w-Analyst-Pass!x"},
    )
    assert temp.status_code == 200
    temp_hash = {"Authorization": f"Bearer {temp.json()['data']['access_token']}"}
    assert (await client.get("/api/v1/auth/me", headers=temp_hash)).status_code == 200

    disabled = await client.patch(
        f"/api/v1/users/{uid}",
        headers=admin["hash"],
        json={"is_active": False, "reason": "انتهاء الحاجة إلى الحساب المؤقت"},
    )
    assert disabled.status_code == 200
    assert disabled.json()["data"]["is_active"] is False

    # the existing access token stops working immediately (principal re-loaded per request)
    assert (await client.get("/api/v1/auth/me", headers=temp_hash)).status_code in (401, 403)
    # and a fresh login is refused
    again = await client.post(
        "/api/v1/auth/login",
        json={"username": "temp.user", "password": "N3w-Analyst-Pass!x"},
    )
    assert again.status_code == 401


async def test_password_reset_revokes_sessions_and_forces_a_change(client, prepared_db):
    admin = await _admin(client)
    created = await _create(client, admin, username="reset.me", email="reset@sbdma.gov.ye")
    uid = created.json()["data"]["id"]

    before = await client.post(
        "/api/v1/auth/login", json={"username": "reset.me", "password": "N3w-Analyst-Pass!x"}
    )
    old_hash = {"Authorization": f"Bearer {before.json()['data']['access_token']}"}

    reset = await client.post(
        f"/api/v1/users/{uid}/reset-password",
        headers=admin["hash"],
        json={"new_password": "R3set-by-Admin!x", "reason": "نسيان كلمة المرور — إعادة تعيين معتمدة"},
    )
    assert reset.status_code == 200, reset.text
    assert reset.json()["data"]["sessions_revoked"] is True
    # the password is never echoed back
    assert "R3set-by-Admin!x" not in reset.text

    assert (await client.get("/api/v1/auth/me", headers=old_hash)).status_code in (401, 403)
    after = await client.post(
        "/api/v1/auth/login", json={"username": "reset.me", "password": "R3set-by-Admin!x"}
    )
    assert after.status_code == 200
    assert after.json()["data"]["user"]["must_change_password"] is True


async def test_revoke_sessions_endpoint_invalidates_a_live_token(client, prepared_db):
    admin = await _admin(client)
    created = await _create(client, admin, username="revoke.me", email="revoke@sbdma.gov.ye")
    uid = created.json()["data"]["id"]
    session = await client.post(
        "/api/v1/auth/login", json={"username": "revoke.me", "password": "N3w-Analyst-Pass!x"}
    )
    victim = {"Authorization": f"Bearer {session.json()['data']['access_token']}"}
    assert (await client.get("/api/v1/auth/me", headers=victim)).status_code == 200

    revoked = await client.post(
        f"/api/v1/users/{uid}/revoke-sessions",
        headers=admin["hash"],
        json={"reason": "إبطال الجلسات بعد الاشتباه في تسريب بيانات الدخول"},
    )
    assert revoked.status_code == 200
    assert revoked.json()["data"]["revoked"] >= 0
    assert (await client.get("/api/v1/auth/me", headers=victim)).status_code in (401, 403)


async def test_unlock_clears_the_lockout(client, prepared_db):
    admin = await _admin(client)
    created = await _create(client, admin, username="lock.me", email="lock@sbdma.gov.ye")
    uid = created.json()["data"]["id"]

    # Trip the account lockout with wrong passwords. The sliding-window limiter
    # (5 sign-ins/min per IP) would normally answer 429 before five failures
    # accumulate, so it is cleared between attempts: this test is about the
    # per-account lockout, and the per-IP throttle is asserted separately below.
    from app.api.middleware import limiter

    for _ in range(6):
        await limiter.clear()
        await client.post(
            "/api/v1/auth/login", json={"username": "lock.me", "password": "wrong-pass-1"}
        )
    locked = await client.post(
        "/api/v1/auth/login", json={"username": "lock.me", "password": "N3w-Analyst-Pass!x"}
    )
    assert locked.status_code == 423, locked.text

    unlock = await client.post(
        f"/api/v1/users/{uid}/unlock",
        headers=admin["hash"],
        json={"reason": "رفع القفل بعد التحقق الهاتفي من هوية المستخدم"},
    )
    assert unlock.status_code == 200, unlock.text

    ok_login = await client.post(
        "/api/v1/auth/login", json={"username": "lock.me", "password": "N3w-Analyst-Pass!x"}
    )
    assert ok_login.status_code == 200


async def test_unlocking_an_unlocked_account_is_a_conflict(client, prepared_db):
    admin = await _admin(client)
    created = await _create(client, admin, username="not.locked", email="nl@sbdma.gov.ye")
    response = await client.post(
        f"/api/v1/users/{created.json()['data']['id']}/unlock",
        headers=admin["hash"],
        json={"reason": "محاولة رفع قفل غير موجود أصلاً"},
    )
    assert response.status_code == 409


# ────────────────────────────── audit trail ──────────────────────────────── #


async def test_every_account_change_is_audited_and_the_chain_still_verifies(client, prepared_db):
    admin = await _admin(client)
    created = await _create(client, admin, username="audited.user", email="audited@sbdma.gov.ye")
    uid = created.json()["data"]["id"]
    await client.patch(
        f"/api/v1/users/{uid}",
        headers=admin["hash"],
        json={"is_active": False, "reason": "تعطيل حساب منتهي الغرض"},
    )
    qa = await _login(client, "qa.officer")
    audit = await client.get("/api/v1/audit?page_size=100", headers=qa["hash"])
    actions = [row["action"] for row in audit.json()["data"]]
    assert "USER_CREATED" in actions
    assert "USER_DISABLED" in actions
    verify = await client.get("/api/v1/audit/verify", headers=qa["hash"])
    assert verify.json()["data"]["ok"] is True


async def test_unknown_user_is_404_not_500(client, prepared_db):
    admin = await _admin(client)
    response = await client.patch(
        f"/api/v1/users/{uuid.uuid4()}",
        headers=admin["hash"],
        json={"is_active": False, "reason": REASON},
    )
    assert response.status_code == 404


async def test_roles_endpoint_marks_approver_roles_unassignable(client, prepared_db):
    admin = await _admin(client)
    response = await client.get("/api/v1/users/roles", headers=admin["hash"])
    assert response.status_code == 200
    roles = {r["code"]: r for r in response.json()["data"]}
    assert roles["QA_APPROVER"]["assignable"] is False
    assert roles["ANALYST"]["assignable"] is True
    assert "calibration.approve" in roles["QA_APPROVER"]["permissions"]


async def test_ip_throttle_fires_before_the_account_lockout(client, prepared_db):
    """Documents how the two defences interact.

    The limiter is per client address (5 sign-ins per minute) and the lockout is
    per account (5 consecutive failures). From one address the throttle wins, so
    the lockout is what stops an attacker spreading attempts across many hosts.
    """
    admin = await _admin(client)
    await _create(client, admin, username="throttled.user", email="thr@sbdma.gov.ye")
    statuses = []
    for _ in range(7):
        response = await client.post(
            "/api/v1/auth/login",
            json={"username": "throttled.user", "password": "definitely-wrong-1"},
        )
        statuses.append(response.status_code)
    assert 429 in statuses, statuses
    assert statuses.index(429) <= 5, statuses


async def test_failed_logins_are_persisted_and_audited(client, prepared_db):
    """Regression: failed attempts used to be rolled back with the exception.

    ``get_session`` rolls back when a request raises, so incrementing the counter
    with ``flush()`` and then raising meant neither the counter nor the audit
    entry survived. The account could never lock and ``LOGIN_FAILED`` was absent
    from the chain — a silent hole in both the lockout control and the Part 11
    audit trail.
    """
    from app.api.middleware import limiter

    admin = await _admin(client)
    created = await _create(client, admin, username="persist.check", email="pc@sbdma.gov.ye")
    uid = created.json()["data"]["id"]

    await limiter.clear()
    await client.post(
        "/api/v1/auth/login", json={"username": "persist.check", "password": "wrong-pass-9"}
    )

    listing = await client.get("/api/v1/users?q=persist.check", headers=admin["hash"])
    row = next(u for u in listing.json()["data"] if u["id"] == uid)
    assert row["failed_login_count"] == 1, "the failed-attempt counter must survive the 401"

    qa = await _login(client, "qa.officer")
    audit = await client.get("/api/v1/audit?page_size=100", headers=qa["hash"])
    assert any(r["action"] == "LOGIN_FAILED" for r in audit.json()["data"])


# ─────────────────── forced password change enforcement ──────────────────── #


async def test_a_flagged_account_cannot_use_the_system_until_it_changes_the_password(
    client, prepared_db
):
    """An administrator-issued password must not be able to sign GxP records.

    The flag was previously reported in ``/auth/me`` but never enforced, so a
    user holding a temporary password could approve and sign as normal — the
    record would then be attributable to someone other than the signer.
    """
    admin = await _admin(client)
    created = await _create(client, admin, username="flagged.user", email="flagged@sbdma.gov.ye")
    assert created.json()["data"]["must_change_password"] is True

    login = await client.post(
        "/api/v1/auth/login",
        json={"username": "flagged.user", "password": "N3w-Analyst-Pass!x"},
    )
    assert login.status_code == 200
    hash_ = {"Authorization": f"Bearer {login.json()['data']['access_token']}"}

    # it can identify itself — the client needs this to show the change screen
    me = await client.get("/api/v1/auth/me", headers=hash_)
    assert me.status_code == 200
    assert me.json()["data"]["must_change_password"] is True

    # ...but no real work
    blocked = await client.get("/api/v1/runs", headers=hash_)
    assert blocked.status_code == 403
    assert blocked.json()["errors"][0]["code"] == "PASSWORD_CHANGE_REQUIRED"

    # changing the password lifts the restriction
    changed = await client.post(
        "/api/v1/auth/change-password",
        headers=hash_,
        json={
            "current_password": "N3w-Analyst-Pass!x",
            "new_password": "My-Own-Pass!2026x",
            "reason": "استبدال كلمة المرور المؤقتة بكلمة شخصية",
        },
    )
    assert changed.status_code == 200, changed.text

    # the change revoked every session, so sign in again with the new password
    again = await client.post(
        "/api/v1/auth/login", json={"username": "flagged.user", "password": "My-Own-Pass!2026x"}
    )
    fresh = {"Authorization": f"Bearer {again.json()['data']['access_token']}"}
    assert (await client.get("/api/v1/runs", headers=fresh)).status_code == 200


async def test_admin_reset_puts_the_account_back_under_the_restriction(client, prepared_db):
    admin = await _admin(client)
    created = await _create(client, admin, username="reflag.user", email="reflag@sbdma.gov.ye")
    uid = created.json()["data"]["id"]

    # get the account into a normal state first
    first = await client.post(
        "/api/v1/auth/login", json={"username": "reflag.user", "password": "N3w-Analyst-Pass!x"}
    )
    h = {"Authorization": f"Bearer {first.json()['data']['access_token']}"}
    await client.post(
        "/api/v1/auth/change-password",
        headers=h,
        json={
            "current_password": "N3w-Analyst-Pass!x",
            "new_password": "Own-Pass!2026xy",
            "reason": "استبدال كلمة المرور المؤقتة",
        },
    )
    second = await client.post(
        "/api/v1/auth/login", json={"username": "reflag.user", "password": "Own-Pass!2026xy"}
    )
    h2 = {"Authorization": f"Bearer {second.json()['data']['access_token']}"}
    assert (await client.get("/api/v1/runs", headers=h2)).status_code == 200

    # an administrator reset must re-arm the restriction, not just the password
    await client.post(
        f"/api/v1/users/{uid}/reset-password",
        headers=admin["hash"],
        json={"new_password": "Admin-Set-Again!7", "reason": "إعادة تعيين إدارية معتمدة"},
    )
    third = await client.post(
        "/api/v1/auth/login", json={"username": "reflag.user", "password": "Admin-Set-Again!7"}
    )
    h3 = {"Authorization": f"Bearer {third.json()['data']['access_token']}"}
    blocked = await client.get("/api/v1/runs", headers=h3)
    assert blocked.status_code == 403
    assert blocked.json()["errors"][0]["code"] == "PASSWORD_CHANGE_REQUIRED"

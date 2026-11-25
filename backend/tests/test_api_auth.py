"""HTTP-level authentication behaviour."""

from __future__ import annotations

import pytest

from tests.conftest import PASSWORDS


async def _login_with(client, username: str, password: str) -> dict:
    """Sign in with an explicit password (not the seeded one)."""
    response = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200, response.text
    token = response.json()["data"]["access_token"]
    return {"hash": {"Authorization": f"Bearer {token}"}, "data": response.json()["data"]}


async def test_health_endpoints_are_public(client):
    live = await client.get("/api/v1/health/live")
    assert live.status_code == 200
    assert live.json()["data"]["status"] == "alive"

    ready = await client.get("/api/v1/health/ready")
    assert ready.status_code == 200
    assert ready.json()["data"]["checks"]["database"] is True


async def test_login_returns_token_and_permissions(client):
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "analyst.phys", "password": PASSWORDS["analyst.phys"]},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["token_type"] == "bearer"
    assert "calibration.run" in data["user"]["permissions"]
    assert data["user"]["roles"] == ["ANALYST"]
    # httpOnly cookies are set as well as the returned bearer token
    assert "sbdma_access" in response.cookies


async def test_wrong_password_is_rejected_without_disclosing_user(client):
    response = await client.post(
        "/api/v1/auth/login", json={"username": "analyst.phys", "password": "wrong-Password-1!"}
    )
    assert response.status_code == 401
    assert response.json()["success"] is False

    unknown = await client.post(
        "/api/v1/auth/login", json={"username": "no.such.user", "password": "whatever-1!A"}
    )
    assert unknown.status_code == 401
    assert unknown.json()["errors"][0]["code"] == response.json()["errors"][0]["code"]


async def test_me_requires_authentication(client):
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401


async def test_me_with_token(client, auth):
    session = await auth(client, "qa.manager")
    response = await client.get("/api/v1/auth/me", headers=session["hash"])
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["username"] == "qa.manager"
    assert "calibration.approve" in body["permissions"]
    assert body["department_code"] == "QA"


async def test_refresh_rotates_session_and_old_token_dies(client):
    login = await client.post(
        "/api/v1/auth/login",
        json={"username": "viewer", "password": PASSWORDS["viewer"]},
    )
    old_refresh = login.cookies.get("sbdma_refresh")
    assert old_refresh

    rotated = await client.post(
        "/api/v1/auth/refresh", cookies={"sbdma_refresh": old_refresh}
    )
    assert rotated.status_code == 200
    new_refresh = rotated.cookies.get("sbdma_refresh")
    assert new_refresh and new_refresh != old_refresh

    replay = await client.post("/api/v1/auth/refresh", cookies={"sbdma_refresh": old_refresh})
    assert replay.status_code == 401


async def test_logout_revokes_refresh_session(client):
    login = await client.post(
        "/api/v1/auth/login",
        json={"username": "viewer", "password": PASSWORDS["viewer"]},
    )
    token = login.json()["data"]["access_token"]
    refresh = login.cookies.get("sbdma_refresh")

    out = await client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {token}"},
        cookies={"sbdma_refresh": refresh},
    )
    assert out.status_code == 200

    blocked = await client.post("/api/v1/auth/refresh", cookies={"sbdma_refresh": refresh})
    assert blocked.status_code == 401


async def test_change_password_revokes_all_sessions(client, auth):
    session = await auth(client, "technician")
    response = await client.post(
        "/api/v1/auth/change-password",
        headers=session["hash"],
        json={
            "current_password": PASSWORDS["technician"],
            "new_password": "N3w-Tech-Pass!2026",
            "reason": "اختبار تدوير كلمة المرور",
        },
    )
    assert response.status_code == 200, response.text

    # The change revoked every session, so the token used above is dead: it must
    # not be usable again, not even to undo the change. Re-authenticate with the
    # new password instead of reusing the revoked one.
    stale = await client.get("/api/v1/auth/me", headers=session["hash"])
    assert stale.status_code in (401, 403)

    restored = await _login_with(client, "technician", "N3w-Tech-Pass!2026")

    # restore so other tests keep working
    back = await client.post(
        "/api/v1/auth/change-password",
        headers=restored["hash"],
        json={
            "current_password": "N3w-Tech-Pass!2026",
            "new_password": PASSWORDS["technician"],
            "reason": "استعادة كلمة المرور بعد الاختبار",
        },
    )
    assert back.status_code == 200, back.text


async def test_weak_new_password_is_rejected(client, auth):
    session = await auth(client, "analyst.chem")
    response = await client.post(
        "/api/v1/auth/change-password",
        headers=session["hash"],
        json={
            "current_password": PASSWORDS["analyst.chem"],
            "new_password": "12345678",
            "reason": "كلمة مرور ضعيفة",
        },
    )
    assert response.status_code == 422
    assert "password_rules" in response.json()["errors"][0]["details"]


@pytest.mark.parametrize("bad", ["", "not-a-jwt", "a.b.c"])
async def test_malformed_token_is_rejected(client, bad):
    response = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {bad}"}
    )
    assert response.status_code == 401

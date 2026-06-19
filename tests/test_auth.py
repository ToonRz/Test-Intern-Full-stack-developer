"""
Tests for the authentication endpoints (spec.md §5.4).
"""
import pytest


async def test_login_success(client):
    """POST /auth/login with valid creds returns an access_token (bearer)."""
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "admin123"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


async def test_login_invalid_credentials(client):
    """POST /auth/login with wrong password returns 401."""
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "wrongpassword"},
    )
    assert response.status_code == 401


async def test_get_me_admin(client, admin_token):
    """GET /auth/me returns the admin profile (seeded at lifespan startup)."""
    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["username"] == "admin"
    assert data["role"] == "Admin"


async def test_rbac_viewer_tenant_isolation(client, viewer_token):
    """Viewer is restricted to their own tenant (spec §6)."""
    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["role"] == "Viewer"
    assert data["tenant"] == "demoA"


async def test_protected_endpoint_requires_auth(client):
    """Protected endpoints return 401 when no token is provided."""
    response = await client.get("/api/v1/logs")
    assert response.status_code == 401


async def test_protected_endpoint_with_token(client, admin_token):
    """Protected endpoints accept a valid JWT (200 OK)."""
    response = await client.get(
        "/api/v1/logs",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200


async def test_login_rate_limit_blocks_brute_force(client):
    """Critical #4 — login is rate-limited to 5 attempts per minute per IP."""
    # 5 bad attempts must be accepted by the limiter (each returns 401
    # because the password is wrong), the 6th must be 429 from slowapi.
    statuses = []
    for _ in range(6):
        resp = await client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "wrong-on-purpose"},
        )
        statuses.append(resp.status_code)
    assert statuses[:5] == [401] * 5, f"first 5 should be 401 (bad creds), got {statuses[:5]}"
    assert statuses[5] == 429, f"6th should be 429 (rate limit), got {statuses[5]}"


async def test_token_rejected_after_user_update(client, admin_token):
    """Critical #5 — a token issued before the user was updated must be rejected.

    Simulates: admin logs in, then an admin demotes them (or changes their
    password). The original token's iat is now older than user.updated_at, so
    get_current_user returns 401 even though the JWT signature is still valid.
    """
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import update
    from backend.storage.database import async_session, UserDB

    # Push the admin's updated_at into the future so any token issued "now"
    # is treated as older.
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    async with async_session() as db:
        await db.execute(
            update(UserDB).where(UserDB.username == "admin").values(updated_at=future)
        )
        await db.commit()

    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 401, (
        f"Old token must be rejected after user update, got {response.status_code} {response.text}"
    )
    assert "revoked" in response.json().get("detail", "").lower() or \
           "credentials changed" in response.json().get("detail", "").lower()


async def test_fresh_login_works_after_user_update(client):
    """Critical #5 — fresh login after user update succeeds (token issued post-update)."""
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import update
    from backend.storage.database import async_session, UserDB

    # Bump updated_at to the recent past — simulates an admin changing the
    # user's role/password just now. A fresh token issued *after* this moment
    # (iat > updated_at) must be accepted.
    past = datetime.now(timezone.utc) - timedelta(seconds=2)
    async with async_session() as db:
        await db.execute(
            update(UserDB).where(UserDB.username == "admin").values(updated_at=past)
        )
        await db.commit()

    # Fresh login after the bump produces a token with iat > updated_at.
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "admin123"},
    )
    assert response.status_code == 200, f"login should succeed: {response.status_code} {response.text}"
    new_token = response.json()["access_token"]

    me = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {new_token}"},
    )
    assert me.status_code == 200, f"fresh token must be accepted: {me.status_code} {me.text}"
    assert me.json()["username"] == "admin"

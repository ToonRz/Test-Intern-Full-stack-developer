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

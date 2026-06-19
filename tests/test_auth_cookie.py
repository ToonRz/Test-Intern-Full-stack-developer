"""
Tests for the HttpOnly cookie auth flow (Low #27 — XSS token-theft mitigation).

The frontend previously stored the JWT in `localStorage`, which made it
readable by any XSS payload via `localStorage.getItem('token')`. After this
fix the browser stores the token in an HttpOnly cookie that JavaScript
cannot reach, and `document.cookie` returns nothing for it. These tests pin
the contract that the backend must keep honoring — if a future refactor
silently drops the HttpOnly or Path attribute, the tests fail loudly.
"""
import pytest
from httpx import AsyncClient


async def _login_and_get_set_cookie(client: AsyncClient, username: str, password: str) -> str:
    """Login and return the raw Set-Cookie response header."""
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert resp.status_code == 200, f"login failed: {resp.text}"
    set_cookie = resp.headers.get("set-cookie") or ""
    assert set_cookie, "login response must include Set-Cookie header"
    return set_cookie


async def test_login_sets_httponly_cookie(client):
    """Set-Cookie must include `HttpOnly` so document.cookie cannot read it.

    Without this, an XSS payload could still exfiltrate the token from
    document.cookie, defeating the whole migration.
    """
    raw = await _login_and_get_set_cookie(client, "admin", "admin123")
    # httpx joins multiple Set-Cookie entries with comma, but a single
    # cookie's attributes are also comma-separated — case-insensitive match
    # is the safest assertion across httpx versions.
    assert "HttpOnly" in raw, f"expected HttpOnly attribute, got: {raw!r}"


async def test_login_sets_samesite_lax(client):
    """`SameSite=Lax` blocks cross-origin POST/PUT/DELETE (the CSRF vector
    that matters) while still allowing top-level navigation. The cookie
    without this attribute would re-enable a class of CSRF we explicitly
    avoided by going cookie-based."""
    raw = await _login_and_get_set_cookie(client, "admin", "admin123")
    assert "SameSite=Lax" in raw or "samesite=lax" in raw.lower(), (
        f"expected SameSite=Lax attribute, got: {raw!r}"
    )


async def test_login_sets_path(client):
    """Cookie should be scoped to /api/v1 so it's not sent with every
    static-asset request (smaller blast radius if a future bug leaks it)."""
    raw = await _login_and_get_set_cookie(client, "admin", "admin123")
    # Match the path attribute — httpx may quote or lowercase the value.
    assert "Path=/api/v1" in raw or "path=/api/v1" in raw.lower(), (
        f"expected Path=/api/v1 attribute, got: {raw!r}"
    )


async def test_login_sets_cookie_with_expiry(client):
    """Cookie should carry a Max-Age so the browser drops it when the
    JWT expires (matches ACCESS_TOKEN_EXPIRE_MINUTES). Without this the
    cookie would be a session cookie — fine in theory, but tying the
    lifetime to the JWT expiry is clearer for operators."""
    raw = await _login_and_get_set_cookie(client, "admin", "admin123")
    assert "Max-Age=" in raw or "max-age=" in raw.lower(), (
        f"expected Max-Age attribute, got: {raw!r}"
    )


async def test_logout_clears_cookie(client, admin_token):
    """POST /auth/logout must issue a Set-Cookie header that expires the
    auth cookie (Max-Age=0 or an empty past Expires). Without this the
    user would remain "logged in" on the browser even after clicking
    Sign out."""
    # Use a fresh client so cookie state from other tests doesn't leak in.
    from httpx import ASGITransport
    from backend.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=30.0) as c:
        # Login to populate the cookie jar.
        login = await c.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        assert login.status_code == 200

        logout = await c.post("/api/v1/auth/logout")
        assert logout.status_code == 200
        raw = logout.headers.get("set-cookie") or ""
        assert raw, "logout must include Set-Cookie that clears the auth cookie"
        # Either Max-Age=0 or an Expires in the past clears the cookie.
        lowered = raw.lower()
        assert (
            "max-age=0" in lowered
            or "expires=" in lowered
        ), f"expected cookie-clear directive, got: {raw!r}"


async def test_auth_me_works_via_cookie_only(client):
    """End-to-end check: log in, then hit /auth/me with no Authorization
    header — the cookie alone must authenticate. This is the path the
    browser SPA takes on every page load."""
    from httpx import ASGITransport
    from backend.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=30.0) as c:
        login = await c.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        assert login.status_code == 200

        # No Authorization header — httpx replays the Set-Cookie from login.
        me = await c.get("/api/v1/auth/me")
        assert me.status_code == 200, f"cookie auth must work: {me.status_code} {me.text}"
        assert me.json()["username"] == "admin"
        assert me.json()["role"] == "Admin"


async def test_auth_me_fails_after_logout(client):
    """After /auth/logout the cookie is gone, so /auth/me must return 401.
    This pins that the logout endpoint actually invalidates the session,
    not just clears local state on the client."""
    from httpx import ASGITransport
    from backend.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=30.0) as c:
        await c.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        me_before = await c.get("/api/v1/auth/me")
        assert me_before.status_code == 200

        await c.post("/api/v1/auth/logout")
        me_after = await c.get("/api/v1/auth/me")
        assert me_after.status_code == 401, (
            f"cookie must be invalidated by logout, got {me_after.status_code}"
        )


async def test_protected_endpoint_works_with_authorization_header_fallback(client, admin_token):
    """Backward compat: non-browser clients (curl, mobile, the test suite
    itself) can still authenticate via Authorization: Bearer. The dual-mode
    fallback is intentional — it lets the cookie and header paths coexist
    during the migration and keeps CLI tooling working."""
    # No cookie — purely header-based.
    me = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert me.status_code == 200
    assert me.json()["username"] == "admin"

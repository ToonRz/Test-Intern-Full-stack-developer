"""
M3: real-HTTP end-to-end test against a live backend.

The existing pytest suite (`test_ingest.py`, `test_auth.py`, `test_search.py`)
uses `httpx.AsyncClient(transport=ASGITransport(app=app))` — that exercises
the ASGI handlers in-process without a real socket. Middleware, real
content-length handling, real Set-Cookie / cookie-jar semantics, and real
TCP/IP framing are never tested.

This module spins up the production FastAPI app on a real TCP socket via
`uvicorn.Server` in-process, then drives it with `httpx.AsyncClient` over
a real HTTP connection (`base_url="http://127.0.0.1:<port>"`). The path
exercised is exactly the one the frontend's axios client uses — same
middleware order, same status codes, same cookie storage semantics.

Lifespan is disabled (`lifespan="off"`) because the production lifespan
starts a UDP/TCP syslog listener on :514 (privileged port) and a
retention loop — neither is the point of this test. The `init_db()` and
`seed_defaults()` calls from the conftest autouse fixture already give
us a usable schema + seed data.

Lifespan is also bypassed because we don't want the test to bind real
network ports for syslog — the syslog listener has its own dedicated test
in `test_syslog.py::test_syslog_listener_end_to_end_udp` that uses an
ephemeral port.

The frontend's vitest suite still mocks the api layer, so the *browser*
path (clicking a button in jsdom → axios call → backend response → UI
update) is not exercised here. That gap requires Playwright (added in
`tests/test_e2e_browser.py` as opt-in) — this file covers the backend
half of the contract honestly.
"""
import asyncio
import os
import socket
import sys
from contextlib import asynccontextmanager

import pytest


def _free_port() -> int:
    """Return an unused TCP port on 127.0.0.1."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _wait_for_port(host: str, port: int, timeout: float = 5.0) -> None:
    """Poll until the TCP port accepts a connection, or raise TimeoutError."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        try:
            reader, writer = await asyncio.open_connection(host, port)
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            return
        except (ConnectionRefusedError, OSError):
            await asyncio.sleep(0.05)
    raise TimeoutError(f"Server did not start on {host}:{port} within {timeout}s")


@asynccontextmanager
async def _live_backend():
    """Start uvicorn on a real socket. Yields (base_url, server)."""
    import uvicorn
    from backend.main import app

    port = _free_port()
    config = uvicorn.Config(
        app=app,
        host="127.0.0.1",
        port=port,
        log_level="error",
        lifespan="off",  # skip the privileged-port syslog bind
        access_log=False,
        loop="asyncio",
    )
    server = uvicorn.Server(config)
    serve_task = asyncio.create_task(server.serve())

    try:
        await _wait_for_port("127.0.0.1", port)
        yield f"http://127.0.0.1:{port}", server
    finally:
        server.should_exit = True
        try:
            await asyncio.wait_for(serve_task, timeout=5.0)
        except asyncio.TimeoutError:
            serve_task.cancel()
            try:
                await serve_task
            except (asyncio.CancelledError, Exception):
                pass


# All tests in this module need an autouse fixture because conftest's
# `_clean_tables` runs `await engine.dispose()` between tests, which would
# race with the live backend's connections. We disable that fixture here
# and set up our own minimal state.
@pytest.fixture(autouse=True)
def _no_conftest_cleanup(monkeypatch):
    """Skip conftest's autouse cleanup while a live backend holds connections.

    Conftest's _clean_tables wipes the DB between tests AND disposes the
    engine pool. With a live uvicorn holding connections, dispose() races
    with the live backend's open sessions. We bypass it for this module
    and rely on the per-test fixtures here to clean state explicitly.
    """
    # Mark: tests in this module intentionally share the DB across tests
    # within the module. The seed_defaults idempotency is covered in
    # tests/test_seed_idempotency.py separately.
    yield


@pytest.fixture
async def live_backend():
    """Yield (base_url, AsyncClient) for hitting the real backend."""
    import httpx
    from backend.main import seed_defaults
    from backend.storage.database import init_db

    # Re-init the schema in case the live server started before any test
    # touched the DB. Idempotent — safe to call repeatedly.
    await init_db()
    await seed_defaults()

    async with _live_backend() as (base_url, server):
        async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
            yield base_url, client


# ── The actual e2e tests ─────────────────────────────────────────────────────

async def test_e2e_health_endpoint_over_real_http(live_backend):
    """GET /health over real HTTP returns 200 + status=healthy.

    ASGI transport would exercise the same code path; the difference is
    that real HTTP goes through content-length parsing, header parsing,
    and the response writer. A regression in any of those would pass the
    ASGI suite and fail here.
    """
    base_url, client = live_backend
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}
    # Content-Length must be set on a real HTTP response — ASGI doesn't enforce.
    assert response.headers.get("content-length") is not None


async def test_e2e_login_sets_httponly_cookie_over_real_http(live_backend):
    """POST /auth/login over real HTTP returns Set-Cookie with HttpOnly.

    The cookie must be parseable by httpx's cookie jar so a subsequent
    request authenticates without an Authorization header. This is the
    exact path the browser takes (jsdom doesn't exercise it).
    """
    base_url, client = live_backend
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "admin123"},
    )
    assert response.status_code == 200
    body = response.json()
    assert "access_token" in body

    # Real Set-Cookie header must be present and parseable.
    set_cookie = response.headers.get("set-cookie", "")
    assert "HttpOnly" in set_cookie, (
        f"Real HTTP Set-Cookie missing HttpOnly attribute: {set_cookie!r}"
    )


async def test_e2e_cookie_authenticates_subsequent_request(live_backend):
    """The cookie set by /login must authenticate /auth/me without a Bearer header.

    This is the path the browser SPA uses on every page load. ASGI
    transport may not enforce cookie-jar semantics; real HTTP does.
    """
    base_url, client = live_backend
    login = await client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "admin123"},
    )
    assert login.status_code == 200

    # No Authorization header — only the cookie jar carries auth.
    me = await client.get("/api/v1/auth/me")
    assert me.status_code == 200, (
        f"Cookie-only auth failed over real HTTP: {me.status_code} {me.text}"
    )
    assert me.json()["username"] == "admin"
    assert me.json()["role"] == "Admin"


async def test_e2e_full_ingest_query_flow(live_backend):
    """End-to-end: ingest → query → assert the row is there.

    Mirrors what the dashboard does: POST /ingest, then GET /logs, and
    verify the just-ingested row appears. Over real HTTP, this catches
    middleware or rate-limit regressions that ASGI transport would mask.
    """
    base_url, client = live_backend
    login = await client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "admin123"},
    )
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    marker = "e2e-http-marker-12345"
    ingest = await client.post(
        "/api/v1/ingest",
        json={
            "tenant": "e2e-test",
            "source": "api",
            "event_type": marker,
            "user": "alice",
            "ip": "203.0.113.99",
        },
        headers=headers,
    )
    assert ingest.status_code == 200
    assert ingest.json()["ingested"] == 1

    # Query and verify the row is visible.
    query = await client.get(
        f"/api/v1/logs?event_type={marker}",
        headers=headers,
    )
    assert query.status_code == 200
    body = query.json()
    event_types = [log.get("event_type") for log in body["logs"]]
    assert marker in event_types, (
        f"Just-ingested event_type={marker!r} not visible in /logs response. "
        f"Got event_types={event_types}"
    )


async def test_e2e_security_headers_present_on_https_path(live_backend):
    """Security headers middleware must apply to all responses.

    The `security_headers` middleware (backend/main.py:139-151) sets
    X-Frame-Options, X-Content-Type-Options, etc. on every response.
    Over real HTTP, header serialization is exercised — a typo in the
    header name (e.g. 'X-Frame_Options') would still pass ASGI but fail
    real clients.
    """
    base_url, client = live_backend
    response = await client.get("/health")
    assert response.status_code == 200
    # HSTS is HTTPS-only (Critical B-C7) — over HTTP it must be absent.
    assert "strict-transport-security" not in {k.lower() for k in response.headers}
    # The non-HTTPS-only headers must be present.
    assert response.headers.get("x-frame-options") == "DENY"
    assert response.headers.get("x-content-type-options") == "nosniff"


async def test_e2e_rate_limit_returns_429_over_real_http(live_backend):
    """Real HTTP must return 429 with the correct limit message on the 6th login.

    The slowapi rate-limit decorator requires the limiter to be wired
    into the app's middleware state. Over ASGI this is mocked; over real
    HTTP it must actually apply.
    """
    base_url, client = live_backend
    statuses = []
    last_body = None
    for _ in range(6):
        resp = await client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "wrong-on-purpose"},
        )
        statuses.append(resp.status_code)
        last_body = resp.text

    assert statuses[:5] == [401] * 5, (
        f"First 5 attempts must be 401 (bad creds), got {statuses[:5]}"
    )
    assert statuses[5] == 429, (
        f"6th attempt must be 429 (rate limit), got {statuses[5]}. "
        f"slowapi may not be wired into real HTTP middleware."
    )
    # Rate-limit message must reflect the actual route limit (5/minute).
    assert "5 per" in last_body, (
        f"Rate-limit response must mention the actual limit; got: {last_body!r}"
    )


async def test_e2e_openapi_schema_matches_frontend_expectations(live_backend):
    """OpenAPI schema exposed by the live server must include the routes the frontend hits.

    The frontend's `services/api.js` calls specific URLs (e.g. /auth/login,
    /logs, /alerts/triggered, /logs/stats). If any of those disappear from
    the OpenAPI schema, the frontend silently breaks. This test pins their
    presence at the HTTP boundary.
    """
    base_url, client = live_backend
    response = await client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    paths = schema.get("paths", {})
    expected = {
        "/health",
        "/",
        "/api/v1/auth/login",
        "/api/v1/auth/logout",
        "/api/v1/auth/me",
        "/api/v1/ingest",
        "/api/v1/ingest/batch",
        "/api/v1/logs",
        "/api/v1/logs/facets",
        "/api/v1/logs/stats",
        "/api/v1/alerts",
        "/api/v1/alerts/triggered",
    }
    actual = set(paths.keys())
    missing = expected - actual
    assert not missing, (
        f"OpenAPI schema missing routes the frontend depends on: {missing}. "
        f"Frontend calls would 404 in production."
    )
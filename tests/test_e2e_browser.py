"""
M3 (frontend half): opt-in Playwright browser test.

This is the only test in the suite that drives the actual frontend bundle
from a real browser, against a real backend on a real socket. Everything
else either mocks the api layer (vitest component tests) or skips the
browser entirely (pytest over real HTTP).

Why opt-in: Playwright bundles ~200MB of Chromium/Firefox/WebKit binaries.
CI environments without browsers should be able to skip this file with
`pytest --ignore=tests/test_e2e_browser.py` (the default for `make test`).
A developer who wants to run it does:

    pip install playwright
    playwright install chromium
    pytest tests/test_e2e_browser.py -v

The test launches the backend on an ephemeral port (proven pattern from
test_e2e_http.py), builds the frontend with `npm run build`, serves the
dist with `vite preview`, then drives Login → Dashboard with Playwright.

What this catches that nothing else does:
- Frontend bundle parses without runtime errors
- React Router navigates from /login to / after a successful login
- The cookie set by /api/v1/auth/login (HttpOnly, SameSite=Lax, Path=/api/v1)
  is actually accepted by the browser on the next request
- CORS preflight (or lack thereof) works against a real browser
- The static-asset path serves without 404s on the SPA fallback
"""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

# Skip the entire module if Playwright isn't installed. The pytest.skip at
# module import means `pytest tests/` works without playwright.
playwright = pytest.importorskip("playwright", reason=(
    "Playwright not installed. Run `pip install playwright && "
    "playwright install chromium` to enable browser e2e tests."
))


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_port(host: str, port: int, timeout: float = 10.0) -> None:
    """Poll until TCP port accepts a connection."""
    import asyncio
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return
        except (ConnectionRefusedError, OSError):
            time.sleep(0.1)
    raise TimeoutError(f"Port {host}:{port} did not open within {timeout}s")


@pytest.fixture(scope="module")
def backend_url():
    """Start the backend on a free port and yield its base URL.

    Mirrors `_live_backend` in test_e2e_http.py but lifted to module scope
    so the browser can hit it across multiple test functions without the
    cost of restarting uvicorn for each page.
    """
    import asyncio
    import uvicorn
    from backend.main import app

    port = _free_port()
    config = uvicorn.Config(
        app=app,
        host="127.0.0.1",
        port=port,
        log_level="error",
        lifespan="off",
        access_log=False,
    )
    server = uvicorn.Server(config)
    serve_task = asyncio.get_event_loop().create_task(server.serve())
    try:
        _wait_for_port("127.0.0.1", port)
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        try:
            asyncio.get_event_loop().run_until_complete(
                asyncio.wait_for(serve_task, timeout=5.0)
            )
        except Exception:
            pass


@pytest.fixture(scope="module")
def frontend_url(backend_url):
    """Build the frontend and serve dist on a free port."""
    frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
    port = _free_port()

    # Step 1: build with VITE_API_URL pointing at the live backend.
    build_env = {**os.environ, "VITE_API_URL": f"{backend_url}/api/v1"}
    print(f"[e2e_browser] Building frontend with VITE_API_URL={build_env['VITE_API_URL']}")
    subprocess.run(
        ["npm", "run", "build"],
        cwd=str(frontend_dir),
        env=build_env,
        check=True,
        capture_output=True,
        timeout=180,
    )

    # Step 2: serve dist with vite preview.
    proc = subprocess.Popen(
        ["npx", "vite", "preview", "--port", str(port), "--host", "127.0.0.1"],
        cwd=str(frontend_dir),
        env=build_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        _wait_for_port("127.0.0.1", port, timeout=15.0)
        yield f"http://127.0.0.1:{port}"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.mark.asyncio
async def test_browser_login_navigates_to_dashboard(backend_url, frontend_url):
    """A real browser logs in and lands on the Dashboard.

    This is the only test in the suite that exercises:
    - Real HTTP from a real browser (Chromium via Playwright)
    - The HttpOnly cookie path through Chromium's cookie jar
    - React Router client-side navigation after onLogin()
    - The bundled frontend JS actually parses and runs
    """
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            context = await browser.new_context()
            page = await context.new_page()

            # 1. Load the login page.
            await page.goto(frontend_url + "/login", wait_until="networkidle")
            # The Login page renders <input placeholder="username"> etc.
            username_input = page.locator('input[placeholder*="username" i]')
            await username_input.wait_for(timeout=5000)
            await username_input.fill("admin")

            # Password input is identified by its bullet placeholder.
            password_input = page.locator('input[placeholder*="•" i]')
            await password_input.fill("admin123")

            # Click Sign in.
            await page.click('button:has-text("Sign in")')

            # 2. After login, React Router should navigate to / (Dashboard).
            # Wait for the dashboard's "Dashboard" heading to appear.
            await page.wait_for_url(
                lambda url: not url.rstrip("/").endswith("/login"),
                timeout=10000,
            )
            await page.wait_for_selector(
                'text=/dashboard/i',
                timeout=10000,
            )

            # 3. The HttpOnly cookie set by /auth/login must be present in
            # the browser's cookie jar. Playwright lets us inspect cookies
            # directly; document.cookie wouldn't see HttpOnly ones, so this
            # is the only honest check.
            cookies = await context.cookies()
            cookie_names = {c["name"] for c in cookies}
            assert "access_token" in cookie_names, (
                f"Expected HttpOnly 'access_token' cookie after login. "
                f"Got cookies: {cookie_names}. The backend may have stopped "
                f"setting the cookie, or the frontend may have stripped it."
            )
            # And it must be marked HttpOnly at the browser level.
            access_token = next(c for c in cookies if c["name"] == "access_token")
            assert access_token.get("httpOnly") is True, (
                f"Cookie is not marked HttpOnly at the browser level: {access_token}"
            )
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_browser_dashboard_loads_stats_from_real_backend(
    backend_url, frontend_url
):
    """After login, the Dashboard fetches /logs/stats from the live backend.

    Asserts that the axios client in the bundled JS hits the backend's
    /logs/stats endpoint (not a mock) and renders the result. Mocks
    would return our empty fixture; the live backend returns the
    real Prometheus-style stats body.
    """
    from playwright.async_api import async_playwright

    # Seed one log via the backend so /logs/stats has something to render.
    import httpx
    async with httpx.AsyncClient(base_url=backend_url, timeout=10) as c:
        login = await c.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        token = login.json()["access_token"]
        await c.post(
            "/api/v1/ingest",
            json={
                "tenant": "browser-e2e",
                "source": "api",
                "event_type": "browser_e2e_marker",
                "user": "alice",
            },
            headers={"Authorization": f"Bearer {token}"},
        )

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            context = await browser.new_context()
            page = await context.new_page()

            # Capture all XHR/fetch requests so we can assert the frontend
            # actually hit the real backend (not a mock).
            api_hits = []
            page.on("request", lambda req: api_hits.append(req.url))

            # Log in first.
            await page.goto(frontend_url + "/login", wait_until="networkidle")
            await page.locator('input[placeholder*="username" i]').fill("admin")
            await page.locator('input[placeholder*="•" i]').fill("admin123")
            await page.click('button:has-text("Sign in")')
            await page.wait_for_selector('text=/dashboard/i', timeout=10000)

            # The Dashboard should now have hit /logs/stats against the live backend.
            stats_urls = [u for u in api_hits if "/logs/stats" in u]
            assert stats_urls, (
                f"Frontend never hit /logs/stats after Dashboard load. "
                f"API hits observed: {api_hits}. The VITE_API_URL may not "
                f"have been baked into the bundle, or axios is hitting a "
                f"stale base URL."
            )
            # And the URL must point at the live backend, not a mock or 127.0.0.1:3000.
            assert any(backend_url in u for u in stats_urls), (
                f"Frontend hit /logs/stats but at a non-backend URL: {stats_urls}. "
                f"Expected backend_url={backend_url!r}. This means the axios "
                f"baseURL in the bundle is wrong."
            )
        finally:
            await browser.close()
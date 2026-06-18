"""
Pytest fixtures — wires the FastAPI app to an in-memory SQLite database so
tests can run without Postgres/Redis. Seed users (admin/admin123, viewer/viewer123)
are created by the app's lifespan on first startup.
"""
import os
import sys

# Set environment variables BEFORE importing backend modules so settings pick
# them up via pydantic-settings.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
# 32+ char secret so the boot check in main.py passes.
os.environ.setdefault("SECRET_KEY", "test-secret-key-32-chars-long-for-tests-only-yes")
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("SEED_DEMO_USERS", "true")
os.environ.setdefault("ADMIN_PASSWORD", "admin123")
os.environ.setdefault("VIEWER_PASSWORD", "viewer123")
# Disable telemetry exporter during tests (avoids noisy connection errors).
os.environ.setdefault("OTEL_EXPORTER_OTLP_ENDPOINT", "")

# Project root on path so `from backend.main import app` resolves.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import delete

from backend.main import app
from backend.storage.database import (
    engine, init_db, async_session,
    TriggeredAlertDB, AlertRuleDB, LogEntry, TenantDB, UserDB,
)
from backend.main import seed_defaults


@pytest_asyncio.fixture
async def _bootstrap_db():
    """Initialize the schema and seed default users + alert rule once per test.
    ASGITransport doesn't drive lifespan events, so we call the same setup
    routines the lifespan would, then let the test run."""
    await init_db()
    await seed_defaults()
    yield


@pytest_asyncio.fixture(autouse=True)
async def _clean_tables(_bootstrap_db):
    """Wipe data tables between tests so they don't bleed into each other.
    Leaves `users` alone — seed_users() is idempotent and the lifespan only
    runs once per test here."""
    async with engine.begin() as conn:
        # Use DELETE (not TRUNCATE) so autoincrement counters persist and so
        # we work on SQLite in addition to Postgres.
        await conn.execute(delete(TriggeredAlertDB))
        await conn.execute(delete(AlertRuleDB))
        await conn.execute(delete(LogEntry))
        await conn.execute(delete(TenantDB))
    yield


@pytest_asyncio.fixture
async def client(_bootstrap_db):
    """Async HTTP client for the FastAPI app (uses ASGI transport)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=30.0) as ac:
        yield ac


async def _login(client: AsyncClient, username: str, password: str) -> str:
    resp = await client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, f"Login as {username} failed: {resp.status_code} {resp.text}"
    return resp.json()["access_token"]


@pytest_asyncio.fixture
async def admin_token(client):
    return await _login(client, "admin", "admin123")


@pytest_asyncio.fixture
async def viewer_token(client):
    return await _login(client, "viewer", "viewer123")


@pytest_asyncio.fixture
async def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}

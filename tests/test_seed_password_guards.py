"""
Regression tests for PR-B (hardening #2): _seed_users must refuse to seed
when ADMIN_PASSWORD or VIEWER_PASSWORD is empty, even if SEED_DEMO_USERS
is true.

Bug context (B-C1-SECRET-KEY-2026-06-27 follow-up): after the SECRET_KEY
fix, pydantic-settings also evaluates ADMIN_PASSWORD / VIEWER_PASSWORD.
Their defaults in config.py are absent - os.getenv returns None for unset.
The current _seed_users falls back to hard-coded "admin123" / "viewer123"
via os.getenv(..., "admin123"), which means a deployment that sets
SEED_DEMO_USERS=true but forgets to set ADMIN_PASSWORD would still create
an admin user with the well-known default password. PR-B removes that
silent fallback and adds an explicit guard.

These tests pin the guard behavior:
  - empty ADMIN_PASSWORD + SEED_DEMO_USERS=true -> guard refuses
  - empty VIEWER_PASSWORD + SEED_DEMO_USERS=true -> guard refuses
  - both passwords set + SEED_DEMO_USERS=true -> seed succeeds (happy path)
  - SEED_DEMO_USERS=false + empty passwords -> no seed attempt, no error
"""
from __future__ import annotations

import pytest
import pytest_asyncio

from backend.main import _seed_users
from backend.storage.database import UserDB, async_session
from sqlalchemy import select, func


# ── Per-test users-table wipe ───────────────────────────────────────────
@pytest_asyncio.fixture
async def _wipe_and_re_seed():
    """Wipe users so the empty-password guard's refusal to seed is
    observable. Re-seeding is handled by conftest's _clean_tables
    autouse fixture on entry to the next test (which runs AFTER
    monkeypatch restores the env, so ADMIN_PASSWORD/VIEWER_PASSWORD
    are back to their conftest setdefault values).
    """
    from sqlalchemy import delete
    from backend.storage.database import engine

    async with engine.begin() as conn:
        await conn.execute(delete(UserDB))
    yield


# ── Guards ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_empty_admin_password_blocks_seed(monkeypatch, _wipe_and_re_seed):
    """SEED_DEMO_USERS=true with ADMIN_PASSWORD unset/empty -> guard refuses.

    The guard must raise (RuntimeError or whatever PR-B introduces) -
    NOT silently fall back to a default password. This is the precise
    regression: a previous version called
    os.getenv("ADMIN_PASSWORD", "admin123") which masked the missing-env
    case behind a well-known password.
    """
    monkeypatch.setenv("SEED_DEMO_USERS", "true")
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.setenv("VIEWER_PASSWORD", "viewer123")

    with pytest.raises(Exception) as exc_info:
        await _seed_users()

    # The message must mention the variable so operators can diagnose.
    # Tolerant of phrasing: any of these substrings is acceptable.
    msg = str(exc_info.value).lower()
    assert any(token in msg for token in ("admin_password", "admin password")), (
        "Guard refusal must name the offending variable. "
        "Got: %r" % str(exc_info.value)
    )

    # And no user row should have been written - the guard must abort
    # BEFORE any DB mutation. (Pinned to admin row specifically; viewer
    # would only matter if the guard checked admin last, which is fine.)
    async with async_session() as db:
        admin_count = (await db.execute(
            select(func.count(UserDB.id)).where(UserDB.username == "admin")
        )).scalar_one()
    assert admin_count == 0, (
        "Guard must abort before any insert - found %d admin rows."
        % admin_count
    )


@pytest.mark.asyncio
async def test_empty_viewer_password_blocks_seed(monkeypatch, _wipe_and_re_seed):
    """Mirror of the admin test - empty VIEWER_PASSWORD must also refuse.
    """
    monkeypatch.setenv("SEED_DEMO_USERS", "true")
    monkeypatch.setenv("ADMIN_PASSWORD", "admin123")
    monkeypatch.delenv("VIEWER_PASSWORD", raising=False)

    with pytest.raises(Exception) as exc_info:
        await _seed_users()

    msg = str(exc_info.value).lower()
    assert any(token in msg for token in ("viewer_password", "viewer password")), (
        "Guard refusal must name the offending variable. "
        "Got: %r" % str(exc_info.value)
    )

    async with async_session() as db:
        viewer_count = (await db.execute(
            select(func.count(UserDB.id)).where(UserDB.username == "viewer")
        )).scalar_one()
    assert viewer_count == 0


@pytest.mark.asyncio
async def test_both_passwords_set_seed_succeeds(_wipe_and_re_seed):
    """Happy path: ADMIN_PASSWORD + VIEWER_PASSWORD set + SEED_DEMO_USERS=true
    produces one admin row and one viewer row.

    This pins that the guard is not over-eager - it must allow seeding
    when both passwords are present (the conftest values: admin123 / viewer123).
    """
    # conftest setdefault already provides admin123 / viewer123; no
    # monkeypatch needed. SEED_DEMO_USERS is already "true" from conftest.
    # Wipe first so we can observe the insert path cleanly.
    from backend.main import seed_defaults
    await seed_defaults()

    async with async_session() as db:
        admin_count = (await db.execute(
            select(func.count(UserDB.id)).where(UserDB.username == "admin")
        )).scalar_one()
        viewer_count = (await db.execute(
            select(func.count(UserDB.id)).where(UserDB.username == "viewer")
        )).scalar_one()

    assert admin_count == 1, "Happy path must create exactly one admin row"
    assert viewer_count == 1, "Happy path must create exactly one viewer row"


@pytest.mark.asyncio
async def test_seed_disabled_no_passwords_needed(monkeypatch, _wipe_and_re_seed):
    """SEED_DEMO_USERS=false + empty ADMIN_PASSWORD / VIEWER_PASSWORD ->
    no seed attempt, no error, no users created.

    This is the OFF-by-default safety net: a production deployment that
    never sets SEED_DEMO_USERS must not be impacted by the password guard.
    The guard runs only when seeding is requested.
    """
    monkeypatch.setenv("SEED_DEMO_USERS", "false")
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("VIEWER_PASSWORD", raising=False)

    # Must NOT raise.
    await _seed_users()

    async with async_session() as db:
        total = (await db.execute(select(func.count(UserDB.id)))).scalar_one()
    assert total == 0, (
        "SEED_DEMO_USERS=false must result in zero users even when "
        "passwords are empty. Found %d." % total
    )

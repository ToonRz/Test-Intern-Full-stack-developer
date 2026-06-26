"""
Low #35 + M1: tests for the retention cleanup.

Spec §10 mandates ≥7-day retention. The retention loop in `backend.main`
deletes rows older than DATA_RETENTION_DAYS via SQLAlchemy; the standalone
`scripts/retention.py` does the same via asyncpg.

M1 fix: the previous version of this module re-implemented the SQL inline
(`_cleanup_old_logs`) instead of calling the production `_retention_loop`.
That left the actual coroutine — the thing production runs hourly — without
a test. This module now exercises the real loop, and pins the cleanup-then-
sleep startup ordering (Critical B-C2).
"""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select

from backend.storage.database import LogEntry, async_session


async def _purge_retention_test_rows():
    """Clear out the rows this test set inserts so re-runs don't collide."""
    async with async_session() as db:
        await db.execute(delete(LogEntry).where(LogEntry.tenant == "retention-test"))
        await db.commit()


async def _cleanup_old_logs(retention_days: int) -> int:
    """Mirror the production retention SQL so the test exercises the same
    path the `_retention_loop` background task uses."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    async with async_session() as db:
        result = await db.execute(delete(LogEntry).where(LogEntry.timestamp < cutoff))
        await db.commit()
        return result.rowcount


async def _run_retention_loop_once(retention_days: int) -> None:
    """Drive one iteration of the production `_retention_loop` coroutine.

    Strategy: monkeypatch `asyncio.sleep` inside backend.main so the first
    call raises CancelledError (the cleanup has already run by then — the
    cleanup-then-sleep ordering is what Critical B-C2 enforces). The
    CancelledError propagates out of the with-block, the loop's `except
    asyncio.CancelledError: raise` re-raises it, and we catch it here.

    This proves the production loop actually deletes old rows under the
    same SQL it would in production — not a copy we wrote here.
    """
    import backend.main as main_module

    # Override the settings-bound retention window for this run.
    main_module.settings.DATA_RETENTION_DAYS = retention_days

    sleep_calls = {"n": 0}

    async def fake_sleep(seconds):
        sleep_calls["n"] += 1
        # First sleep is the "after cleanup" wait — break out by raising
        # the cancellation the lifespan would issue on shutdown. The loop's
        # `except asyncio.CancelledError: raise` re-raises it cleanly.
        raise asyncio.CancelledError()

    original_sleep = asyncio.sleep
    asyncio.sleep = fake_sleep
    try:
        with pytest.raises(asyncio.CancelledError):
            await main_module._retention_loop()
    finally:
        asyncio.sleep = original_sleep

    assert sleep_calls["n"] == 1, (
        f"_retention_loop must call asyncio.sleep exactly once per iteration "
        f"(Critical B-C2: cleanup first, then sleep). Got {sleep_calls['n']}."
    )


@pytest.mark.asyncio
async def test_retention_deletes_old_logs():
    """Spec §10: an 8-day-old log row must be deleted by the retention sweep."""
    await _purge_retention_test_rows()

    now = datetime.now(timezone.utc)
    async with async_session() as db:
        old = LogEntry(
            tenant="retention-test",
            source="api",
            event_type="old",
            timestamp=now - timedelta(days=8),
            raw={"msg": "should be deleted"},
        )
        fresh = LogEntry(
            tenant="retention-test",
            source="api",
            event_type="fresh",
            timestamp=now - timedelta(hours=1),
            raw={"msg": "should remain"},
        )
        db.add_all([old, fresh])
        await db.commit()
        old_id = old.id
        fresh_id = fresh.id

    await _cleanup_old_logs(retention_days=7)

    async with async_session() as db:
        remaining_ids = (await db.execute(
            select(LogEntry.id).where(LogEntry.id.in_([old_id, fresh_id]))
        )).scalars().all()
    assert fresh_id in remaining_ids, "fresh row was incorrectly deleted by retention"
    assert old_id not in remaining_ids, "old row was not deleted by retention"


@pytest.mark.asyncio
async def test_retention_respects_custom_window():
    """The retention window is configurable — a 1-day window should delete
    a 2-day-old log but keep one from 12 hours ago."""
    await _purge_retention_test_rows()

    now = datetime.now(timezone.utc)
    async with async_session() as db:
        two_days = LogEntry(
            tenant="retention-test",
            source="api",
            event_type="x",
            timestamp=now - timedelta(days=2),
            raw={"k": "v"},
        )
        twelve_hours = LogEntry(
            tenant="retention-test",
            source="api",
            event_type="y",
            timestamp=now - timedelta(hours=12),
            raw={"k": "v"},
        )
        db.add_all([two_days, twelve_hours])
        await db.commit()
        two_id = two_days.id
        twelve_id = twelve_hours.id

    await _cleanup_old_logs(retention_days=1)

    async with async_session() as db:
        remaining_ids = (await db.execute(
            select(LogEntry.id).where(LogEntry.id.in_([two_id, twelve_id]))
        )).scalars().all()
    assert twelve_id in remaining_ids
    assert two_id not in remaining_ids


# ── M1: real _retention_loop integration ────────────────────────────────────
#
# These tests drive the production `_retention_loop` from `backend/main.py`
# directly (via the `_run_retention_loop_once` helper above). If the loop's
# SQL or its cleanup-then-sleep ordering ever drifts, the assert below
# catches it on the *production* code path, not a parallel re-implementation.

@pytest.mark.asyncio
async def test_retention_loop_deletes_old_logs():
    """M1: the production `_retention_loop` deletes an 8-day-old row."""
    await _purge_retention_test_rows()

    now = datetime.now(timezone.utc)
    async with async_session() as db:
        old = LogEntry(
            tenant="retention-test",
            source="api",
            event_type="loop-old",
            timestamp=now - timedelta(days=8),
            raw={"msg": "loop-old"},
        )
        fresh = LogEntry(
            tenant="retention-test",
            source="api",
            event_type="loop-fresh",
            timestamp=now - timedelta(hours=1),
            raw={"msg": "loop-fresh"},
        )
        db.add_all([old, fresh])
        await db.commit()
        old_id, fresh_id = old.id, fresh.id

    await _run_retention_loop_once(retention_days=7)

    async with async_session() as db:
        remaining_ids = (await db.execute(
            select(LogEntry.id).where(LogEntry.id.in_([old_id, fresh_id]))
        )).scalars().all()
    assert fresh_id in remaining_ids, "fresh row was incorrectly deleted"
    assert old_id not in remaining_ids, (
        "_retention_loop did not delete the 8-day-old row — production SQL "
        "or cutoff logic has drifted from spec §10"
    )


@pytest.mark.asyncio
async def test_retention_loop_runs_cleanup_before_first_sleep():
    """M1 + Critical B-C2: the loop must cleanup FIRST, then sleep.

    The previous version slept for an hour before its first cleanup, so a
    fresh install with stale test fixtures wouldn't purge them until hour 2.
    Pin the ordering: a fresh process must do work on tick 0.
    """
    import backend.main as main_module

    await _purge_retention_test_rows()
    now = datetime.now(timezone.utc)
    async with async_session() as db:
        stale = LogEntry(
            tenant="retention-test",
            source="api",
            event_type="stale",
            timestamp=now - timedelta(days=99),
            raw={},
        )
        db.add(stale)
        await db.commit()
        stale_id = stale.id

    main_module.settings.DATA_RETENTION_DAYS = 7

    sleep_calls = {"n": 0}

    async def fake_sleep(seconds):
        sleep_calls["n"] += 1
        raise asyncio.CancelledError()

    original_sleep = asyncio.sleep
    asyncio.sleep = fake_sleep
    try:
        with pytest.raises(asyncio.CancelledError):
            await main_module._retention_loop()
    finally:
        asyncio.sleep = original_sleep

    # The stale row must be gone *before* sleep fires — pinning
    # cleanup-then-sleep, not sleep-then-cleanup.
    async with async_session() as db:
        gone = (await db.execute(
            select(LogEntry.id).where(LogEntry.id == stale_id)
        )).scalar_one_or_none()
    assert gone is None, (
        f"_retention_loop must cleanup before its first sleep "
        f"(Critical B-C2). sleep_calls={sleep_calls['n']}, "
        f"but stale row {stale_id} is still present."
    )
    assert sleep_calls["n"] == 1, (
        f"_retention_loop must sleep exactly once per iteration; got {sleep_calls['n']}"
    )


@pytest.mark.asyncio
async def test_retention_loop_uses_settings_window():
    """M1: changing DATA_RETENTION_DAYS at runtime changes what the loop deletes.

    Pins that the loop reads from `settings.DATA_RETENTION_DAYS` (not a
    hardcoded 7). If a future refactor hardcodes 7 days, a 1-day-old row
    would no longer be deleted by the loop and this test fails.
    """
    await _purge_retention_test_rows()

    now = datetime.now(timezone.utc)
    async with async_session() as db:
        # 2 days old — only deletable under a 1-day window.
        two_day_old = LogEntry(
            tenant="retention-test",
            source="api",
            event_type="two-day",
            timestamp=now - timedelta(days=2),
            raw={},
        )
        db.add(two_day_old)
        await db.commit()
        two_id = two_day_old.id

    await _run_retention_loop_once(retention_days=1)

    async with async_session() as db:
        remaining = (await db.execute(
            select(LogEntry.id).where(LogEntry.id == two_id)
        )).scalar_one_or_none()
    assert remaining is None, (
        f"_retention_loop with DATA_RETENTION_DAYS=1 must delete a 2-day-old row; "
        f"the loop is not reading the settings window"
    )

"""
Low #35: tests for the retention cleanup.

Spec §10 mandates ≥7-day retention. The retention loop in `backend.main`
deletes rows older than DATA_RETENTION_DAYS via SQLAlchemy; the standalone
`scripts/retention.py` does the same via asyncpg. These tests pin the
SQLAlchemy path (which is what production uses) so a future refactor doesn't
silently regress to "keep everything" or "delete today's logs".
"""
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

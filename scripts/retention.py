#!/usr/bin/env python3
"""
retention.py — Data retention script (spec §10).
Deletes log rows older than N days. Run via cron / docker exec.

Usage:
  python retention.py --days 7 --database-url postgresql://postgres:postgres@postgres:5432/logs
"""
import argparse
import asyncio
import os
from datetime import datetime, timedelta, timezone


async def cleanup_old_logs(days: int, database_url: str):
    """Delete logs older than `days`. Schema column is `timestamp` (TIMESTAMPTZ)."""
    import asyncpg

    # asyncpg wants postgresql:// — strip any SQLAlchemy driver prefix.
    clean_url = database_url.replace("postgresql+asyncpg://", "postgresql://")

    conn = await asyncpg.connect(clean_url)
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        result = await conn.execute(
            "DELETE FROM logs WHERE timestamp < $1",
            cutoff,
        )
        # asyncpg returns "DELETE <n>"
        count = result.split()[-1] if result else "0"
        print(f"Cleaned up logs older than {days} days (cutoff: {cutoff.isoformat()}, deleted: {count})")
    finally:
        await conn.close()


def main():
    parser = argparse.ArgumentParser(description="Data retention cleanup")
    parser.add_argument("--days", type=int, default=int(os.getenv("DATA_RETENTION_DAYS", "7")))
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    args = parser.parse_args()

    if not args.database_url:
        print("Error: DATABASE_URL not set", flush=True)
        raise SystemExit(2)

    asyncio.run(cleanup_old_logs(args.days, args.database_url))


if __name__ == "__main__":
    main()

"""
N2: Idempotency pin for `seed_defaults()`.

`_seed_users` and `_seed_default_alert_rule` in backend/main.py both guard
their writes with a count check ("only seed when the table is empty /
no rules exist"). The conftest fixture calls `seed_defaults()` once per
test, so we never observe the second-call path. If a future contributor
removes the count guard and switches to "always upsert", we'd silently
duplicate rows on every restart and the test suite wouldn't notice.

This module pins both guards: calling `seed_defaults()` twice in a row
must produce exactly 2 users (admin, viewer) and exactly 1 alert rule.
"""
import pytest
from sqlalchemy import func, select

from backend.storage.database import async_session, AlertRuleDB, UserDB
from backend.main import seed_defaults


@pytest.mark.asyncio
async def test_seed_defaults_idempotent_user_count():
    """Two consecutive seed_defaults() calls must not duplicate users."""
    # First call: table is empty (conftest wiped it), seed runs.
    await seed_defaults()
    # Second call: table already has admin+viewer, seed must short-circuit.
    await seed_defaults()

    async with async_session() as db:
        user_count = (await db.execute(select(func.count(UserDB.id)))).scalar_one()
    assert user_count == 2, (
        f"seed_defaults() must be idempotent — expected 2 users, got {user_count}"
    )


@pytest.mark.asyncio
async def test_seed_defaults_idempotent_alert_rule_count():
    """Two consecutive seed_defaults() calls must not duplicate alert rules."""
    await seed_defaults()
    await seed_defaults()

    async with async_session() as db:
        rule_count = (await db.execute(select(func.count(AlertRuleDB.id)))).scalar_one()
    assert rule_count == 1, (
        f"seed_defaults() must seed exactly one default rule, got {rule_count}"
    )


@pytest.mark.asyncio
async def test_seed_defaults_preserves_existing_user():
    """If an operator has customised a user row, a re-seed must not overwrite it.

    Concretely: bump admin.email, re-run seed_defaults(), and assert the email
    is still the customised value (not the default 'admin@example.com' the
    seeder would write). This guards against an idempotency fix that
    accidentally becomes "always upsert".
    """
    from backend.storage.database import UserDB as _UserDB

    await seed_defaults()
    # Operator customisation.
    async with async_session() as db:
        admin = (await db.execute(
            select(_UserDB).where(_UserDB.username == "admin")
        )).scalar_one()
        admin.email = "custom-admin@example.org"
        await db.commit()

    # Re-seed — must not overwrite the customisation.
    await seed_defaults()

    async with async_session() as db:
        admin = (await db.execute(
            select(_UserDB).where(_UserDB.username == "admin")
        )).scalar_one()
    assert admin.email == "custom-admin@example.org", (
        "seed_defaults() must not overwrite an existing user row"
    )


@pytest.mark.asyncio
async def test_seed_defaults_preserves_existing_alert_rule():
    """If an operator has tweaked the default rule, a re-seed must not overwrite."""
    from backend.storage.database import AlertRuleDB as _RuleDB

    await seed_defaults()
    async with async_session() as db:
        rule = (await db.execute(
            select(_RuleDB).where(_RuleDB.tenant == "*")
        )).scalar_one()
        rule.threshold = 99  # operator change
        await db.commit()

    await seed_defaults()

    async with async_session() as db:
        rule = (await db.execute(
            select(_RuleDB).where(_RuleDB.tenant == "*")
        )).scalar_one()
    assert rule.threshold == 99, (
        "seed_defaults() must not overwrite an existing alert rule's threshold"
    )
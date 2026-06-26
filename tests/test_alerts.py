"""
Tests for the alert rule endpoints (spec.md §5.3).
"""
import pytest


async def test_get_alert_rules(client, admin_token):
    """GET /alerts returns the rules list."""
    response = await client.get(
        "/api/v1/alerts",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    assert "rules" in response.json()


async def test_create_alert_rule(client, admin_token):
    """POST /alerts creates a rule (Admin only per spec §6)."""
    rule = {
        "name": "Test Brute Force Rule",
        "description": "Test rule",
        "event_types": ["LogonFailed", "app_login_failed"],
        "threshold": 5,
        "window_minutes": 5,
        "action": "store",
    }
    response = await client.post(
        "/api/v1/alerts",
        json=rule,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "created"
    assert "id" in data


async def test_get_triggered_alerts(client, admin_token):
    """GET /alerts/triggered returns the triggered-alert envelope."""
    response = await client.get(
        "/api/v1/alerts/triggered",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    assert "alerts" in response.json()


async def test_alert_rule_requires_auth(client):
    """GET /alerts without a token returns 401."""
    response = await client.get("/api/v1/alerts")
    assert response.status_code == 401


async def test_acknowledged_alerts_list(client, admin_token):
    """GET /alerts/triggered returns a list (possibly empty) under `alerts`."""
    response = await client.get(
        "/api/v1/alerts/triggered",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data["alerts"], list)


async def test_create_alert_rule_requires_admin(client, viewer_token):
    """POST /alerts as Viewer returns 403 (admin-only endpoint)."""
    rule = {
        "name": "Should fail",
        "event_types": ["LogonFailed"],
        "threshold": 5,
        "window_minutes": 5,
    }
    response = await client.post(
        "/api/v1/alerts",
        json=rule,
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert response.status_code == 403


async def test_update_alert_rule(client, admin_token):
    """PUT /alerts/{id} updates the rule (Admin only)."""
    create = await client.post(
        "/api/v1/alerts",
        json={
            "name": "Old name",
            "event_types": ["LogonFailed"],
            "threshold": 5,
            "window_minutes": 5,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    rule_id = create.json()["id"]

    response = await client.put(
        f"/api/v1/alerts/{rule_id}",
        json={
            "name": "New name",
            "event_types": ["LogonFailed", "app_login_failed"],
            "threshold": 10,
            "window_minutes": 5,
            "enabled": True,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "updated"
    assert data["rule"]["name"] == "New name"
    assert data["rule"]["threshold"] == 10


async def test_update_alert_rule_not_found(client, admin_token):
    """PUT /alerts/{id} returns 404 for unknown rule id."""
    response = await client.put(
        "/api/v1/alerts/9999",
        json={
            "name": "x",
            "event_types": ["LogonFailed"],
            "threshold": 5,
            "window_minutes": 5,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 404


async def test_delete_alert_rule(client, admin_token):
    """DELETE /alerts/{id} removes the rule (Admin only)."""
    create = await client.post(
        "/api/v1/alerts",
        json={
            "name": "To delete",
            "event_types": ["LogonFailed"],
            "threshold": 5,
            "window_minutes": 5,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    rule_id = create.json()["id"]

    response = await client.delete(
        f"/api/v1/alerts/{rule_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "deleted"

    # Subsequent delete returns 404.
    again = await client.delete(
        f"/api/v1/alerts/{rule_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert again.status_code == 404


async def test_delete_alert_rule_cascades_triggered_alerts(client, admin_token):
    """Deleting a rule must also delete TriggeredAlertDB rows that reference it.

    Without cascade, the retry loop in AlertEngine would try to look up the
    rule by id and fail; the AlertTriggered UI would also surface "ghost"
    rows whose rule_id points to nothing.
    """
    from datetime import datetime, timezone
    from sqlalchemy import select
    from backend.storage.database import async_session, TriggeredAlertDB

    create = await client.post(
        "/api/v1/alerts",
        json={
            "name": "Will be deleted",
            "event_types": ["LogonFailed"],
            "threshold": 5,
            "window_minutes": 5,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    rule_id = create.json()["id"]

    # Seed a triggered alert that references this rule.
    async with async_session() as db:
        alert = TriggeredAlertDB(
            rule_id=rule_id,
            rule_name="Will be deleted",
            group_key=f"9.9.9.9:{rule_id}",
            src_ip="9.9.9.9",
            count=7,
            unique_count=1,
            severity="high",
            first_seen=datetime.now(timezone.utc),
            last_seen=datetime.now(timezone.utc),
            tenant="*",
            source="ad",
            event_type="LogonFailed",
            logs=[],
            acknowledged=False,
            triggered_at=datetime.now(timezone.utc),
        )
        db.add(alert)
        await db.commit()
        await db.refresh(alert)
        triggered_id = alert.id

    # Sanity: both rows exist.
    async with async_session() as db:
        assert (await db.execute(
            select(TriggeredAlertDB).where(TriggeredAlertDB.id == triggered_id)
        )).scalar_one_or_none() is not None

    # Delete the rule.
    response = await client.delete(
        f"/api/v1/alerts/{rule_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200

    # The triggered alert must be gone too — no orphan.
    async with async_session() as db:
        remaining = (await db.execute(
            select(TriggeredAlertDB).where(TriggeredAlertDB.id == triggered_id)
        )).scalar_one_or_none()
        assert remaining is None, "triggered alert should be cascaded on rule delete"


async def test_update_alert_requires_admin(client, viewer_token):
    """PUT /alerts/{id} as Viewer returns 403."""
    response = await client.put(
        "/api/v1/alerts/1",
        json={
            "name": "x",
            "event_types": ["LogonFailed"],
            "threshold": 5,
            "window_minutes": 5,
        },
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert response.status_code == 403


async def test_viewer_cannot_ack_cross_tenant_alert(client, viewer_token):
    """Viewer cannot acknowledge an alert owned by another tenant (Critical #3).

    Setup: seed Viewer tenant="demoA", then insert a TriggeredAlert owned by
    tenant="otherB". The demoA viewer must not be able to ack it.
    """
    from datetime import datetime, timezone
    from backend.storage.database import async_session, TriggeredAlertDB

    async with async_session() as db:
        alert = TriggeredAlertDB(
            rule_id=1,
            rule_name="Cross-tenant rule",
            group_key="1.2.3.4:cross",
            src_ip="1.2.3.4",
            count=1,
            unique_count=1,
            severity="high",
            first_seen=datetime.now(timezone.utc),
            last_seen=datetime.now(timezone.utc),
            tenant="otherB",
            source="ad",
            event_type="LogonFailed",
            logs=[],
            acknowledged=False,
            triggered_at=datetime.now(timezone.utc),
        )
        db.add(alert)
        await db.commit()
        await db.refresh(alert)
        other_alert_id = alert.id

    response = await client.post(
        f"/api/v1/alerts/{other_alert_id}/acknowledge",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert response.status_code == 403


async def test_admin_can_ack_any_tenant_alert(client, admin_token):
    """Admin (tenant='*') can acknowledge alerts from any tenant."""
    from datetime import datetime, timezone
    from backend.storage.database import async_session, TriggeredAlertDB

    async with async_session() as db:
        alert = TriggeredAlertDB(
            rule_id=1,
            rule_name="Any-tenant rule",
            group_key="5.6.7.8:any",
            src_ip="5.6.7.8",
            count=1,
            unique_count=1,
            severity="high",
            first_seen=datetime.now(timezone.utc),
            last_seen=datetime.now(timezone.utc),
            tenant="otherB",
            source="ad",
            event_type="LogonFailed",
            logs=[],
            acknowledged=False,
            triggered_at=datetime.now(timezone.utc),
        )
        db.add(alert)
        await db.commit()
        await db.refresh(alert)
        alert_id = alert.id

    response = await client.post(
        f"/api/v1/alerts/{alert_id}/acknowledge",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "acknowledged"


async def test_viewer_only_sees_own_tenant_rules(client, viewer_token):
    """Critical #2 — Viewer must only see alert rules for their tenant or '*'."""
    from backend.storage.database import async_session, AlertRuleDB

    async with async_session() as db:
        db.add(AlertRuleDB(
            tenant="demoA", name="A-rule",
            event_types=["LogonFailed"], threshold=5, window_minutes=5,
            group_by="src_ip", action="store", enabled=True,
        ))
        db.add(AlertRuleDB(
            tenant="otherB", name="B-rule",
            event_types=["LogonFailed"], threshold=5, window_minutes=5,
            group_by="src_ip", action="store", enabled=True,
        ))
        db.add(AlertRuleDB(
            tenant="*", name="global-rule",
            event_types=["LogonFailed"], threshold=5, window_minutes=5,
            group_by="src_ip", action="store", enabled=True,
        ))
        await db.commit()

    response = await client.get(
        "/api/v1/alerts",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert response.status_code == 200
    names = {r["name"] for r in response.json()["rules"]}
    assert "A-rule" in names
    assert "global-rule" in names
    assert "B-rule" not in names, f"Viewer must not see otherB rule, got: {names}"


async def test_alert_engine_does_not_cross_trigger(client, admin_token):
    """Critical #2 — a tenant-scoped rule must not fire on another tenant's logs.

    Strengthened (N1): the previous version only asserted that the demoA-scoped
    rule did not fire on otherB logs. That passed even if a regression merged
    alerts across tenants under the seeded wildcard (tenant='*') rule, because
    the test never checked the *total* triggered-alert count for otherB.

    Now we explicitly assert: zero triggered alerts after running the engine
    on three otherB LogonFailed rows, AND a triggered alert appears for
    demoA. That pins tenant isolation end-to-end.
    """
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import func, select
    from backend.storage.database import (
        async_session, AlertRuleDB, LogEntry, TriggeredAlertDB,
    )

    # Use a fresh src_ip so we don't collide with any prior test that left a
    # TriggeredAlertDB row pointing at the same group_key. Each test fixture
    # wipes the table, but a paranoid unique IP keeps this test independent.
    isolated_ip = "203.0.113.42"

    # Create a tenant-scoped rule for tenant="demoA".
    async with async_session() as db:
        scoped_rule = AlertRuleDB(
            tenant="demoA", name="Scoped-only-A",
            event_types=["LogonFailed"], threshold=3, window_minutes=5,
            group_by="src_ip", action="store", enabled=True,
        )
        db.add(scoped_rule)
        await db.commit()
        await db.refresh(scoped_rule)
        rule_id = scoped_rule.id

        # Ingest 3 failed-login logs under tenant="otherB" — should NOT trigger
        # any alert, scoped or wildcard.
        now = datetime.now(timezone.utc)
        otherb_logs = []
        for i in range(3):
            entry = LogEntry(
                tenant="otherB",
                source="ad",
                event_type="LogonFailed",
                severity=7,
                src_ip=isolated_ip,
                timestamp=now - timedelta(seconds=i),
                raw={},
            )
            db.add(entry)
            otherb_logs.append(entry)
        await db.commit()
        for entry in otherb_logs:
            await db.refresh(entry)

        # Drive the engine for each otherB log.
        from backend.services.alert_engine import AlertEngine
        engine = AlertEngine(db)
        for entry in otherb_logs:
            triggered = await engine.check_brute_force(entry)
            assert triggered is None, (
                f"Scoped rule for demoA must not fire on otherB logs, got: {triggered}"
            )

        # Stronger (N1): assert the table is empty for this src_ip / tenant
        # pair. If a regression merged alerts across tenants (e.g. dropped the
        # tenant prefix from group_key), this catches it.
        rows = (await db.execute(
            select(func.count(TriggeredAlertDB.id)).where(
                TriggeredAlertDB.src_ip == isolated_ip,
                TriggeredAlertDB.tenant == "otherB",
            )
        )).scalar_one()
        assert rows == 0, (
            f"otherB must produce zero triggered alerts, got {rows} rows"
        )

        # Now ingest 3 failed-login logs under tenant="demoA" — SHOULD trigger
        # the scoped rule (and only the scoped rule).
        demoa_logs = []
        for i in range(3):
            entry = LogEntry(
                tenant="demoA",
                source="ad",
                event_type="LogonFailed",
                severity=7,
                src_ip=isolated_ip,
                timestamp=now - timedelta(seconds=i),
                raw={},
            )
            db.add(entry)
            demoa_logs.append(entry)
        await db.commit()
        for entry in demoa_logs:
            await db.refresh(entry)

        last_triggered = None
        for entry in demoa_logs:
            last_triggered = await engine.check_brute_force(entry)
        assert last_triggered is not None, (
            "Rule scoped to demoA must trigger on demoA logs after threshold"
        )
        assert last_triggered.rule_id == rule_id
        # And it must be tenant-scoped to demoA — a regression that dropped the
        # tenant filter would set tenant="otherB" via _make_group_key.
        assert last_triggered.tenant == "demoA", (
            f"triggered alert must be tenant='demoA', got: {last_triggered.tenant}"
        )

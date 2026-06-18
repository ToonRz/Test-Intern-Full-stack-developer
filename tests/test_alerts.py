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

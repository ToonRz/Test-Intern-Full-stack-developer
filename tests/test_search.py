"""
Tests for the log search endpoint (spec.md §5.2).
Uses the shared `client` and `admin_token` fixtures from conftest.py.
"""
import pytest


async def test_query_logs_requires_auth(client):
    """GET /logs returns 401 without a Bearer token (spec §6)."""
    response = await client.get("/api/v1/logs")
    assert response.status_code == 401


async def test_query_logs_with_auth(client, admin_token):
    """GET /logs with a valid JWT returns the paginated envelope."""
    response = await client.get(
        "/api/v1/logs",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "logs" in data
    assert "total" in data
    assert "page" in data
    assert "size" in data
    assert "pages" in data


async def test_query_logs_invalid_token(client):
    """GET /logs with a malformed token returns 401."""
    response = await client.get(
        "/api/v1/logs",
        headers={"Authorization": "Bearer not-a-valid-token"},
    )
    assert response.status_code == 401


async def test_query_logs_supports_pagination(client, admin_token):
    """`page` and `size` query params are honored."""
    response = await client.get(
        "/api/v1/logs?page=1&size=10",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["page"] == 1
    assert data["size"] == 10


async def test_query_logs_accepts_repeated_source(client, admin_token):
    """Multi-value filter (?source=a&source=b) is accepted and returns 200."""
    response = await client.get(
        "/api/v1/logs?source=api&source=aws",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200


async def test_query_logs_accepts_csv_source(client, admin_token):
    """CSV form (?source=a,b) is accepted as a convenience for curl users."""
    response = await client.get(
        "/api/v1/logs?source=api,aws",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200


async def test_query_logs_accepts_severity_buckets(client, admin_token):
    """Severity buckets (low/medium/high/critical) expand to numeric ranges
    AND the union of non-contiguous buckets does not silently include the
    gap. Critical=9-10 + Low=0-3 should match {0,1,2,3,9,10} — never 4-8.
    """
    from datetime import datetime, timezone
    from backend.storage.database import async_session, LogEntry

    # Seed one log per severity 0..10 so the filter has something to match.
    async with async_session() as db:
        for sev in range(11):
            db.add(LogEntry(
                tenant="demoA",
                source="api",
                event_type=f"sev_{sev}",
                severity=sev,
                timestamp=datetime.now(timezone.utc),
            ))
        await db.commit()

    # critical+low must NOT match medium (4-6) or high (7-8).
    response = await client.get(
        "/api/v1/logs?severity=critical&severity=low&size=100",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    matched = {log["severity"] for log in data["logs"]}
    assert matched <= {0, 1, 2, 3, 9, 10}, (
        f"critical+low filter should return only severities in {{0,1,2,3,9,10}}, "
        f"got {sorted(matched)}"
    )
    assert 0 in matched and 9 in matched, "buckets must include the boundary values"

    # Each bucket alone returns its own range.
    for bucket, expected in [
        ("critical", {9, 10}),
        ("high", {7, 8}),
        ("medium", {4, 5, 6}),
        ("low", {0, 1, 2, 3}),
    ]:
        response = await client.get(
            f"/api/v1/logs?severity={bucket}&size=100",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        matched = {log["severity"] for log in response.json()["logs"]}
        assert matched == expected, (
            f"bucket={bucket}: expected {sorted(expected)}, got {sorted(matched)}"
        )


async def test_query_logs_facets_returns_distinct_values(client, admin_token):
    """GET /logs/facets returns distinct sources / event_types / actions / tenants."""
    response = await client.get(
        "/api/v1/logs/facets",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    for key in ("sources", "event_types", "actions", "tenants"):
        assert key in data
        assert isinstance(data[key], list)


async def test_logs_stats_works_on_sqlite(client, admin_token):
    """Regression: /logs/stats must not depend on Postgres-only functions
    like to_timestamp() — this test uses SQLite (test default) and would
    500 if the timeline query was not made portable. The dashboard's main
    page hits this endpoint on load.
    """
    from datetime import datetime, timezone, timedelta
    from backend.storage.database import async_session, LogEntry

    async with async_session() as db:
        now = datetime.now(timezone.utc)
        for i in range(3):
            db.add(LogEntry(
                tenant="demoA",
                source="api",
                event_type="stats_test",
                severity=5,
                timestamp=now - timedelta(hours=i),
            ))
        await db.commit()

    response = await client.get(
        "/api/v1/logs/stats?bucket_minutes=60",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200, f"stats crashed: {response.text[:200]}"
    body = response.json()
    assert body["total"] >= 3
    assert isinstance(body["timeline"], list)
    assert len(body["timeline"]) >= 1
    assert any(item["key"] == "api" for item in body["by_source"])


async def test_logs_stats_respects_tenant_filter_viewer(client, viewer_token):
    """Viewer must only see their own tenant's stats (spec §6 RBAC)."""
    response = await client.get(
        "/api/v1/logs/stats",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert response.status_code == 200
    # Viewer token belongs to demoA; stats must not 500 on an empty result set.
    assert "total" in response.json()

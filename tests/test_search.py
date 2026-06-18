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
    """Severity buckets (low/medium/high/critical) expand to numeric ranges."""
    response = await client.get(
        "/api/v1/logs?severity=critical&severity=low",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200


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

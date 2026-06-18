"""
Tests for the ingest endpoints (spec.md §5.1).
"""
import pytest


async def test_ingest_single_log(client):
    """POST /ingest with a single JSON object succeeds and returns 1 ingested."""
    log = {
        "tenant": "test",
        "source": "api",
        "event_type": "test_event",
        "user": "testuser",
        "ip": "192.0.2.1",
    }
    response = await client.post("/api/v1/ingest", json=log)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["ingested"] == 1


async def test_ingest_batch_array(client):
    """POST /ingest accepts a top-level JSON array of logs."""
    logs = [
        {"tenant": "test", "source": "api", "event_type": "event1"},
        {"tenant": "test", "source": "api", "event_type": "event2"},
    ]
    response = await client.post("/api/v1/ingest", json=logs)
    assert response.status_code == 200
    data = response.json()
    assert data["ingested"] == 2


async def test_ingest_with_src_ip(client):
    """POST /ingest with a src_ip succeeds; enrichment is best-effort and async."""
    log = {
        "tenant": "test",
        "source": "api",
        "event_type": "test",
        "ip": "8.8.8.8",
    }
    response = await client.post("/api/v1/ingest", json=log)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


async def test_ingest_batch_endpoint(client):
    """POST /ingest/batch per spec §5.1 — AWS/M365/AD style multi-file upload."""
    batch = {
        "source": "aws",
        "tenant": "test",
        "files": [
            {
                "logs": [
                    {"event_type": "CreateUser", "user": "alice"},
                    {"event_type": "DeleteUser", "user": "bob"},
                ]
            }
        ],
    }
    response = await client.post("/api/v1/ingest/batch", json=batch)
    assert response.status_code == 200
    data = response.json()
    assert data["ingested"] == 2

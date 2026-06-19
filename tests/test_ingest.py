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


async def test_redis_failure_continues_batch(client, monkeypatch):
    """Critical #1 — when enrichment fails for log #1, log #2+ must still ingest.

    Before the fix, log #1's failed transaction poisoned the shared session,
    so every subsequent log in the batch hit PendingRollbackError on commit.
    """
    from backend.routers import ingest as ingest_module

    call_count = {"n": 0}

    async def boom(src_ip):
        call_count["n"] += 1
        raise ConnectionError("Redis is down (simulated)")

    monkeypatch.setattr(ingest_module.EnrichmentService, "enrich", staticmethod(boom))

    logs = [
        {"tenant": "test", "source": "api", "event_type": f"e{i}", "ip": "8.8.8.8"}
        for i in range(5)
    ]
    response = await client.post("/api/v1/ingest", json=logs)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["ingested"] == 5, f"All 5 logs should ingest despite Redis failure: {data}"
    assert call_count["n"] == 5


async def test_redis_cache_resets_after_failure(client, monkeypatch):
    """After enrichment failure, RedisCache singleton is reset so next call retries cleanly."""
    from backend.routers import ingest as ingest_module
    from backend.services.enrichment import RedisCache

    RedisCache._instance = "broken-stub"

    async def boom(src_ip):
        raise ConnectionError("Redis is down (simulated)")

    monkeypatch.setattr(ingest_module.EnrichmentService, "enrich", staticmethod(boom))

    response = await client.post(
        "/api/v1/ingest",
        json=[{"tenant": "test", "source": "api", "event_type": "e", "ip": "8.8.8.8"}],
    )
    assert response.status_code == 200
    assert RedisCache._instance is None, "Broken cache instance must be reset on failure"

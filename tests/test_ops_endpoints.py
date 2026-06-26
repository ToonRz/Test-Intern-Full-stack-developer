"""
N5: tests for the ops endpoints (`/health`, `/metrics`, `/`).

Both endpoints are part of the contract:

* `/health` is the docker-compose healthcheck target (docker-compose.yml:72).
  If it 500s, the frontend never starts. The endpoint has had bugs before —
  previous I-C6 incident was a misconfigured selector on the deploy side
  rather than the backend, but a `/health` regression on the backend would
  silently break every appliance deploy.

* `/metrics` is scraped by Prometheus. nginx allowlists `/metrics` by IP
  (nginx.conf), but the backend only started defining the route after HIGH
  #7 was fixed — without this test, a future refactor that accidentally
  drops the route would re-introduce the 404.

These tests exercise the endpoints over ASGI transport so they run in the
existing pytest matrix without needing the real socket stack.
"""
import pytest


async def test_root_returns_service_metadata(client):
    """GET / returns the service banner used by the README 'Access' table."""
    response = await client.get("/")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "running"
    assert "service" in body


async def test_health_returns_healthy(client):
    """GET /health must always return 200 with status='healthy'.

    The docker-compose healthcheck (docker-compose.yml:72) uses
    `curl -fsS http://localhost:8000/health` — any non-2xx response fails
    the healthcheck and Docker marks the container unhealthy. We pin the
    200 contract here so a future bug that introduces a 500 (e.g. a
    startup-time exception that bubbles into the route) is caught in CI
    rather than at deploy time.
    """
    response = await client.get("/health")
    assert response.status_code == 200, (
        f"/health must return 200 for the docker-compose healthcheck; "
        f"got {response.status_code} {response.text}"
    )
    assert response.json() == {"status": "healthy"}


async def test_health_requires_no_auth(client):
    """GET /health must not require authentication.

    The docker-compose healthcheck runs unauthenticated curl from inside
    the backend container; if /health ever requires a Bearer token, every
    container will be marked unhealthy and the stack will not come up.
    """
    response = await client.get("/health")  # no Authorization header
    assert response.status_code == 200


async def test_metrics_returns_prometheus_text_format(client):
    """GET /metrics returns Prometheus exposition format (text/plain).

    The exporter hand-formats the body without prometheus_client so it
    works in air-gapped test envs (comment at backend/main.py:204). Pin
    the content-type so a future refactor that switches to a different
    serializer (e.g. JSON) is flagged — Prometheus needs
    `text/plain; version=0.0.4`.
    """
    response = await client.get("/metrics")
    assert response.status_code == 200
    # Prometheus exposition format is text/plain with version param.
    assert response.headers["content-type"].startswith("text/plain"), (
        f"/metrics must return Prometheus text format, got: "
        f"{response.headers.get('content-type')!r}"
    )


async def test_metrics_emits_expected_counter_names(client):
    """The /metrics body must include the four counters the README promises.

    README advertises "Prometheus-format metrics endpoint" — the four
    counters are emitted by hand in backend/main.py:223-236. If a future
    refactor renames any of them, dashboards break silently. Pin the names.
    """
    response = await client.get("/metrics")
    assert response.status_code == 200
    body = response.text
    for metric in (
        "log_management_logs_total",
        "log_management_triggered_alerts_total",
        "log_management_alert_rules_total",
        "log_management_alerts_acknowledged_total",
    ):
        assert metric in body, (
            f"Missing metric '{metric}' in /metrics body. Body:\n{body}"
        )


async def test_metrics_reflects_ingested_logs(client, admin_token):
    """After ingesting a log, log_management_logs_total must increment.

    This is the closest thing to a true 'metrics reflect reality' test.
    Without it, a regression in the SQL behind `/metrics` (e.g. wrong
    table or column) would report 0 logs even when the DB has rows.
    """
    # Snapshot before.
    before_body = (await client.get("/metrics")).text
    # Ingest one log.
    await client.post(
        "/api/v1/ingest",
        json={"tenant": "demoA", "source": "api", "event_type": "ops_test"},
    )
    # Snapshot after.
    after_body = (await client.get("/metrics")).text

    def _value(body: str, metric: str) -> int:
        for line in body.splitlines():
            if line.startswith(metric + " "):
                return int(line.split()[-1])
        raise AssertionError(f"metric '{metric}' missing from body:\n{body}")

    assert _value(after_body, "log_management_logs_total") >= \
           _value(before_body, "log_management_logs_total") + 1, (
        f"Ingesting one log must increment log_management_logs_total. "
        f"before={before_body!r}, after={after_body!r}"
    )


async def test_metrics_does_not_500_when_db_is_empty(client):
    """Regression: a fresh DB must produce 0 counters, not a 500.

    The conftest's `_clean_tables` wipes tables between tests. /metrics
    uses `coalesce(..., 0)` to handle empty results; if a future refactor
    drops that, an empty DB throws and Prometheus stops scraping.
    """
    # _clean_tables ran in the autouse fixture, so we're starting from
    # an empty state. /metrics must still return 200.
    response = await client.get("/metrics")
    assert response.status_code == 200, (
        f"/metrics must not 500 on an empty DB; got {response.status_code} {response.text}"
    )
from datetime import datetime, timezone


def normalize_aws(data: dict, tenant: str = None) -> dict:
    """Normalize AWS CloudTrail log per spec.md 4.5."""
    # `cloud` may arrive as a string, list, or other non-dict from malformed
    # upstream payloads — coerce to dict so `.get()` can't crash the ingest.
    cloud_data = data.get("cloud")
    if not isinstance(cloud_data, dict):
        cloud_data = {}
    tags = ["aws", "cloud"]

    return {
        "tenant": tenant or data.get("tenant", "default"),
        "source": "aws",
        "vendor": "aws",
        "product": "cloudtrail",
        "event_type": data.get("event_type", "unknown"),
        "user": data.get("user"),
        "cloud": {
            "service": cloud_data.get("service"),
            "account_id": cloud_data.get("account_id"),
            "region": cloud_data.get("region"),
        },
        "@timestamp": data.get("@timestamp") or datetime.now(timezone.utc).isoformat(),
        "raw": data.get("raw") or data,
        "_tags": tags,
    }

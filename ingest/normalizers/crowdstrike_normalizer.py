from datetime import datetime, timezone


def normalize_crowdstrike(data: dict, tenant: str = None) -> dict:
    """Normalize CrowdStrike log per spec.md 4.4."""
    tags = ["crowdstrike", "edr"]
    event_type = data.get("event_type", "unknown")
    if event_type and "malware" in event_type.lower():
        tags.append("malware")

    return {
        "tenant": tenant or data.get("tenant", "default"),
        "source": "crowdstrike",
        "vendor": "crowdstrike",
        "product": "falcon",
        "event_type": event_type,
        "severity": data.get("severity", 8),
        "action": data.get("action"),
        "host": data.get("host"),
        "process": data.get("process"),
        "user": data.get("user"),
        "src_ip": data.get("ip"),
        "sha256": data.get("sha256"),
        "@timestamp": data.get("@timestamp") or datetime.now(timezone.utc).isoformat(),
        "raw": data,
        "_tags": tags,
    }

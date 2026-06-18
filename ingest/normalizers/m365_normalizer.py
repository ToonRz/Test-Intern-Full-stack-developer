from datetime import datetime, timezone


def normalize_m365(data: dict, tenant: str = None) -> dict:
    """Normalize Microsoft 365 Unified Audit log per spec.md 4.6."""
    status = data.get("status")
    event_type = data.get("event_type", "UserLoggedIn")
    action = "login" if "login" in event_type.lower() else None
    severity = 8 if status == "Fail" else 5

    tags = ["m365", "cloud", data.get("workload", "").lower()] if data.get("workload") else ["m365", "cloud"]

    return {
        "tenant": tenant or data.get("tenant", "default"),
        "source": "m365",
        "vendor": "microsoft",
        "product": "office365",
        "event_type": event_type,
        "user": data.get("user"),
        "src_ip": data.get("ip"),
        "severity": severity,
        "action": action,
        "@timestamp": data.get("@timestamp") or datetime.now(timezone.utc).isoformat(),
        "raw": data,
        "_tags": [t for t in tags if t],
    }

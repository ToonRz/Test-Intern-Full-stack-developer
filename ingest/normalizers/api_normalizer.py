from datetime import datetime


def normalize_api(data: dict, tenant: str = None) -> dict:
    """
    Normalize HTTP API log per spec.md 4.3
    """
    action = None
    if data.get("reason") or "fail" in data.get("event_type", "").lower():
        action = "login"  # login failed
    elif "login" in data.get("event_type", "").lower():
        action = "login"
    elif "logout" in data.get("event_type", "").lower():
        action = "logout"

    severity = 8 if data.get("reason") or "fail" in data.get("event_type", "").lower() else 5

    return {
        "tenant": tenant or data.get("tenant", "default"),
        "source": "api",
        "event_type": data.get("event_type", "unknown"),
        "event_subtype": data.get("reason"),
        "user": data.get("user"),
        "src_ip": data.get("ip"),
        "severity": severity,
        "action": action,
        "host": data.get("host"),
        "@timestamp": data.get("@timestamp") or datetime.utcnow().isoformat() + "Z",
        "raw": data
    }

from datetime import datetime, timezone


def normalize_m365(data: dict, tenant: str = None) -> dict:
    """Normalize Microsoft 365 Unified Audit log per spec.md 4.6.

    Spec §4.6 example uses input field `ip` and does not include `severity`.
    We honor an explicit caller-provided `severity` (matches the §4.4
    CrowdStrike pattern), otherwise derive from `status`. Input also
    accepts `src_ip` as an alias for `ip` so the field name from the
    normalized schema can be used interchangeably with the spec example.
    """
    status = data.get("status")
    event_type = data.get("event_type", "UserLoggedIn")
    action = "login" if "login" in event_type.lower() else None

    caller_severity = data.get("severity")
    if isinstance(caller_severity, int) and 0 <= caller_severity <= 10:
        severity = caller_severity
    else:
        severity = 8 if status == "Fail" else 5

    src_ip = data.get("ip") or data.get("src_ip")

    tags = ["m365", "cloud", data.get("workload", "").lower()] if data.get("workload") else ["m365", "cloud"]

    return {
        "tenant": tenant or data.get("tenant", "default"),
        "source": "m365",
        "vendor": "microsoft",
        "product": "office365",
        "event_type": event_type,
        "user": data.get("user"),
        "src_ip": src_ip,
        "severity": severity,
        "action": action,
        "@timestamp": data.get("@timestamp") or datetime.now(timezone.utc).isoformat(),
        "raw": data,
        "_tags": [t for t in tags if t],
    }

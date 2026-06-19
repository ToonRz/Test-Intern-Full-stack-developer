from datetime import datetime, timezone


def normalize_ad(data: dict, tenant: str = None) -> dict:
    """Normalize Microsoft AD / Windows Security log per spec.md 4.7.

    EventID 4625 = LogonFailed  (matched by brute-force rule, spec §8)
    EventID 4624 = LogonSuccess
    """
    event_id = data.get("event_id", 0)
    tags = ["ad", "windows"]

    if event_id == 4625:
        action, severity, event_type = "login", 8, "LogonFailed"
    elif event_id == 4624:
        action, severity, event_type = "login", 5, "LogonSuccess"
    elif event_id in (4741, 4720, 4732):
        action, severity, event_type = "create", 7, f"AccountChange_{event_id}"
    elif event_id in (4726, 4728):
        action, severity, event_type = "delete", 7, f"AccountChange_{event_id}"
    else:
        action, severity = None, 5
        event_type = data.get("event_type") or f"EventID_{event_id}"

    if event_type == "LogonFailed":
        tags.append("auth_failure")

    return {
        "tenant": tenant or data.get("tenant", "default"),
        "source": "ad",
        "vendor": "microsoft",
        "product": "active_directory",
        "event_type": event_type,
        "event_subtype": str(event_id) if event_id else None,
        "user": data.get("user"),
        # Spec §4.7 example uses input field `ip`; `src_ip` accepted as an
        # alias so callers used to the normalized schema field can use either.
        "src_ip": data.get("ip") or data.get("src_ip"),
        "host": data.get("host"),
        "severity": severity,
        "action": action,
        "@timestamp": data.get("@timestamp") or datetime.now(timezone.utc).isoformat(),
        "raw": data,
        "_tags": tags,
    }

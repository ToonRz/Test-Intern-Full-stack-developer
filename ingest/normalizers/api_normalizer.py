from datetime import datetime, timezone


def normalize_api(data: dict, tenant: str = None) -> dict:
    """
    Normalize HTTP API log per spec.md 4.3.

    Spec §4.3 example uses input field `ip` and does not include `severity`.
    We honor both: if the caller provides `severity`, use it (matches the
    §4.4 CrowdStrike pattern); otherwise derive from event_type. Input
    accepts `src_ip` as an alias for `ip` so callers used to the normalized
    schema field can use either name without the value being silently
    dropped.
    """
    action = None
    if data.get("reason") or "fail" in data.get("event_type", "").lower():
        action = "login"  # login failed
    elif "login" in data.get("event_type", "").lower():
        action = "login"
    elif "logout" in data.get("event_type", "").lower():
        action = "logout"

    # Severity: caller-provided value wins (must be int 0–10 per spec §3
    # schema). Falls back to the login-fail heuristic so the spec §4.3
    # example — which has no severity field — still produces a sensible
    # value.
    caller_severity = data.get("severity")
    if isinstance(caller_severity, int) and 0 <= caller_severity <= 10:
        severity = caller_severity
    else:
        severity = 8 if data.get("reason") or "fail" in data.get("event_type", "").lower() else 5

    # IP: spec §4.3 uses `ip`; `src_ip` is accepted as an alias so the call
    # site can use either name. `ip` wins on tie to keep spec parity.
    src_ip = data.get("ip") or data.get("src_ip")

    return {
        "tenant": tenant or data.get("tenant", "default"),
        "source": "api",
        "event_type": data.get("event_type", "unknown"),
        "event_subtype": data.get("reason"),
        "user": data.get("user"),
        "src_ip": src_ip,
        "severity": severity,
        "action": action,
        "host": data.get("host"),
        "@timestamp": data.get("@timestamp") or datetime.now(timezone.utc).isoformat(),
        "raw": data
    }

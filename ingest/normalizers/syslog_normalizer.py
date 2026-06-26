import re
from datetime import datetime, timezone, timedelta


# Critical B-C13: a syslog timestamp like "Aug 20 12:44:56" has no year. The
# previous code used `datetime.now().year` for both Aug-20 and Dec-31 lines,
# so a Dec-31 line ingested on Jan 1 would be tagged as the *next* Dec 31,
# 364 days in the future. Compare against the *current* year and roll back
# to the previous year if the candidate is more than ~3 days in the future.
def _parse_syslog_timestamp(ts_str: str, now: datetime) -> datetime:
    """Parse "Aug 20 12:44:56" into a tz-aware UTC datetime.

    Year-rollover guard: if the candidate timestamp is more than
    `_YEAR_ROLLOVER_WINDOW` ahead of `now`, assume it's last year. The window
    is asymmetric on purpose: a 3-day skew absorbs legitimate clock drift
    without false-negatives on Dec 31 → Jan 1 transitions.
    """
    _YEAR_ROLLOVER_WINDOW = timedelta(days=3)
    try:
        naive = datetime.strptime(f"{now.year} {ts_str}", "%Y %b %d %H:%M:%S")
    except ValueError:
        return now
    candidate = naive.replace(tzinfo=timezone.utc)
    if candidate > now + _YEAR_ROLLOVER_WINDOW:
        candidate = candidate.replace(year=candidate.year - 1)
    return candidate


def parse_syslog(line: str, tenant: str = "default"):
    """
    Parse syslog line per spec.md 4.1 and 4.2.
    Returns normalized dict matching schema.
    """
    now = datetime.now(timezone.utc)
    # Firewall format: <134>Aug 20 12:44:56 fw01 vendor=demo product=ngfw action=deny...
    firewall_pattern = r'<(?:\d+)>(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\s+(\S+)\s+(?:vendor=(\S+))?\s*(?:product=(\S+))?\s*(?:action=(\S+))?\s*(?:src=(\S+))?\s*(?:dst=(\S+))?\s*(?:spt=(\d+))?\s*(?:dpt=(\d+))?\s*(?:proto=(\S+))?\s*(?:msg=(\S+))?\s*(?:policy=(\S+))?'
    fw_match = re.match(firewall_pattern, line)

    if fw_match and (fw_match.group(3) or fw_match.group(4)):
        # The firewall regex is permissive (every field is optional) so it can
        # spuriously match a non-firewall line like a network-router syslog.
        # Require at least vendor or product before claiming a firewall match —
        # otherwise fall through to the network pattern below.
        timestamp_str, hostname, vendor, product, action, src_ip, dst_ip, spt, dpt, proto, msg, policy = fw_match.groups()
        timestamp = _parse_syslog_timestamp(timestamp_str, now)

        return {
            "tenant": tenant,
            "source": "firewall",
            "vendor": vendor or "unknown",
            "product": product or "unknown",
            "event_type": msg or "unknown",
            "severity": 8 if action == "deny" else 5,
            "action": action,
            "src_ip": src_ip,
            "src_port": int(spt) if spt else None,
            "dst_ip": dst_ip,
            "dst_port": int(dpt) if dpt else None,
            "protocol": proto,
            "host": hostname,
            "rule_name": policy,
            "@timestamp": timestamp.isoformat(),
            "raw": {"original": line}
        }

    # Network router format: <190>Aug 20 13:01:02 r1 if=ge-0/0/1 event=link-down...
    network_pattern = r'<(?:\d+)>(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\s+(\S+)\s+(?:if=(\S+))?\s*(?:event=(\S+))?\s*(?:mac=([0-9a-f:]+))?\s*(?:reason=(\S+))?'
    net_match = re.match(network_pattern, line)

    if net_match:
        timestamp_str, hostname, interface, event, mac, reason = net_match.groups()
        timestamp = _parse_syslog_timestamp(timestamp_str, now)

        severity = 7 if event and "down" in event.lower() else 5

        return {
            "tenant": tenant,
            "source": "network",
            "event_type": event or "unknown",
            "event_subtype": reason,
            "severity": severity,
            "host": hostname,
            "action": "alert" if severity >= 7 else None,
            "@timestamp": timestamp.isoformat(),
            "raw": {"original": line, "interface": interface, "mac": mac, "reason": reason}
        }

    return None

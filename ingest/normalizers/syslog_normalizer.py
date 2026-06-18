import re
from datetime import datetime


def parse_syslog(line: str, tenant: str = "default"):
    """
    Parse syslog line per spec.md 4.1 and 4.2.
    Returns normalized dict matching schema.
    """
    # Firewall format: <134>Aug 20 12:44:56 fw01 vendor=demo product=ngfw action=deny...
    firewall_pattern = r'<(?:\d+)>(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\s+(\S+)\s+(?:vendor=(\S+))?\s*(?:product=(\S+))?\s*(?:action=(\S+))?\s*(?:src=(\S+))?\s*(?:dst=(\S+))?\s*(?:spt=(\d+))?\s*(?:dpt=(\d+))?\s*(?:proto=(\S+))?\s*(?:msg=(\S+))?\s*(?:policy=(\S+))?'
    fw_match = re.match(firewall_pattern, line)

    if fw_match:
        timestamp_str, hostname, vendor, product, action, src_ip, dst_ip, spt, dpt, proto, msg, policy = fw_match.groups()
        try:
            timestamp = datetime.strptime(f"{datetime.now().year} {timestamp_str}", "%Y %b %d %H:%M:%S")
        except ValueError:
            timestamp = datetime.utcnow()

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
            "@timestamp": timestamp.isoformat() + "Z",
            "raw": {"original": line}
        }

    # Network router format: <190>Aug 20 13:01:02 r1 if=ge-0/0/1 event=link-down...
    network_pattern = r'<(?:\d+)>(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\s+(\S+)\s+(?:if=(\S+))?\s*(?:event=(\S+))?\s*(?:mac=([0-9a-f:]+))?\s*(?:reason=(\S+))?'
    net_match = re.match(network_pattern, line)

    if net_match:
        timestamp_str, hostname, interface, event, mac, reason = net_match.groups()
        try:
            timestamp = datetime.strptime(f"{datetime.now().year} {timestamp_str}", "%Y %b %d %H:%M:%S")
        except ValueError:
            timestamp = datetime.utcnow()

        severity = 7 if event and "down" in event.lower() else 5

        return {
            "tenant": tenant,
            "source": "network",
            "event_type": event or "unknown",
            "event_subtype": reason,
            "severity": severity,
            "host": hostname,
            "action": "alert" if severity >= 7 else None,
            "@timestamp": timestamp.isoformat() + "Z",
            "raw": {"original": line, "interface": interface, "mac": mac, "reason": reason}
        }

    return None

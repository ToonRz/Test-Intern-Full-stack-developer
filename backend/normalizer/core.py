from datetime import datetime
from typing import Optional, List, Any
import re
from backend.models.schemas import NormalizedLog, Cloud


def parse_syslog_firewall(line: str, tenant: str = "default") -> Optional[NormalizedLog]:
    """
    Parse Firewall Syslog per spec.md 4.1:
    <134>Aug 20 12:44:56 fw01 vendor=demo product=ngfw action=deny src=10.0.1.10 dst=8.8.8.8 spt=5353 dpt=53 proto=udp msg=DNS blocked policy=Block-DNS
    """
    pattern = r'<(?:\d+)>(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\s+(\S+)\s+(?:vendor=(\S+))?\s*(?:product=(\S+))?\s*(?:action=(\S+))?\s*(?:src=(\S+))?\s*(?:dst=(\S+))?\s*(?:spt=(\d+))?\s*(?:dpt=(\d+))?\s*(?:proto=(\S+))?\s*(?:msg=(\S+))?\s*(?:policy=(\S+))?'
    match = re.match(pattern, line)
    if not match:
        return None

    timestamp_str, hostname, vendor, product, action, src_ip, dst_ip, spt, dpt, proto, msg, policy = match.groups()

    # Must have vendor OR product to be a valid firewall log
    if not vendor and not product:
        return None

    try:
        ts = datetime.strptime(f"{datetime.now().year} {timestamp_str}", "%Y %b %d %H:%M:%S")
        if ts > datetime.utcnow():
            ts = ts.replace(year=ts.year - 1)
    except ValueError:
        ts = datetime.utcnow()

    return NormalizedLog(
        timestamp=ts.isoformat() + "Z",
        tenant=tenant,
        source="firewall",
        vendor=vendor or "unknown",
        product=product or "unknown",
        event_type=msg or "unknown",
        severity=8 if action == "deny" else 5,
        action=action,
        src_ip=src_ip,
        src_port=int(spt) if spt else None,
        dst_ip=dst_ip,
        dst_port=int(dpt) if dpt else None,
        protocol=proto,
        host=hostname,
        rule_name=policy,
        raw={"original": line}
    )


def parse_syslog_network(line: str, tenant: str = "default") -> Optional[NormalizedLog]:
    """
    Parse Network Router Syslog per spec.md 4.2:
    <190>Aug 20 13:01:02 r1 if=ge-0/0/1 event=link-down mac=aa:bb:cc:dd:ee:ff reason=carrier-loss
    """
    pattern = r'<(?:\d+)>(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\s+(\S+)\s+(?:if=(\S+))?\s*(?:event=(\S+))?\s*(?:mac=([0-9a-f:]+))?\s*(?:reason=(\S+))?'
    match = re.match(pattern, line)
    if not match:
        return None

    timestamp_str, hostname, interface, event, mac, reason = match.groups()

    try:
        ts = datetime.strptime(f"{datetime.now().year} {timestamp_str}", "%Y %b %d %H:%M:%S")
        if ts > datetime.utcnow():
            ts = ts.replace(year=ts.year - 1)
    except ValueError:
        ts = datetime.utcnow()

    severity = 7 if event and "down" in event.lower() else 5

    return NormalizedLog(
        timestamp=ts.isoformat() + "Z",
        tenant=tenant,
        source="network",
        event_type=event or "unknown",
        event_subtype=reason,
        severity=severity,
        host=hostname,
        action="alert" if severity >= 7 else None,
        raw={"original": line, "interface": interface, "mac": mac, "reason": reason}
    )


def normalize_api_log(data: dict, tenant: Optional[str] = None) -> NormalizedLog:
    """Normalize HTTP API log per spec.md 4.3"""
    ts = data.get("@timestamp") or data.get("timestamp") or datetime.utcnow().isoformat() + "Z"

    action = None
    if data.get("reason") or "fail" in data.get("event_type", "").lower():
        action = "login"  # login failed
    elif "login" in data.get("event_type", "").lower():
        action = "login"
    elif "logout" in data.get("event_type", "").lower():
        action = "logout"

    severity = 8 if data.get("reason") or "fail" in data.get("event_type", "").lower() else 5

    return NormalizedLog(
        timestamp=ts,
        tenant=tenant or data.get("tenant", "default"),
        source="api",
        event_type=data.get("event_type", "unknown"),
        event_subtype=data.get("reason"),
        user=data.get("user"),
        src_ip=data.get("ip"),
        severity=severity,
        action=action,
        host=data.get("host"),
        raw=data
    )


def normalize_crowdstrike(data: dict, tenant: Optional[str] = None) -> NormalizedLog:
    """Normalize CrowdStrike log per spec.md 4.4"""
    ts = data.get("@timestamp") or data.get("timestamp") or datetime.utcnow().isoformat() + "Z"
    return NormalizedLog(
        timestamp=ts,
        tenant=tenant or data.get("tenant", "default"),
        source="crowdstrike",
        event_type=data.get("event_type", "malware_detected"),
        severity=data.get("severity", 8),
        action=data.get("action"),
        host=data.get("host"),
        process=data.get("process"),
        user=data.get("user"),
        src_ip=data.get("ip"),
        raw=data
    )


def normalize_aws(data: dict, tenant: Optional[str] = None) -> NormalizedLog:
    """Normalize AWS CloudTrail log per spec.md 4.5"""
    ts = data.get("@timestamp") or data.get("timestamp") or datetime.utcnow().isoformat() + "Z"
    cloud_data = data.get("cloud", {})
    return NormalizedLog(
        timestamp=ts,
        tenant=tenant or data.get("tenant", "default"),
        source="aws",
        event_type=data.get("event_type", "unknown"),
        user=data.get("user"),
        cloud=Cloud(
            service=cloud_data.get("service"),
            account_id=cloud_data.get("account_id"),
            region=cloud_data.get("region")
        ),
        raw=data.get("raw")
    )


def normalize_m365(data: dict, tenant: Optional[str] = None) -> NormalizedLog:
    """Normalize Microsoft 365 log per spec.md 4.6"""
    ts = data.get("@timestamp") or data.get("timestamp") or datetime.utcnow().isoformat() + "Z"
    return NormalizedLog(
        timestamp=ts,
        tenant=tenant or data.get("tenant", "default"),
        source="m365",
        event_type=data.get("event_type", "UserLoggedIn"),
        user=data.get("user"),
        src_ip=data.get("ip"),
        severity=8 if data.get("status") == "Fail" else 5,
        action="login" if "login" in data.get("event_type", "").lower() else None,
        raw=data
    )


def normalize_ad(data: dict, tenant: Optional[str] = None) -> NormalizedLog:
    """Normalize Microsoft AD/Windows Security log per spec.md 4.7"""
    ts = data.get("@timestamp") or data.get("timestamp") or datetime.utcnow().isoformat() + "Z"
    event_id = data.get("event_id", 0)

    if event_id == 4625:
        action = "login"
        severity = 8
        event_type = "LogonFailed"
    elif event_id == 4624:
        action = "login"
        severity = 5
        event_type = "LogonSuccess"
    else:
        action = None
        severity = 5
        event_type = data.get("event_type", f"EventID_{event_id}")

    return NormalizedLog(
        timestamp=ts,
        tenant=tenant or data.get("tenant", "default"),
        source="ad",
        event_type=event_type,
        user=data.get("user"),
        src_ip=data.get("ip"),
        host=data.get("host"),
        severity=severity,
        action=action,
        raw=data
    )


def normalize_log(data: dict, source: str = "api", tenant: Optional[str] = None) -> NormalizedLog:
    """Route to appropriate normalizer based on source"""
    raw = data.get("raw")

    if source == "firewall" and isinstance(raw, str):
        result = parse_syslog_firewall(raw, tenant or data.get("tenant"))
        if result:
            return result

    if source == "network" and isinstance(raw, str):
        result = parse_syslog_network(raw, tenant or data.get("tenant"))
        if result:
            return result

    if source == "crowdstrike":
        return normalize_crowdstrike(data, tenant)
    if source == "aws":
        return normalize_aws(data, tenant)
    if source == "m365":
        return normalize_m365(data, tenant)
    if source == "ad":
        return normalize_ad(data, tenant)

    return normalize_api_log(data, tenant)

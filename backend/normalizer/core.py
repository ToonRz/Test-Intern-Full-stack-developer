from typing import Optional
from backend.models.schemas import NormalizedLog
from ingest import normalizers as _ingest


def _to_model(d: Optional[dict]) -> Optional[NormalizedLog]:
    if d is None:
        return None
    return NormalizedLog.model_validate(d)


def parse_syslog_firewall(line: str, tenant: str = "default") -> Optional[NormalizedLog]:
    """Parse Firewall Syslog per spec.md 4.1."""
    d = _ingest.parse_syslog(line, tenant)
    if d and d.get("source") == "firewall":
        return _to_model(d)
    return None


def parse_syslog_network(line: str, tenant: str = "default") -> Optional[NormalizedLog]:
    """Parse Network Router Syslog per spec.md 4.2."""
    d = _ingest.parse_syslog(line, tenant)
    if d and d.get("source") == "network":
        return _to_model(d)
    return None


def normalize_api_log(data: dict, tenant: Optional[str] = None) -> NormalizedLog:
    """Normalize HTTP API log per spec.md 4.3."""
    return _to_model(_ingest.normalize_api(data, tenant))


def normalize_crowdstrike(data: dict, tenant: Optional[str] = None) -> NormalizedLog:
    """Normalize CrowdStrike log per spec.md 4.4."""
    return _to_model(_ingest.normalize_crowdstrike(data, tenant))


def normalize_aws(data: dict, tenant: Optional[str] = None) -> NormalizedLog:
    """Normalize AWS CloudTrail log per spec.md 4.5."""
    return _to_model(_ingest.normalize_aws(data, tenant))


def normalize_m365(data: dict, tenant: Optional[str] = None) -> NormalizedLog:
    """Normalize M365 log per spec.md 4.6."""
    return _to_model(_ingest.normalize_m365(data, tenant))


def normalize_ad(data: dict, tenant: Optional[str] = None) -> NormalizedLog:
    """Normalize AD log per spec.md 4.7 (covers event IDs 4624/4625 plus
    account-change events 4720/4726/4728/4732/4741)."""
    return _to_model(_ingest.normalize_ad(data, tenant))


def normalize_log(data: dict, source: str = "api", tenant: Optional[str] = None) -> NormalizedLog:
    """Route to the appropriate normalizer based on source.

    For syslog sources, the raw line is expected under data['raw'].
    """
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

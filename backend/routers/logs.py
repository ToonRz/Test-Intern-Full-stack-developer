from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func, cast, Text, distinct
from typing import Optional, List
from datetime import datetime, timedelta, timezone
from backend.storage.database import get_db, LogEntry, UserDB
from backend.auth.jwt import get_current_user

router = APIRouter(prefix="/logs", tags=["Logs"])


def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def _split_csv(value: Optional[str]) -> List[str]:
    """Allow callers to pass either repeated params (?source=a&source=b) or a
    single comma-separated value (?source=a,b). The repeated-param form is
    what Axios sends for arrays; the CSV form is a convenience for curl."""
    if not value:
        return []
    return [v.strip() for v in value.split(",") if v.strip()]


def _normalize_list(values: Optional[List[str]]) -> List[str]:
    """Drop blanks/dupes from a list param."""
    if not values:
        return []
    seen = []
    for v in values:
        v = (v or "").strip()
        if v and v not in seen:
            seen.append(v)
    return seen


def _apply_common_filters(query, current_user: UserDB, tenants, sources, event_types,
                          actions, geo_country, severities, start, end):
    """Apply RBAC + common filters used by /logs and /logs/stats.

    `tenants`, `sources`, `event_types`, `actions`, `severities` are lists so
    the UI can pass multiple checkbox values and the API does an IN match.
    `severities` is a list of bucket names (low/medium/high/critical) that we
    expand to a numeric range OR'd together.
    """
    # Tenant: Viewer forced to their tenant; Admin can pass a list (or "*"/empty
    # for all).
    if current_user.role == "Viewer":
        query = query.where(LogEntry.tenant == current_user.tenant)
    else:
        # Exclude the wildcard sentinel so admins can still mean "all".
        real = [t for t in tenants if t and t != "*"]
        if real:
            query = query.where(LogEntry.tenant.in_(real))

    if sources:
        query = query.where(LogEntry.source.in_(sources))
    if event_types:
        query = query.where(LogEntry.event_type.in_(event_types))
    if actions:
        query = query.where(LogEntry.action.in_(actions))
    if geo_country:
        query = query.where(LogEntry.geo_country == geo_country)

    # Severity: a list of bucket names → expand each to [min, max] and OR.
    if severities:
        ranges = []
        for b in severities:
            if b == "critical":
                ranges.append((9, 10))
            elif b == "high":
                ranges.append((7, 8))
            elif b == "medium":
                ranges.append((4, 6))
            elif b == "low":
                ranges.append((0, 3))
        if ranges:
            lo = min(r[0] for r in ranges)
            hi = max(r[1] for r in ranges)
            # Use IN over a generated list so non-contiguous buckets (e.g.
            # critical+low) don't accidentally include medium/high.
            allowed = set()
            for lo_r, hi_r in ranges:
                for v in range(lo_r, hi_r + 1):
                    allowed.add(v)
            if allowed:
                query = query.where(LogEntry.severity.in_(sorted(allowed)))

    start_dt = _parse_dt(start)
    if start_dt:
        query = query.where(LogEntry.timestamp >= start_dt)
    end_dt = _parse_dt(end)
    if end_dt:
        query = query.where(LogEntry.timestamp <= end_dt)
    return query


def _serialize_log(log: LogEntry) -> dict:
    return {
        "id": log.id,
        "@timestamp": log.timestamp.isoformat() if log.timestamp else None,
        "tenant": log.tenant,
        "source": log.source,
        "vendor": log.vendor,
        "product": log.product,
        "event_type": log.event_type,
        "event_subtype": log.event_subtype,
        "severity": log.severity,
        "action": log.action,
        "src_ip": log.src_ip,
        "src_port": log.src_port,
        "dst_ip": log.dst_ip,
        "dst_port": log.dst_port,
        "protocol": log.protocol,
        "user": log.user,
        "host": log.host,
        "process": log.process,
        "url": log.url,
        "http_method": log.http_method,
        "status_code": log.status_code,
        "rule_name": log.rule_name,
        "rule_id": log.rule_id,
        "geo_country": log.geo_country,
        "geo_city": log.geo_city,
        "geo_lat": log.geo_lat,
        "geo_lon": log.geo_lon,
        "rdns_hostname": log.rdns_hostname,
        "cloud": log.cloud,
        "raw": log.raw,
        "_tags": log._tags,
    }


@router.get("/facets")
async def get_log_facets(
    request: Request,
    tenant: Optional[List[str]] = Query(None, description="Restrict facets to these tenants (Admin only)"),
    current_user: UserDB = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Distinct values to populate checkbox filters in the UI.

    For each column we cap at a reasonable size so a runaway tenant doesn't
    return tens of thousands of event types. The UI uses these as suggestions,
    not a closed list — the user can still type freeform values.
    """
    base = select(LogEntry)
    if current_user.role == "Viewer":
        base = base.where(LogEntry.tenant == current_user.tenant)
    elif tenant:
        real = [t for t in tenant if t and t != "*"]
        if real:
            base = base.where(LogEntry.tenant.in_(real))

    async def distinct_values(column, cap=200):
        stmt = select(distinct(column)).where(column.isnot(None))
        if base.whereclause is not None:
            stmt = stmt.where(base.whereclause)
        stmt = stmt.limit(cap)
        rows = await db.execute(stmt)
        return sorted([r[0] for r in rows.all() if r[0] is not None], key=str)

    return {
        "sources": await distinct_values(LogEntry.source),
        "event_types": await distinct_values(LogEntry.event_type),
        "actions": await distinct_values(LogEntry.action),
        "tenants": await distinct_values(LogEntry.tenant),
    }


@router.get("/stats")
async def get_dashboard_stats(
    request: Request,
    tenant: Optional[List[str]] = Query(None),
    source: Optional[List[str]] = Query(None),
    event_type: Optional[List[str]] = Query(None),
    action: Optional[List[str]] = Query(None),
    geo_country: Optional[str] = Query(None),
    severity: Optional[List[str]] = Query(None, description="Severity buckets: low/medium/high/critical"),
    start: Optional[str] = Query(None, description="ISO8601 start time (default: 24h ago)"),
    end: Optional[str] = Query(None, description="ISO8601 end time (default: now)"),
    top_n: int = Query(10, ge=1, le=50),
    bucket_minutes: int = Query(60, ge=5, le=1440),
    current_user: UserDB = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Aggregations for the Dashboard page (spec §7): total, timeline,
    top N src_ip / user / event_type, by source, by severity.
    """
    tenants = _normalize_list(tenant)
    sources = _normalize_list(source)
    event_types = _normalize_list(event_type)
    actions = _normalize_list(action)
    severities = _normalize_list(severity)

    end_dt = _parse_dt(end) or datetime.now(timezone.utc)
    start_dt = _parse_dt(start) or (end_dt - timedelta(hours=24))
    base = select(LogEntry)
    base = _apply_common_filters(base, current_user, tenants, sources, event_types,
                                 actions, geo_country, severities,
                                 start_dt.isoformat(), end_dt.isoformat())

    # Total
    total = (await db.execute(
        select(func.count(LogEntry.id)).where(base.whereclause)
    )).scalar_one()

    # Timeline — bucketed count via date_trunc on Postgres.
    bucket_seconds = bucket_minutes * 60
    timeline_q = (
        select(
            func.to_timestamp(func.floor(func.extract("epoch", LogEntry.timestamp) / bucket_seconds) * bucket_seconds).label("bucket"),
            func.count(LogEntry.id).label("count"),
        )
        .where(base.whereclause)
        .group_by("bucket")
        .order_by("bucket")
    )
    timeline_rows = (await db.execute(timeline_q)).all()
    timeline = [{"bucket": r.bucket.isoformat() if r.bucket else None, "count": int(r.count)} for r in timeline_rows]

    # Top N helpers
    async def top_by(column, n):
        q = (
            select(column.label("key"), func.count(LogEntry.id).label("count"))
            .where(base.whereclause)
            .where(column.isnot(None))
            .group_by(column)
            .order_by(func.count(LogEntry.id).desc())
            .limit(n)
        )
        rows = (await db.execute(q)).all()
        return [{"key": str(r.key), "count": int(r.count)} for r in rows if r.key]

    top_src_ips = await top_by(LogEntry.src_ip, top_n)
    top_users = await top_by(LogEntry.user, top_n)
    top_event_types = await top_by(LogEntry.event_type, top_n)
    by_source = await top_by(LogEntry.source, 20)

    # Severity buckets
    sev_q = (
        select(LogEntry.severity, func.count(LogEntry.id).label("count"))
        .where(base.whereclause)
        .group_by(LogEntry.severity)
        .order_by(LogEntry.severity)
    )
    sev_rows = (await db.execute(sev_q)).all()
    by_severity = [{"key": str(r.severity), "count": int(r.count)} for r in sev_rows]

    return {
        "total": int(total),
        "start": start_dt.isoformat(),
        "end": end_dt.isoformat(),
        "bucket_minutes": bucket_minutes,
        "timeline": timeline,
        "top_src_ips": top_src_ips,
        "top_users": top_users,
        "top_event_types": top_event_types,
        "by_source": by_source,
        "by_severity": by_severity,
    }


@router.get("")
async def query_logs(
    request: Request,
    tenant: Optional[List[str]] = Query(None),
    source: Optional[List[str]] = Query(None),
    event_type: Optional[List[str]] = Query(None),
    action: Optional[List[str]] = Query(None),
    geo_country: Optional[str] = Query(None, description="Filter by geo country code"),
    severity: Optional[List[str]] = Query(None, description="Severity buckets: low/medium/high/critical"),
    start: Optional[str] = Query(None, description="ISO8601 start time"),
    end: Optional[str] = Query(None, description="ISO8601 end time"),
    q: Optional[str] = Query(None, description="Full-text search"),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=1000),
    current_user: UserDB = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """GET /logs - query logs with filters per spec.md 5.2

    `tenant`, `source`, `event_type`, `action`, and `severity` accept multiple
    values (either repeated params like ?source=api&source=aws or a single
    comma-separated value). `severity` is a list of bucket names
    (low/medium/high/critical) — the API expands each bucket to its numeric
    range and OR's them so non-contiguous buckets (e.g. critical+low) don't
    accidentally include the gap.
    """
    tenants = _normalize_list(tenant)
    sources = _normalize_list(source)
    event_types = _normalize_list(event_type)
    actions = _normalize_list(action)
    severities = _normalize_list(severity)

    query = select(LogEntry)
    query = _apply_common_filters(query, current_user, tenants, sources, event_types,
                                  actions, geo_country, severities, start, end)

    if q:
        search_filter = or_(
            LogEntry.event_type.ilike(f"%{q}%"),
            LogEntry.user.ilike(f"%{q}%"),
            LogEntry.src_ip.ilike(f"%{q}%"),
            LogEntry.host.ilike(f"%{q}%"),
            LogEntry.rdns_hostname.ilike(f"%{q}%"),
            LogEntry.action.ilike(f"%{q}%"),
        )
        if db.bind.dialect.name == "postgres":
            search_filter = search_filter.or_(
                cast(LogEntry.raw, Text).ilike(f"%{q}%")
            )
        query = query.where(search_filter)

    # Build count query from the same conditions (don't rely on query.whereclause).
    count_query = select(func.count(LogEntry.id))
    if query.whereclause is not None:
        count_query = count_query.where(query.whereclause)
    total = (await db.execute(count_query)).scalar_one()

    # Pagination
    offset = (page - 1) * size
    paged = query.order_by(LogEntry.timestamp.desc()).offset(offset).limit(size)

    result = await db.execute(paged)
    logs = result.scalars().all()

    pages = (total + size - 1) // size if total else 0

    return {
        "total": total,
        "page": page,
        "size": size,
        "pages": pages,
        "has_next": page < pages,
        "has_prev": page > 1,
        "logs": [_serialize_log(log) for log in logs],
    }
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from datetime import datetime
from backend.storage.database import get_db, UserDB
from backend.services.alert_engine import AlertEngine
from backend.models.schemas import AlertRule, TriggeredAlert
from backend.auth.jwt import get_current_user, require_admin

router = APIRouter(prefix="/alerts", tags=["Alerts"])


@router.get("")
async def get_alerts(
    current_user: UserDB = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """GET /alerts - get all alert rules per spec.md 5.3.

    Viewers only see rules scoped to their own tenant; admins see every rule
    (Critical #2 — multi-tenant isolation).
    """
    from sqlalchemy import select, or_
    from backend.storage.database import AlertRuleDB

    if current_user.role == "Viewer":
        result = await db.execute(
            select(AlertRuleDB).where(
                or_(
                    AlertRuleDB.tenant == current_user.tenant,
                    AlertRuleDB.tenant == "*",
                )
            ).order_by(AlertRuleDB.id)
        )
    else:
        result = await db.execute(select(AlertRuleDB).order_by(AlertRuleDB.id))
    rules = list(result.scalars().all())
    return {
        "rules": [
            {
                "id": r.id,
                "tenant": r.tenant,
                "name": r.name,
                "description": r.description,
                "event_types": r.event_types,
                "threshold": r.threshold,
                "window_minutes": r.window_minutes,
                "group_by": r.group_by,
                "action": r.action,
                "webhook_url": r.webhook_url,
                "email_to": r.email_to,
                "enabled": r.enabled,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rules
        ]
    }


@router.post("")
async def create_alert(
    rule: AlertRule,
    current_user: UserDB = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """POST /alerts - create new alert rule per spec.md 5.3 (Admin only)."""
    engine = AlertEngine(db)
    # Force Viewers out (require_admin already does that) and clamp the tenant
    # for Admin creation: an empty/missing tenant defaults to global ("*").
    rule.tenant = rule.tenant or "*"
    db_rule = await engine.create_alert_rule(rule)
    return {"id": db_rule.id, "status": "created", "rule": db_rule}


@router.put("/{rule_id}")
async def update_alert(
    rule_id: int,
    rule: AlertRule,
    current_user: UserDB = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """PUT /alerts/{id} - update an existing alert rule (Admin only).

    Spec §5.3 deviation: spec only permits GET /alerts and POST /alerts. This
    PUT exists because Medium #17 requires the Alert Rules UI to edit
    existing rules (per spec §7 'ดู/สร้าง/แก้ไข'). Documented in
    CODE_REVIEW.md N2; either remove or update spec.md §5.3.
    """
    engine = AlertEngine(db)
    db_rule = await engine.update_alert_rule(rule_id, rule)
    if not db_rule:
        raise HTTPException(status_code=404, detail="Alert rule not found")
    return {"id": db_rule.id, "status": "updated", "rule": db_rule}


@router.delete("/{rule_id}")
async def delete_alert(
    rule_id: int,
    current_user: UserDB = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """DELETE /alerts/{id} - delete an alert rule (Admin only).

    Spec §5.3 deviation: spec does not authorize DELETE on alert rules.
    Note that spec §7 'Alert Rules: ดู/สร้าง/แก้ไข' explicitly omits delete,
    so this endpoint is unused by the UI (Medium #17 fix removed the delete
    button). Documented in CODE_REVIEW.md N2 — kept available for ops use
    but not exposed by the frontend.
    """
    engine = AlertEngine(db)
    deleted = await engine.delete_alert_rule(rule_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Alert rule not found")
    return {"status": "deleted", "id": rule_id}


@router.get("/triggered")
async def get_triggered_alerts(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    tenant: Optional[str] = Query(None, description="Filter by tenant"),
    severity: Optional[str] = Query(None, description="Filter by severity: low, medium, high, critical"),
    source: Optional[str] = Query(None, description="Filter by source: api, ad, firewall, etc."),
    acknowledged: Optional[bool] = Query(None, description="Filter by acknowledged status"),
    start_time: Optional[datetime] = Query(None, description="Filter start time (ISO format)"),
    end_time: Optional[datetime] = Query(None, description="Filter end time (ISO format)"),
    current_user: UserDB = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """GET /alerts/triggered - view triggered alerts with filters and grouping

    Grouped alerts: Same src_ip + rule_name within time window = one alert group.
    Multiple occurrences are counted in 'count' field.

    Multi-tenant: when the caller is a Viewer (spec §6), the `tenant` query
    parameter is forcibly overridden with the JWT's tenant claim — a Viewer
    cannot pass another tenant's name and broaden their view. Admins honour
    the parameter as supplied (or see all rows when it is omitted).

    HIGH (pagination): supports `?offset=N&limit=M` so the UI can fetch
    page-by-page. Response carries `total` for the page count.
    """
    engine = AlertEngine(db)

    # If viewer, restrict to their tenant — silently overrides the query param
    # so a Viewer cannot read another tenant's alerts by passing `?tenant=...`.
    filter_tenant = tenant
    if current_user.role == "Viewer":
        filter_tenant = current_user.tenant

    alerts, total = await engine.get_triggered_alerts(
        limit=limit,
        offset=offset,
        tenant=filter_tenant,
        severity=severity,
        source=source,
        acknowledged=acknowledged,
        start_time=start_time,
        end_time=end_time
    )

    # Convert to response format
    alert_list = []
    for a in alerts:
        alert_list.append({
            "id": a.id,
            "rule_id": a.rule_id,
            "rule_name": a.rule_name,
            "group_key": a.group_key,
            "src_ip": a.src_ip,
            "count": a.count,
            "unique_count": a.unique_count,
            "severity": a.severity,
            "first_seen": a.first_seen.isoformat() if a.first_seen else None,
            "last_seen": a.last_seen.isoformat() if a.last_seen else None,
            "tenant": a.tenant,
            "source": a.source,
            "event_type": a.event_type,
            "log_count": len(a.logs) if a.logs else 0,
            "acknowledged": a.acknowledged,
            "triggered_at": a.triggered_at.isoformat() if a.triggered_at else None
        })

    return {"alerts": alert_list, "total": total, "offset": offset, "limit": limit}


@router.get("/triggered/{alert_id}")
async def get_triggered_alert_detail(
    alert_id: int,
    current_user: UserDB = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """GET /alerts/triggered/{alert_id} - view alert group detail with all logs.

    Spec §5.3 deviation: spec only permits GET /alerts/triggered (the list
    view). This detail endpoint backs the AlertTriggered UI's row-expansion
    behaviour. Documented in CODE_REVIEW.md N2.
    """
    engine = AlertEngine(db)

    from sqlalchemy import select
    from backend.storage.database import TriggeredAlertDB

    result = await db.execute(
        select(TriggeredAlertDB).where(TriggeredAlertDB.id == alert_id)
    )
    alert = result.scalar_one_or_none()

    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    # Check tenant access for viewers
    if current_user.role == "Viewer" and alert.tenant != current_user.tenant:
        raise HTTPException(status_code=403, detail="Access denied")

    # Get all logs for this alert
    logs = await engine.get_alert_logs(alert_id)

    return {
        "alert": {
            "id": alert.id,
            "rule_id": alert.rule_id,
            "rule_name": alert.rule_name,
            "group_key": alert.group_key,
            "src_ip": alert.src_ip,
            "count": alert.count,
            "unique_count": alert.unique_count,
            "severity": alert.severity,
            "first_seen": alert.first_seen.isoformat() if alert.first_seen else None,
            "last_seen": alert.last_seen.isoformat() if alert.last_seen else None,
            "tenant": alert.tenant,
            "source": alert.source,
            "event_type": alert.event_type,
            "acknowledged": alert.acknowledged
        },
        "logs": [
            {
                "id": log.id,
                "@timestamp": log.timestamp.isoformat() if log.timestamp else None,
                "tenant": log.tenant,
                "source": log.source,
                "event_type": log.event_type,
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
                "status_code": log.status_code,
                "rule_name": log.rule_name,
                "geo_country": log.geo_country,
                "geo_city": log.geo_city,
                "raw": log.raw,
                "_tags": log._tags
            }
            for log in logs
        ]
    }


@router.post("/{alert_id}/acknowledge")
async def acknowledge_alert(
    alert_id: int,
    current_user: UserDB = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Acknowledge a triggered alert (Viewer scoped to own tenant per spec §6).

    Spec §5.3 deviation: spec only permits GET /alerts, POST /alerts, and
    GET /alerts/triggered. This acknowledge endpoint is required by
    Critical #3 to let tenants mark alerts as handled. Documented in
    CODE_REVIEW.md N2 — if strict spec compliance is required, replace
    with a PATCH /alerts/triggered/{id} once spec §5.3 is updated.
    """
    from sqlalchemy import select
    from backend.storage.database import TriggeredAlertDB

    # Single SELECT: load the alert, scope it for the current user, and flip
    # `acknowledged` on the same row. The previous flow ran an engine-level
    # SELECT after this, doubling the round-trips for no reason.
    pre = (await db.execute(
        select(TriggeredAlertDB).where(TriggeredAlertDB.id == alert_id)
    )).scalar_one_or_none()
    if not pre:
        raise HTTPException(status_code=404, detail="Alert not found")
    if current_user.role == "Viewer" and pre.tenant != current_user.tenant:
        raise HTTPException(status_code=403, detail="Access denied")

    pre.acknowledged = True
    await db.commit()
    await db.refresh(pre)
    return {"status": "acknowledged", "alert_id": alert_id}

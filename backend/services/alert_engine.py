from datetime import datetime, timedelta, timezone
from typing import List, Optional
import asyncio
import logging
from sqlalchemy import select, and_, or_, func, String
from sqlalchemy.ext.asyncio import AsyncSession
from backend.storage.database import AlertRuleDB, TriggeredAlertDB, LogEntry
from backend.models.schemas import AlertRule, TriggeredAlert
import httpx

logger = logging.getLogger("log-management.alert_engine")

FAILED_LOGIN_EVENT_TYPES = ("LogonFailed", "app_login_failed")


def _calculate_severity(log_severity: int) -> str:
    """Map log severity (0-10) to alert severity bucket."""
    if log_severity >= 9:
        return "critical"
    if log_severity >= 7:
        return "high"
    if log_severity >= 4:
        return "medium"
    return "low"


def _make_group_key(src_ip: str, rule_name: str) -> str:
    return f"{src_ip}:{rule_name}"


class AlertEngine:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def check_brute_force(self, log: LogEntry) -> Optional[TriggeredAlertDB]:
        """
        Spec §8 Login Failed Brute-Force: trigger only when the number of failed
        login events from the same src_ip within the rule's window crosses the
        rule's threshold. Each (src_ip, rule) pair is grouped.
        """
        if log.event_type not in FAILED_LOGIN_EVENT_TYPES:
            return None
        if not log.src_ip:
            return None

        # Match enabled rules whose event_types list contains this event_type.
        # Critical #2: rules must be tenant-scoped. A rule with tenant="*"
        # applies to every tenant; otherwise the rule's tenant must match the
        # log's tenant (spec §6 — multi-tenant isolation).
        result = await self.db.execute(
            select(AlertRuleDB).where(
                AlertRuleDB.enabled == True,
                AlertRuleDB.event_types.cast(String).contains(log.event_type),
                or_(
                    AlertRuleDB.tenant == "*",
                    AlertRuleDB.tenant == log.tenant,
                ),
            )
        )
        rules = result.scalars().all()
        if not rules:
            return None

        triggered = None
        now = datetime.now(timezone.utc)

        for rule in rules:
            window_start = now - timedelta(minutes=rule.window_minutes)
            group_key = _make_group_key(log.src_ip, rule.name)

            # Count how many failed-login logs from this src_ip happened
            # within the rule's window. Including the current log row.
            count_q = select(func.count(LogEntry.id)).where(
                and_(
                    LogEntry.src_ip == log.src_ip,
                    LogEntry.event_type.in_(FAILED_LOGIN_EVENT_TYPES),
                    LogEntry.timestamp >= window_start,
                    LogEntry.tenant == log.tenant,
                )
            )
            count = (await self.db.execute(count_q)).scalar_one()

            if count < rule.threshold:
                continue

            # Find an unacknowledged open alert group within this window.
            existing_q = select(TriggeredAlertDB).where(
                and_(
                    TriggeredAlertDB.group_key == group_key,
                    TriggeredAlertDB.acknowledged == False,
                    TriggeredAlertDB.last_seen >= window_start,
                )
            )
            existing = (await self.db.execute(existing_q)).scalar_one_or_none()

            if existing:
                existing.count = count
                existing.last_seen = now
                existing.src_ip = log.src_ip
                if log.id is not None:
                    logs_list = list(existing.logs or [])
                    if log.id not in logs_list:
                        logs_list.append(log.id)
                    existing.logs = logs_list
                new_severity = _calculate_severity(log.severity or 5)
                order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
                if order.get(new_severity, 0) > order.get(existing.severity, 0):
                    existing.severity = new_severity
                await self.db.commit()
                triggered = existing
            else:
                triggered = await self._create_triggered_alert(rule, log, group_key, count)

        return triggered

    async def _create_triggered_alert(
        self, rule: AlertRuleDB, log: LogEntry, group_key: str, count: int
    ) -> TriggeredAlertDB:
        now = datetime.now(timezone.utc)
        triggered = TriggeredAlertDB(
            rule_id=rule.id,
            rule_name=rule.name,
            group_key=group_key,
            triggered_at=now,
            src_ip=log.src_ip,
            count=count,
            unique_count=1,
            severity=_calculate_severity(log.severity or 5),
            first_seen=now,
            last_seen=now,
            tenant=log.tenant or "default",
            source=log.source,
            event_type=log.event_type,
            logs=[log.id] if log.id else [],
            acknowledged=False,
        )
        self.db.add(triggered)
        await self.db.commit()
        await self.db.refresh(triggered)

        if rule.action in ("webhook", "both") and rule.webhook_url:
            asyncio.create_task(self._send_webhook(rule, triggered))
        if rule.action in ("email", "both") and rule.email_to:
            asyncio.create_task(self._send_email(rule, triggered))

        return triggered

    async def _send_webhook(self, rule: AlertRuleDB, triggered: TriggeredAlertDB):
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    rule.webhook_url,
                    json={
                        "alert": "Brute Force Login Detected",
                        "rule_name": rule.name,
                        "src_ip": triggered.src_ip,
                        "count": triggered.count,
                        "severity": triggered.severity,
                        "tenant": triggered.tenant,
                        "triggered_at": triggered.triggered_at.isoformat(),
                        "action": "Review and block source IP",
                    },
                    timeout=10.0,
                )
        except Exception:
            logger.exception("Webhook delivery failed for alert %s", triggered.id)

    async def _send_email(self, rule: AlertRuleDB, triggered: TriggeredAlertDB):
        # Email delivery is intentionally a no-op here — wire SMTP/SES in your environment.
        logger.info(
            "Email alert would be sent to %s for rule %s src_ip=%s",
            rule.email_to, rule.name, triggered.src_ip,
        )

    async def get_alert_rules(self) -> List[AlertRuleDB]:
        result = await self.db.execute(select(AlertRuleDB).order_by(AlertRuleDB.id))
        return list(result.scalars().all())

    async def create_alert_rule(self, rule: AlertRule) -> AlertRuleDB:
        db_rule = AlertRuleDB(
            tenant=rule.tenant or "*",
            name=rule.name,
            description=rule.description,
            event_types=rule.event_types,
            threshold=rule.threshold,
            window_minutes=rule.window_minutes,
            group_by=rule.group_by,
            action=rule.action,
            webhook_url=rule.webhook_url,
            email_to=rule.email_to,
            enabled=rule.enabled,
        )
        self.db.add(db_rule)
        await self.db.commit()
        await self.db.refresh(db_rule)
        return db_rule

    async def update_alert_rule(self, rule_id: int, rule: AlertRule) -> Optional[AlertRuleDB]:
        result = await self.db.execute(select(AlertRuleDB).where(AlertRuleDB.id == rule_id))
        db_rule = result.scalar_one_or_none()
        if not db_rule:
            return None
        # Partial update — only the fields the schema carries.
        if rule.tenant is not None:
            db_rule.tenant = rule.tenant
        db_rule.name = rule.name
        db_rule.description = rule.description
        db_rule.event_types = rule.event_types
        db_rule.threshold = rule.threshold
        db_rule.window_minutes = rule.window_minutes
        db_rule.group_by = rule.group_by
        db_rule.action = rule.action
        db_rule.webhook_url = rule.webhook_url
        db_rule.email_to = rule.email_to
        db_rule.enabled = rule.enabled
        await self.db.commit()
        await self.db.refresh(db_rule)
        return db_rule

    async def delete_alert_rule(self, rule_id: int) -> bool:
        result = await self.db.execute(select(AlertRuleDB).where(AlertRuleDB.id == rule_id))
        db_rule = result.scalar_one_or_none()
        if not db_rule:
            return False
        await self.db.delete(db_rule)
        await self.db.commit()
        return True

    async def get_triggered_alerts(
        self,
        limit: int = 100,
        tenant: Optional[str] = None,
        severity: Optional[str] = None,
        source: Optional[str] = None,
        acknowledged: Optional[bool] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[TriggeredAlertDB]:
        query = select(TriggeredAlertDB)
        conditions = []
        if tenant:
            conditions.append(TriggeredAlertDB.tenant == tenant)
        if severity:
            conditions.append(TriggeredAlertDB.severity == severity)
        if source:
            conditions.append(TriggeredAlertDB.source == source)
        if acknowledged is not None:
            conditions.append(TriggeredAlertDB.acknowledged == acknowledged)
        if start_time:
            conditions.append(TriggeredAlertDB.last_seen >= start_time)
        if end_time:
            conditions.append(TriggeredAlertDB.last_seen <= end_time)
        if conditions:
            query = query.where(and_(*conditions))
        query = query.order_by(TriggeredAlertDB.last_seen.desc()).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_alert_logs(self, alert_id: int) -> List[LogEntry]:
        result = await self.db.execute(
            select(TriggeredAlertDB).where(TriggeredAlertDB.id == alert_id)
        )
        alert = result.scalar_one_or_none()
        if not alert or not alert.logs:
            return []
        log_ids = alert.logs if isinstance(alert.logs, list) else []
        if not log_ids:
            return []
        log_result = await self.db.execute(
            select(LogEntry).where(LogEntry.id.in_(log_ids))
        )
        return list(log_result.scalars().all())

    async def acknowledge_alert(self, alert_id: int) -> Optional[TriggeredAlertDB]:
        result = await self.db.execute(
            select(TriggeredAlertDB).where(TriggeredAlertDB.id == alert_id)
        )
        alert = result.scalar_one_or_none()
        if alert:
            alert.acknowledged = True
            await self.db.commit()
            await self.db.refresh(alert)
        return alert

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

# Cap the sample-log list per triggered alert. The `count` field conveys the
# raw total; the list is only sampled for the UI's "related logs" view, so a
# rolling window of the most recent N entries is enough. Without this, a
# sustained attack rewrites a multi-megabyte JSON blob on every update.
MAX_ALERT_LOG_SAMPLES = 100


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

        Race-safety: two logs from the same src_ip ingested concurrently could
        otherwise both observe count==threshold-1, both decide "not yet", and
        miss the alert — or both observe count==threshold and both insert
        duplicate open alerts. We lock the matched rule rows (Postgres
        `SELECT ... FOR UPDATE`; SQLite is single-writer so the lock is
        implicit) and the existing-alert row so the count → create sequence
        is serialised for any given (src_ip, rule) group.
        """
        if log.event_type not in FAILED_LOGIN_EVENT_TYPES:
            return None
        if not log.src_ip:
            return None

        # Match enabled rules whose event_types list contains this event_type.
        # Critical #2: rules must be tenant-scoped. A rule with tenant="*"
        # applies to every tenant; otherwise the rule's tenant must match the
        # log's tenant (spec §6 — multi-tenant isolation).
        # with_for_update() serialises concurrent transactions working on the
        # same rule — on Postgres this acquires a row lock; on SQLite the
        # engine is single-writer so the call is a no-op.
        result = await self.db.execute(
            select(AlertRuleDB).where(
                AlertRuleDB.enabled == True,
                AlertRuleDB.event_types.cast(String).contains(log.event_type),
                or_(
                    AlertRuleDB.tenant == "*",
                    AlertRuleDB.tenant == log.tenant,
                ),
            ).with_for_update()
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
            # Lock the row so a sibling transaction can't also "create" while
            # we decide to update it.
            existing_q = select(TriggeredAlertDB).where(
                and_(
                    TriggeredAlertDB.group_key == group_key,
                    TriggeredAlertDB.acknowledged == False,
                    TriggeredAlertDB.last_seen >= window_start,
                )
            ).with_for_update()
            existing = (await self.db.execute(existing_q)).scalar_one_or_none()

            if existing:
                existing.count = count
                existing.last_seen = now
                existing.src_ip = log.src_ip
                if log.id is not None:
                    # Cap the sample list at MAX_ALERT_LOG_SAMPLES so a long-
                    # running brute force doesn't grow one JSON column to
                    # megabytes and rewrite it on every update. The `count`
                    # field already conveys magnitude; the list is only used
                    # for "show related logs" UI samples.
                    logs_list = list(existing.logs or [])
                    if log.id not in logs_list:
                        if len(logs_list) < MAX_ALERT_LOG_SAMPLES:
                            logs_list.append(log.id)
                        else:
                            # Keep the newest MAX_ALERT_LOG_SAMPLES — drop the
                            # oldest so the sample stays recent.
                            logs_list = logs_list[1:] + [log.id]
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
        # Reload in a fresh session — the caller's session was already committed
        # when this fire-and-forget task started, so the ORM identity map is
        # detached and a naive `triggered.webhook_sent = True` would have no
        # effect on the database.
        from backend.storage.database import async_session
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
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
                response.raise_for_status()
        except Exception:
            logger.exception("Webhook delivery failed for alert %s", triggered.id)
            return

        # Flip the delivery flag in a fresh session so a restart that
        # pre-empted the in-flight HTTP request can be detected and retried
        # on next startup.
        try:
            async with async_session() as db:
                row = await db.get(TriggeredAlertDB, triggered.id)
                if row and not row.webhook_sent:
                    row.webhook_sent = True
                    await db.commit()
        except Exception:
            logger.exception("Failed to mark webhook_sent for alert %s", triggered.id)

    async def _send_email(self, rule: AlertRuleDB, triggered: TriggeredAlertDB):
        # Email delivery is intentionally a no-op here — wire SMTP/SES in your
        # environment. We still flip `email_sent` to True so the startup-retry
        # scanner doesn't keep re-firing a no-op delivery.
        logger.info(
            "Email alert would be sent to %s for rule %s src_ip=%s",
            rule.email_to, rule.name, triggered.src_ip,
        )
        try:
            from backend.storage.database import async_session
            async with async_session() as db:
                row = await db.get(TriggeredAlertDB, triggered.id)
                if row and not row.email_sent:
                    row.email_sent = True
                    await db.commit()
        except Exception:
            logger.exception("Failed to mark email_sent for alert %s", triggered.id)

    async def _retry_pending_deliveries(self):
        """On startup, re-fire any delivery that didn't complete last time.

        Medium #5 fix: `_send_webhook` / `_send_email` are fire-and-forget
        tasks. A restart that pre-empts the HTTP request leaves `webhook_sent`
        / `email_sent` at False. Scan for those rows older than 30s (to avoid
        racing a still-in-flight concurrent ingest) and re-fire.

        Email has no-op delivery here, so an unflipped `email_sent` only means
        the prior process died before the flag UPDATE. Retry idempotently.
        """
        from backend.storage.database import async_session

        threshold = datetime.now(timezone.utc) - timedelta(seconds=30)
        # Snapshot (alert, rule) pairs inside the session — outside the `with`
        # block, `db` is closed and any `.execute()` would fail.
        to_retry: list[tuple[TriggeredAlertDB, AlertRuleDB]] = []
        async with async_session() as db:
            pending = (await db.execute(
                select(TriggeredAlertDB).where(
                    or_(
                        TriggeredAlertDB.webhook_sent == False,  # noqa: E712
                        TriggeredAlertDB.email_sent == False,    # noqa: E712
                    ),
                    TriggeredAlertDB.triggered_at <= threshold,
                )
            )).scalars().all()
            for alert in pending:
                rule = (await db.execute(
                    select(AlertRuleDB).where(AlertRuleDB.id == alert.rule_id)
                )).scalar_one_or_none()
                if rule:
                    to_retry.append((alert, rule))

        for alert, rule in to_retry:
            if not alert.webhook_sent and rule.action in ("webhook", "both") and rule.webhook_url:
                logger.info("Retrying pending webhook for alert %s", alert.id)
                asyncio.create_task(self._send_webhook(rule, alert))
            if not alert.email_sent and rule.action in ("email", "both") and rule.email_to:
                logger.info("Retrying pending email for alert %s", alert.id)
                asyncio.create_task(self._send_email(rule, alert))

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
        # TriggeredAlertDB.rule_id has no FK constraint, so deleting the rule
        # leaves orphans that the retry loop would then fail to resolve when
        # re-fetching the rule. Clean them up in the same transaction.
        from sqlalchemy import delete as sql_delete
        await self.db.execute(
            sql_delete(TriggeredAlertDB).where(TriggeredAlertDB.rule_id == rule_id)
        )
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

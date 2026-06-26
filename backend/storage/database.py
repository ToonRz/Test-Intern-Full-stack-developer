from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, JSON, Index, Float
from sqlalchemy.pool import StaticPool
from datetime import datetime, timezone
from backend.config import get_settings

settings = get_settings()

# SQLite (used in tests) needs StaticPool + check_same_thread=False so a single
# in-memory database is shared across all connections; otherwise each session
# would see an empty schema.
_engine_kwargs: dict = {"echo": settings.DEBUG, "future": True}
if settings.DATABASE_URL.startswith("sqlite"):
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
    if ":memory:" in settings.DATABASE_URL:
        _engine_kwargs["poolclass"] = StaticPool

engine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

utc_now = lambda: datetime.now(timezone.utc)


class LogEntry(Base):
    __tablename__ = "logs"

    id = Column(Integer, primary_key=True, index=True)
    tenant = Column(String, nullable=False, index=True)
    source = Column(String, nullable=False)
    vendor = Column(String, nullable=True)
    product = Column(String, nullable=True)
    event_type = Column(String, nullable=False, index=True)
    event_subtype = Column(String, nullable=True)
    severity = Column(Integer, default=5)
    action = Column(String, nullable=True)
    src_ip = Column(String, nullable=True, index=True)
    src_port = Column(Integer, nullable=True)
    dst_ip = Column(String, nullable=True)
    dst_port = Column(Integer, nullable=True)
    protocol = Column(String, nullable=True)
    user = Column(String, nullable=True, index=True)
    host = Column(String, nullable=True)
    process = Column(String, nullable=True)
    url = Column(String, nullable=True)
    http_method = Column(String, nullable=True)
    status_code = Column(Integer, nullable=True)
    rule_name = Column(String, nullable=True)
    rule_id = Column(String, nullable=True)
    # Enrichment fields (GeoIP)
    geo_country = Column(String, nullable=True)
    geo_city = Column(String, nullable=True)
    geo_lat = Column(Float, nullable=True)
    geo_lon = Column(Float, nullable=True)
    # Enrichment fields (Reverse DNS)
    rdns_hostname = Column(String, nullable=True)
    # Cloud info (AWS, etc.)
    cloud = Column(JSON, nullable=True)
    # Raw original data
    raw = Column(JSON, nullable=True)
    _tags = Column(JSON, nullable=True)
    # Timestamps
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    __table_args__ = (
        Index("idx_tenant_timestamp", "tenant", "timestamp"),
        Index("idx_source_timestamp", "source", "timestamp"),
        Index("idx_geo_country", "geo_country"),
        Index("idx_src_ip_enriched", "src_ip", "geo_country"),
        # Low #29: GIN index on `raw` requires the column type to be JSONB,
        # not JSON — Postgres raises "data type json has no default operator
        # class for access method gin" otherwise. Migration deferred: the
        # current `JSON` column would need to be ALTER TYPE'd to JSONB first,
        # which is a separate change. Documented in CODE_REVIEW.md — the
        # slow `cast(raw as text) ILIKE` query remains in routers/logs.py.
    )


class AlertRuleDB(Base):
    __tablename__ = "alert_rules"

    id = Column(Integer, primary_key=True, index=True)
    # tenant="*" means the rule applies to logs from every tenant (global rule);
    # otherwise the rule only fires for logs whose tenant matches this column.
    # Critical #2 — without this filter, rules from tenant A would trigger on
    # tenant B's logs and notify the wrong operator.
    tenant = Column(String, nullable=False, default="*", index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    event_types = Column(JSON, nullable=False)
    threshold = Column(Integer, nullable=False)
    window_minutes = Column(Integer, nullable=False, default=5)
    group_by = Column(String, nullable=False, default="src_ip")
    action = Column(String, nullable=False, default="store")
    webhook_url = Column(String, nullable=True)
    email_to = Column(String, nullable=True)
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class TriggeredAlertDB(Base):
    __tablename__ = "triggered_alerts"

    id = Column(Integer, primary_key=True, index=True)
    rule_id = Column(Integer, nullable=False, index=True)
    rule_name = Column(String, nullable=False)
    # Grouping: same src_ip + rule within time window = same alert group
    group_key = Column(String, nullable=False, index=True)  # e.g., "192.0.2.100:brute_force"
    # Alert details
    src_ip = Column(String, nullable=False, index=True)
    count = Column(Integer, nullable=False)  # Total occurrences
    unique_count = Column(Integer, nullable=False, default=1)  # Unique IPs/users affected
    severity = Column(String, nullable=False, default="medium")  # low, medium, high, critical
    # Time range of grouped alerts
    first_seen = Column(DateTime(timezone=True), nullable=False)
    last_seen = Column(DateTime(timezone=True), nullable=False)
    # Multi-tenant
    tenant = Column(String, nullable=False, index=True)
    # Source info
    source = Column(String, nullable=True)
    event_type = Column(String, nullable=True)
    # Log IDs for detail
    logs = Column(JSON, nullable=True)  # [log_id, ...]
    acknowledged = Column(Boolean, default=False)
    # Delivery flags — flipped to True by the alert engine after the
    # corresponding side-effect succeeds. They start False so a restart that
    # pre-empts the fire-and-forget delivery task can be detected and the
    # pending webhook/email retried on next startup.
    webhook_sent = Column(Boolean, default=False)
    email_sent = Column(Boolean, default=False)
    # Legacy field for compatibility
    triggered_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (
        Index("idx_group_key_triggered", "group_key", "triggered_at"),
        Index("idx_tenant_severity", "tenant", "severity"),
    )


class UserDB(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, nullable=False, index=True)
    email = Column(String, unique=True, nullable=True)
    role = Column(String, nullable=False, default="Viewer")
    tenant = Column(String, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    # updated_at is bumped on every UPDATE; get_current_user compares it against
    # the JWT `iat` so a token issued before the last role/tenant/password
    # change is rejected (Critical #5 — privilege escalation after demote).
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class TenantDB(Base):
    """Tenant registry — populates the User Management UI's tenant dropdown.

    Per spec §6, isolation is field-level: every LogEntry row carries a
    `tenant` column, and every API request is scoped by the JWT tenant claim.
    There is no schema-per-tenant isolation; all logs live in `public.logs`.

    The `schema_name` column is a legacy artifact from an earlier schema-isolated
    design. It is nullable because the current field-level design no longer
    assigns tenants to PostgreSQL schemas.
    """
    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False, index=True)
    schema_name = Column(String, unique=True, nullable=True)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)


async def init_db():
    """Create schema and apply lightweight ALTER migrations.

    Critical B-C15: each ALTER is wrapped in a try/except so a failure on
    one migration (e.g. partial schema state, locked table, or missing
    permission) doesn't abort the whole init. The exception is logged so
    the operator can see which migration failed and act on it, but the
    process still boots. This matches Alembic's "best-effort" pattern for
    pre-production schemas.
    """
    import logging
    _log = logging.getLogger("log-management.init_db")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Lightweight idempotent migration: add columns introduced after the
        # table's initial create_all. create_all is a no-op for existing
        # tables, so we have to ALTER TABLE manually. Used for UserDB.updated_at
        # (Critical #5 — JWT re-validation) and AlertRuleDB.tenant (Critical #2).
        from sqlalchemy import inspect, text
        from sqlalchemy.engine import Inspector

        def _has_column(sync_conn, table: str, column: str) -> bool:
            try:
                inspector = Inspector.from_engine(sync_conn)
                return column in {c["name"] for c in inspector.get_columns(table)}
            except Exception:
                # If we can't even introspect (corrupt metadata, missing
                # table), assume the column is missing and try to add it.
                return False

        def _alter(sync_conn, dialect: str, table: str, column: str, ddl_postgres: str, ddl_sqlite: str) -> None:
            if _has_column(sync_conn, table, column):
                return
            stmt = ddl_postgres if dialect == "postgresql" else ddl_sqlite
            try:
                sync_conn.execute(text(stmt))
                _log.info("Migration: added %s.%s", table, column)
            except Exception as e:
                # Don't abort the whole init on a single failed migration.
                # The column may already exist under a different type, or
                # the table may be in an odd state — log and continue.
                _log.warning("Migration skipped %s.%s: %s", table, column, e)

        dialect = engine.dialect.name
        await conn.run_sync(
            lambda sync_conn: _alter(
                sync_conn, dialect, "users", "updated_at",
                "ALTER TABLE users ADD COLUMN updated_at TIMESTAMP WITH TIME ZONE",
                "ALTER TABLE users ADD COLUMN updated_at TIMESTAMP",
            )
        )
        await conn.run_sync(
            lambda sync_conn: _alter(
                sync_conn, dialect, "alert_rules", "tenant",
                "ALTER TABLE alert_rules ADD COLUMN tenant VARCHAR NOT NULL DEFAULT '*'",
                "ALTER TABLE alert_rules ADD COLUMN tenant VARCHAR NOT NULL DEFAULT '*'",
            )
        )
        # Medium #5: webhook_sent / email_sent delivery flags on triggered
        # alerts so a restart that pre-empts the fire-and-forget delivery
        # task can be detected and retried on next startup.
        await conn.run_sync(
            lambda sync_conn: _alter(
                sync_conn, dialect, "triggered_alerts", "webhook_sent",
                "ALTER TABLE triggered_alerts ADD COLUMN webhook_sent BOOLEAN NOT NULL DEFAULT FALSE",
                "ALTER TABLE triggered_alerts ADD COLUMN webhook_sent BOOLEAN NOT NULL DEFAULT 0",
            )
        )
        await conn.run_sync(
            lambda sync_conn: _alter(
                sync_conn, dialect, "triggered_alerts", "email_sent",
                "ALTER TABLE triggered_alerts ADD COLUMN email_sent BOOLEAN NOT NULL DEFAULT FALSE",
                "ALTER TABLE triggered_alerts ADD COLUMN email_sent BOOLEAN NOT NULL DEFAULT 0",
            )
        )
        # Index for tenant-scoped alert rule lookups (Critical #2).
        if dialect == "postgresql":
            try:
                await conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS idx_alert_rules_tenant ON alert_rules (tenant)"
                ))
            except Exception as e:
                _log.warning("Index creation skipped: %s", e)
            # Low #29: GIN index requires the column to be JSONB. The current
            # `raw` column is JSON (created by SQLAlchemy's generic JSON
            # type). Migrating to JSONB is a separate change; deferring.


async def get_db() -> AsyncSession:
    async with async_session() as session:
        yield session

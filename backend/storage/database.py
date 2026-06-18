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
    )


class AlertRuleDB(Base):
    __tablename__ = "alert_rules"

    id = Column(Integer, primary_key=True, index=True)
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
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncSession:
    async with async_session() as session:
        yield session

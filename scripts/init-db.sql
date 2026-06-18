-- init-db.sql — Database initialization (spec §10).
-- Tables are also created by SQLAlchemy on first backend start, but having
-- them here means `make up` succeeds even when the API hasn't run yet.
-- IF NOT EXISTS keeps it idempotent against the SQLAlchemy bootstrap.

CREATE TABLE IF NOT EXISTS logs (
    id SERIAL PRIMARY KEY,
    tenant VARCHAR(64) NOT NULL,
    source VARCHAR(64) NOT NULL,
    vendor VARCHAR(128),
    product VARCHAR(128),
    event_type VARCHAR(128) NOT NULL,
    event_subtype VARCHAR(128),
    severity INTEGER DEFAULT 5,
    action VARCHAR(64),
    src_ip VARCHAR(64),
    src_port INTEGER,
    dst_ip VARCHAR(64),
    dst_port INTEGER,
    protocol VARCHAR(32),
    "user" VARCHAR(256),
    host VARCHAR(256),
    process VARCHAR(256),
    url TEXT,
    http_method VARCHAR(16),
    status_code INTEGER,
    rule_name VARCHAR(256),
    rule_id VARCHAR(128),
    geo_country VARCHAR(8),
    geo_city VARCHAR(128),
    geo_lat DOUBLE PRECISION,
    geo_lon DOUBLE PRECISION,
    rdns_hostname VARCHAR(256),
    cloud JSONB,
    raw JSONB,
    _tags JSONB,
    timestamp TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_logs_tenant ON logs(tenant);
CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON logs(timestamp);
CREATE INDEX IF NOT EXISTS idx_logs_src_ip ON logs(src_ip);
CREATE INDEX IF NOT EXISTS idx_logs_event_type ON logs(event_type);
CREATE INDEX IF NOT EXISTS idx_logs_user ON logs("user");
CREATE INDEX IF NOT EXISTS idx_logs_geo_country ON logs(geo_country);
CREATE INDEX IF NOT EXISTS idx_logs_tenant_timestamp ON logs(tenant, timestamp);

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(64) UNIQUE NOT NULL,
    email VARCHAR(256) UNIQUE,
    role VARCHAR(32) NOT NULL DEFAULT 'Viewer',
    tenant VARCHAR(64) NOT NULL,
    hashed_password VARCHAR(256) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS alert_rules (
    id SERIAL PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    description TEXT,
    event_types JSONB NOT NULL,
    threshold INTEGER NOT NULL,
    window_minutes INTEGER NOT NULL DEFAULT 5,
    group_by VARCHAR(64) NOT NULL DEFAULT 'src_ip',
    action VARCHAR(32) NOT NULL DEFAULT 'store',
    webhook_url VARCHAR(512),
    email_to VARCHAR(256),
    enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS triggered_alerts (
    id SERIAL PRIMARY KEY,
    rule_id INTEGER NOT NULL,
    rule_name VARCHAR(128) NOT NULL,
    group_key VARCHAR(256) NOT NULL,
    src_ip VARCHAR(64) NOT NULL,
    count INTEGER NOT NULL,
    unique_count INTEGER NOT NULL DEFAULT 1,
    severity VARCHAR(32) NOT NULL DEFAULT 'medium',
    first_seen TIMESTAMPTZ NOT NULL,
    last_seen TIMESTAMPTZ NOT NULL,
    tenant VARCHAR(64) NOT NULL,
    source VARCHAR(64),
    event_type VARCHAR(128),
    logs JSONB,
    acknowledged BOOLEAN DEFAULT FALSE,
    triggered_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_alerts_group ON triggered_alerts(group_key, triggered_at);
CREATE INDEX IF NOT EXISTS idx_alerts_tenant_severity ON triggered_alerts(tenant, severity);

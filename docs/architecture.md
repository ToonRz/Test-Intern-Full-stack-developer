# Architecture — Log Management System

## Overview

Log Management System รองรับการเก็บ รวบรวม ค้นหา และแจ้งเตือนเหตุการณ์จากหลายแหล่งข้อมูล ออกแบบมาสำหรับ 2 deployment modes:
- **Appliance** — รันบนเครื่องเดียว/VM เดียว ด้วย Docker Compose
- **SaaS/Cloud** — รันบน Cloud มี HTTPS URL สำหรับเข้าใช้งานจากภายนอก

อ้างอิง: `spec.md` (single source of truth สำหรับข้อกำหนดทั้งหมด)

## System Architecture

```
                    ┌─────────────────────────────────────────────────┐
                    │              Log Management System              │
                    └─────────────────────────────────────────────────┘
                                              │
        ┌─────────────────────────────────────┼─────────────────────────────────┐
        │                                     │                                 │
        ▼                                     ▼                                 ▼
┌───────────────┐                    ┌──────────────────┐              ┌──────────────┐
│  Ingest       │   Syslog 514       │   Backend        │   /api/v1/*  │   Frontend   │
│  (Collector)  │   HTTP /ingest ───▶│   (FastAPI)      │ ◀─────────── │  (React SPA) │
│               │                    │                  │              │              │
│ • Syslog 514  │                    │ • Normalize      │              │ • Dashboard  │
│ • HTTP /ingest│                    │ • Enrichment    │              │ • Log Search │
│ • Batch files │                    │ • Auth/RBAC      │              │ • Alerts     │
└───────────────┘                    │ • Alert Engine   │              │ • Users      │
        │                            └────────┬─────────┘              └──────┬───────┘
        │                                     │                               │
        │                                     ▼                               ▼
        │                            ┌──────────────────┐            ┌──────────────────┐
        │                            │   PostgreSQL     │            │   Nginx (TLS)    │
        │                            │   + JSONB/GIN    │            │   reverse-proxy  │
        │                            │   (logs/users/   │            │   + stream UDP   │
        │                            │    alerts/       │            └────────┬─────────┘
        │                            │    tenants)      │                     │
        │                            └──────────────────┘                     │
        │                                     ▲                               │
        │                                     │                               │
        │                            ┌────────┴─────────┐                     │
        └───────────────────────────▶│   Redis          │◀────────────────────┘
              enrichment cache        │   (cache)        │   HTTPS:443
                                     └──────────────────┘
```

## Data Flow

```
Log Sources                  Ingest Layer                   Backend
──────────────────────────────────────────────────────────────────────────

Firewall/Network     syslog msg ─▶ Syslog UDP/TCP 514 ─▶ Normalize ─▶ Enrich (GeoIP/rDNS)
                                          │                              │
HTTP API Clients     POST /ingest ────────┘                              ▼
JSON body                                                       Save (Postgres)
                                              │                          │
Batch Files          POST /ingest/batch ─────┘                          ▼
JSON batch                                              Background: AlertEngine
                                                                     │
                                                                     ▼
                                                          Triggered Alert (Postgres)
                                                                     │
                                                                     ▼
                                                          Optional Webhook / Email
```

## Components

| Component | Tech | Responsibility |
|---|---|---|
| Ingest (Syslog) | Python async UDP/TCP listener (embedded in backend) | Parse RFC3164/5424 syslog, normalize, store |
| Ingest (HTTP) | FastAPI route | Accept single JSON or batch array via `POST /ingest` |
| Ingest (Batch) | FastAPI route | Accept file-batch JSON via `POST /ingest/batch` |
| Normalizer | Python | Map source-specific fields → central schema (spec §3) |
| Enrichment | Python + MaxMind GeoLite2 + Redis cache | GeoIP, reverse DNS (async, failure-tolerant) |
| Alert Engine | Python | Brute-force rule + custom rule evaluation on every new log |
| Backend API | FastAPI + asyncpg | AuthN (JWT in HttpOnly cookie), RBAC, search, alerts, users, tenants |
| Frontend | React 18 + Recharts + react-router | Dashboard, Log Search, Alert Rules, Alert Triggered, User Mgmt |
| Nginx | nginx:alpine | TLS termination, reverse-proxy `/api/*` → backend, `/` → frontend; **stream block** forwards UDP/514 + TCP/514 to backend |
| Storage | PostgreSQL 15 + JSONB + GIN indexes | Logs, users, alert_rules, triggered_alerts, tenants |
| Cache | Redis 7 | Enrichment cache (GeoIP / rDNS) |
| TLS | Self-signed (appliance) / Let's Encrypt (SaaS) | HTTPS termination at nginx |

## Tech Stack (per spec.md §4)

| Layer | Technology | Rationale |
|---|---|---|
| Collector/Ingest | Python async (embedded) | Same codebase, simpler ops; spec allows custom collectors |
| Storage | PostgreSQL + JSONB + GIN | ACID, native JSON ops, partition-friendly |
| Backend API | FastAPI + Uvicorn (async) | Auto OpenAPI docs, async-first fits Postgres asyncpg |
| Frontend | React 18 + Recharts + Vite | Component model, declarative charts, fast dev |
| Auth | JWT in HttpOnly cookie + RBAC | Spec §6; cookie avoids localStorage XSS risk |
| Enrichment | MaxMind GeoLite2 + reverse DNS | Spec §14 "Nice-to-have: GeoIP" |
| Packaging (appliance) | Docker Compose | One-command bring-up per spec §9.1 |
| Packaging (cloud) | Docker Compose + Helm chart + Terraform | Spec §14 "Nice-to-have: IaC" |
| TLS | Self-signed (appliance) / Let's Encrypt (SaaS) | Spec §9.2 allows self-signed with clear steps |
| Observability | OpenTelemetry + `/metrics` + `/health` | Spec §14 "Nice-to-have: metrics/trace" |

## Normalized Schema

ทุก log ถูก normalize เข้า schema เดียวกันก่อนเก็บ (spec §3):

```json
{
  "@timestamp": "RFC3339 string",
  "tenant": "string",
  "source": "firewall | crowdstrike | aws | m365 | ad | api | network",
  "vendor": "string",
  "product": "string",
  "event_type": "string",
  "event_subtype": "string",
  "severity": "integer 0-10",
  "action": "allow | deny | create | delete | login | logout | alert",
  "src_ip": "string",
  "src_port": "integer",
  "dst_ip": "string",
  "dst_port": "integer",
  "protocol": "string",
  "user": "string",
  "host": "string",
  "process": "string",
  "url": "string",
  "http_method": "string",
  "status_code": "integer",
  "rule_name": "string",
  "rule_id": "string",
  "cloud": { "account_id": "string", "region": "string", "service": "string" },
  "raw": "object | string",
  "_tags": ["array of strings"]
}
```

Enrichment เพิ่ม `geo_country`, `geo_city`, `geo_lat`, `geo_lon`, `rdns_hostname` ลงใน row จริง (ไม่อยู่ใน spec schema แต่ enrich ระหว่าง ingest — ไม่กระทบ contract)

## Multi-Tenant Model (spec §6)

- Logs แยกตาม column `tenant` (ไม่ใช่ schema-per-tenant)
- JWT มี claim `tenant` + `role`
- RBAC:
  - **Admin** (`role=Admin`, `tenant=*`) — เห็น/จัดการทุก tenant, จัดการ users, tenants, alert rules
  - **Viewer** (`role=Viewer`, `tenant=demoA`) — เห็นเฉพาะ log ของ tenant ตัวเอง
- Tenant registry table (`tenants`) ใช้ populate dropdown ใน UI เท่านั้น — ไม่สร้าง schema แยก

```
┌──────────────────────────────────────────────────────┐
│                     Admin                            │
│  Tenant: * (sees all)                                │
└──────────────────────────────────────────────────────┘
         │
         ├─── Tenant: demoA ──────────────────────────
         │    • viewer: sees only demoA logs
         │
         ├─── Tenant: demoB ──────────────────────────
         │    • viewer: sees only demoB logs
         │
         └─── Tenant: demoC ──────────────────────────
              • viewer: sees only demoC logs
```

## Alerting Flow (spec §8)

```
Incoming Log
     │
     ▼
┌─────────────────┐
│ Alert Engine    │  (background task after each ingest)
│                 │
│ Check: tenant   │
│  + event_types  │
│  in alert rule? │
└────────┬────────┘
         │
         ▼
┌─────────────────┐     ┌─────────────────┐
│ Count by group  │────▶│ Threshold       │
│ within window   │     │ exceeded?       │
└─────────────────┘     └────────┬────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │ Trigger Alert           │
                    │ • Store in DB           │
                    │ • Optional webhook/email│
                    └─────────────────────────┘
```

Built-in seeded rule: **Login Failed Brute-Force** — `event_type ∈ {LogonFailed, app_login_failed}`, group by `src_ip`, threshold ≥ N within 5 min (spec §8 example).

## Directory Structure

```
/
├── docker-compose.yml          # Appliance: postgres, redis, backend, frontend, nginx, certs-init
├── .env.example                # All env vars with safe defaults
├── Makefile                    # up/down/ps/logs/test/certs/init/retention/send-syslog/send-sample
├── backend/
│   ├── main.py                 # FastAPI app + lifespan + seed users
│   ├── config.py               # Pydantic settings
│   ├── rate_limit.py           # slowapi limiter
│   ├── auth/jwt.py             # JWT issue/verify, get_current_user, require_admin
│   ├── models/schemas.py       # Pydantic request/response models
│   ├── normalizer/core.py      # normalize_log() — source dispatch
│   ├── routers/
│   │   ├── auth.py             # /auth/login, /auth/logout, /auth/me
│   │   ├── ingest.py           # /ingest, /ingest/batch (+ syslog listener)
│   │   ├── logs.py             # /logs, /logs/facets, /logs/stats
│   │   ├── alerts.py           # /alerts, /alerts/{id}, /alerts/triggered, ...
│   │   ├── users.py            # /users CRUD (Admin)
│   │   └── tenants.py          # /tenants CRUD (Admin)
│   ├── services/
│   │   ├── alert_engine.py     # Brute-force detection + custom rule eval
│   │   └── enrichment.py       # GeoIP + reverse DNS + Redis cache
│   ├── storage/database.py     # SQLAlchemy async models, get_db, init_db
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── src/App.jsx             # Routes + auth guard + cookie-based session
│   ├── src/pages/
│   │   ├── Login.jsx
│   │   ├── Dashboard.jsx       # Top-N, timeline, severity, by-source
│   │   ├── LogSearch.jsx       # Filters + pagination + full-text
│   │   ├── AlertRules.jsx      # CRUD alert rules (Delete cascades to triggered_alerts + confirmation modal)
│   │   ├── AlertTriggered.jsx  # Triggered alerts + acknowledge
│   │   └── UserManagement.jsx  # Admin: users CRUD
│   ├── src/components/Layout.jsx
│   ├── src/services/api.js     # Axios instance w/ 401 interceptor + cookie auth
│   ├── src/styles/main.css
│   ├── Dockerfile
│   ├── nginx.conf              # Frontend container nginx (port 80)
│   └── package.json
├── ingest/
│   ├── normalizers/            # Standalone normalizers per source
│   │   ├── syslog_normalizer.py
│   │   ├── api_normalizer.py
│   │   ├── aws_normalizer.py
│   │   ├── m365_normalizer.py
│   │   ├── ad_normalizer.py
│   │   └── crowdstrike_normalizer.py
│   └── requirements.txt
├── nginx/
│   ├── nginx.conf              # TLS + reverse-proxy + stream block (syslog)
│   └── certs/                  # Self-signed certs (generated by scripts/generate-certs.sh)
├── scripts/
│   ├── init-db.sql             # Source of truth for schema (mounted by postgres)
│   ├── generate-certs.sh       # Self-signed cert generator (idempotent)
│   └── retention.py            # Spec §10: delete logs older than N days
├── samples/                    # Example logs + senders (spec §11)
│   ├── send_syslog.sh
│   ├── post_logs.py
│   ├── sample_firewall.log
│   ├── sample_aws_cloudtrail.json
│   ├── sample_m365.json
│   ├── sample_ad_4625.json
│   └── sample_crowdstrike.json
├── helm/log-management/        # Spec §14 nice-to-have: Helm chart
├── terraform/                  # Spec §14 nice-to-have: IaC
│   ├── main.tf
│   ├── variables.tf
│   ├── terraform.tfvars.example
│   └── modules/{vpc,rds,eks}/
├── tests/                      # pytest — backend unit + integration
└── docs/                       # This folder
    ├── architecture.md         # ← you are here
    ├── setup_appliance.md
    └── setup_saas.md
```

## Data Retention (spec §10)

- Default: 7 days (`DATA_RETENTION_DAYS` in `.env`)
- Mechanism: `scripts/retention.py` — `DELETE FROM logs WHERE timestamp < now() - INTERVAL 'N days'`
- Run modes:
  - One-shot: `make retention` (docker exec backend)
  - Cron: schedule same command daily

## Deployment Modes (spec §9)

| Mode | Bring-up | URL |
|---|---|---|
| Appliance | `make up` (Docker Compose on single host) | `http://localhost` (HTTP) or `https://localhost` after `make certs` |
| SaaS / Cloud | Same Compose on cloud VM + domain + Let's Encrypt | `https://your-domain.com` (HTTPS) |

รายละเอียดเพิ่มเติม: `docs/setup_appliance.md`, `docs/setup_saas.md`

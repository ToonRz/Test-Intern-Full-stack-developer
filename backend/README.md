# Backend API — Log Management System

FastAPI-based backend for the Log Management System

อ้างอิง: `spec.md` (single source of truth สำหรับ schema, endpoints, RBAC)

## Tech Stack

- **FastAPI** + **Uvicorn** (async)
- **SQLAlchemy 2.x async** + **asyncpg** → PostgreSQL 15
- **Pydantic v2** — request/response schemas + settings
- **python-jose** (JWT) + **passlib[bcrypt]** (password hashing)
- **slowapi** — per-IP rate limiting
- **httpx** — outbound calls (enrichment GeoIP/rDNS)
- **Redis** — enrichment cache (GeoIP results, rDNS results)
- **APScheduler / background tasks** — alert evaluation on ingest
- **OpenTelemetry** — optional OTLP export

## Directory Layout

```
backend/
├── main.py                # FastAPI app + lifespan + seed users + syslog listener
├── config.py              # Pydantic settings (reads .env)
├── rate_limit.py          # slowapi Limiter (per-IP)
├── auth/jwt.py            # JWT issue/verify, get_current_user, require_admin
├── models/schemas.py      # Pydantic request/response models
├── normalizer/core.py     # normalize_log() — dispatch by source
├── routers/
│   ├── auth.py            # /auth/login, /auth/logout, /auth/me
│   ├── ingest.py          # /ingest, /ingest/batch (+ syslog UDP/TCP listener)
│   ├── logs.py            # /logs, /logs/facets, /logs/stats
│   ├── alerts.py          # /alerts CRUD + /alerts/triggered + acknowledge
│   ├── users.py           # /users CRUD (Admin)
│   └── tenants.py         # /tenants CRUD (Admin)
├── services/
│   ├── alert_engine.py    # Brute-force detection + custom rule evaluation
│   └── enrichment.py      # GeoIP (MaxMind) + reverse DNS + Redis cache
├── storage/database.py    # SQLAlchemy async models + get_db dependency
├── Dockerfile
└── requirements.txt
```

## API Endpoints

Base prefix: `/api/v1` (ตั้งใน `.env` ผ่าน `API_PREFIX`)

### Authentication (`routers/auth.py`) — spec §5.4

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/auth/login` | — | Login → JWT (in body + HttpOnly cookie). Rate-limited 5/min/IP. |
| `POST` | `/auth/logout` | — | Clear auth cookie (idempotent) |
| `GET`  | `/auth/me` | any | Current user profile |

JWT อยู่ใน `HttpOnly` cookie (`lms_auth`) + body (`access_token`) — browser SPA ใช้ cookie (ไม่ต้องเก็บใน localStorage), CLI/curl ใช้ `Authorization: Bearer <token>`

### Ingest (`routers/ingest.py`) — spec §5.1

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/ingest` | — (open) | Single JSON object **หรือ** array of objects. Normalize → enrich → save → background alert check |
| `POST` | `/ingest/batch` | — (open) | `{source, tenant, files:[{logs:[...]}]}` — file-batch (AWS/M365/AD) |
| UDP `514` | syslog | — | Firewall/Network syslog (RFC3164/5424) |
| TCP `514` | syslog | — | Same, over TCP (LF-delimited + octet-counted framed) |

Ingest endpoints เปิดโดยไม่ต้อง auth (เพื่อให้ collector ส่งได้สะดวก) — rate-limit ผ่าน nginx + slowapi
ดูด้านใน `routers/ingest.py` สำหรับ parse + normalize flow

### Logs / Search (`routers/logs.py`) — spec §5.2

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/logs` | any | Query logs + filters + pagination + full-text |
| `GET` | `/logs/facets` | any | Distinct values สำหรับ populate filter dropdown |
| `GET` | `/logs/stats` | any | Dashboard aggregations: total, timeline, top-N, by-source, by-severity |

Query params ที่รับ: `tenant`, `source`, `event_type`, `action`, `geo_country`, `severity` (list/bucket), `start`, `end`, `q` (full-text), `page`, `size`, `bucket_minutes`, `top_n`
ทุก filter รับได้ทั้ง **repeated param** (`?source=api&source=aws`) และ **CSV** (`?source=api,aws`)

### Alerts (`routers/alerts.py`) — spec §5.3

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/alerts` | any | List alert rules (Viewer เห็นเฉพาะ tenant ตัวเอง + `*`) |
| `POST` | `/alerts` | Admin | Create alert rule |
| `PUT` | `/alerts/{rule_id}` | Admin | Update alert rule |
| `DELETE` | `/alerts/{rule_id}` | Admin | Delete alert rule + cascade ลบ `triggered_alerts` ที่อ้างถึง rule_id นี้ (กัน orphan ที่ retry loop จะหา rule ไม่เจอ) — exposed ใน UI ผ่านปุ่ม Delete + confirmation modal |
| `GET` | `/alerts/triggered` | any | List triggered alerts (filters: tenant/severity/source/acknowledged/start/end) |
| `GET` | `/alerts/triggered/{alert_id}` | any | Alert group detail + all logs in group |
| `POST` | `/alerts/{alert_id}/acknowledge` | any | Mark alert as handled (Viewer ต้องอยู่ tenant ตัวเอง) |

Built-in seeded rule ตอน first boot: **Login Failed Brute-Force** — `event_types=[LogonFailed, app_login_failed]`, group by `src_ip`, threshold ≥ 5 ใน 5 นาที (spec §8)

### Users (`routers/users.py`)

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/users` | Admin | List all users |
| `POST` | `/users` | Admin | Create user |
| `PATCH` | `/users/{user_id}` | Admin | Update user (password/role/tenant/email) |
| `DELETE` | `/users/{user_id}` | Admin | Delete user (ลบ `admin` built-in หรือตัวเองไม่ได้) |

### Tenants (`routers/tenants.py`)

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/tenants` | Admin | List registered tenants (populate dropdown) |
| `POST` | `/tenants` | Admin | Register a new tenant (ไม่สร้าง schema แยก — ใช้ populate dropdown เท่านั้น) |
| `DELETE` | `/tenants/{tenant_id}` | Admin | Remove tenant from registry |

### Health / Metrics

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness — 200 OK |
| `GET` | `/metrics` | Prometheus-format (gated ไว้ใน nginx config สำหรับ internal network) |
| `GET` | `/docs` | OpenAPI Swagger UI (spec §5 — automatic) |

## Authentication & RBAC

- **JWT (HS256)** ใน `HttpOnly` cookie + body response
- Claims: `sub` (username), `role` (`Admin`/`Viewer`), `tenant`, `exp`
- `get_current_user` dependency → load user จาก DB (ใช้ `updated_at` invalidate tokens เก่า)
- `require_admin` dependency → 403 ถ้าไม่ใช่ Admin
- **Viewer** ถูก scope ทุก query ด้วย `tenant == current_user.tenant` ที่ query layer (`routers/logs.py`, `routers/alerts.py`)
- **Admin** ผ่าน `tenant` filter ได้ (รวม `*` = all)

## Normalized Schema

ทุก log ถูก normalize ผ่าน `backend/normalizer/core.py:normalize_log()` เข้า schema กลาง (spec §3) ก่อน save
Enrichment เพิ่ม `geo_country`, `geo_city`, `geo_lat`, `geo_lon`, `rdns_hostname` ลง column จริง (cache ใน Redis)

## Multi-Tenant Isolation

- Field-level: ทุก row มี `tenant` column
- Filter at query time: `WHERE tenant = current_user.tenant` (Viewer) หรือ `WHERE tenant IN (...)` (Admin)
- ไม่มี schema-per-tenant — single `public.logs` table
- Indexes: `(tenant)`, `(tenant, timestamp)` — query เร็วพอสำหรับ 7-day window

## Data Retention

- `scripts/retention.py` — `DELETE FROM logs WHERE timestamp < now() - INTERVAL 'N days'`
- Default `DATA_RETENTION_DAYS=7` (spec §10)
- Run one-shot: `make retention` (docker exec backend python -m scripts.retention)
- Production: cron daily

## Quick Start

```bash
# จาก repo root
make up
# → backend available at http://localhost:8000 (direct) or https://localhost/api/v1 (via nginx)

# หรือ run standalone
cd backend
pip install -r requirements.txt
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

OpenAPI docs: http://localhost:8000/docs

## Default Seed Users

Seeded โดย `backend/main.py:_seed_users()` ตอน first boot (ถ้ายังไม่มีใน DB):

| Username | Password | Role | Tenant |
|---|---|---|---|
| `admin` | `admin123` (หรือ `ADMIN_PASSWORD`) | Admin | `*` (all tenants) |
| `viewer` | `viewer123` (หรือ `VIEWER_PASSWORD`) | Viewer | `demoA` |

⚠️ Production ต้องเปลี่ยนทั้งสองก่อน deploy

## Tests

```bash
make test
# หรือ
cd backend && python -m pytest ../tests/ -v
```

Tests ครอบ:
- `test_auth.py` — login/logout/me, RBAC
- `test_auth_cookie.py` — HttpOnly cookie behavior
- `test_ingest.py` — single + batch ingest + normalization
- `test_alerts.py` — alert rule CRUD + brute-force trigger
- `test_normalizer.py` — per-source normalizer output
- `test_syslog.py` — UDP/TCP syslog listener
- `test_retention.py` — retention script

## Environment Variables

อ่านจาก `.env` (ตาม `.env.example`):

| Var | Required | Default | Notes |
|---|---|---|---|
| `SECRET_KEY` | ✅ | — | ≥32 chars random — boot check fail ถ้าว่าง |
| `DATABASE_URL` | ✅ | `postgresql+asyncpg://...` | asyncpg URL |
| `REDIS_URL` | ✅ | `redis://redis:6379/0` | enrichment cache |
| `API_PREFIX` | — | `/api/v1` | |
| `SYSLOG_HOST` | — | `0.0.0.0` | bind syslog listener |
| `SYSLOG_PORT` | — | `514` | UDP+TCP same port |
| `DATA_RETENTION_DAYS` | — | `7` | spec §10 |
| `GEOIP_DB_PATH` | — | `/var/lib/geoip/GeoLite2-City.mmdb` | MaxMind GeoLite2-City |
| `RATE_LIMIT_PER_MINUTE` | — | `100` | per IP |
| `ALLOWED_ORIGINS` | — | localhost defaults | CORS comma-separated |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | — | `60` | |
| `OTEL_*` | — | — | optional OpenTelemetry |

## Production Notes

- เปลี่ยน default passwords ก่อน deploy
- ใช้ managed Postgres + Redis สำหรับ HA
- ตั้ง `ALLOWED_ORIGINS` ให้ตรง domain จริง
- ตั้ง cron สำหรับ backup + retention
- เปิด TLS ที่ nginx (ดู `docs/setup_saas.md`)

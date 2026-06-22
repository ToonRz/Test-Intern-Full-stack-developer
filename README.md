# Log Management System

ระบบจัดการ log แบบ multi-tenant รองรับการ ingest, normalize, search, alert และ dashboard — ติดตั้งได้ทั้ง **Appliance mode** (Docker Compose บนเครื่องเดียว) และ **SaaS mode** (Cloud + HTTPS)

---

## Features

- **Ingest หลายแหล่ง** — Syslog (UDP/TCP 514), HTTP `POST /ingest`, file batch สำหรับ AWS / M365 / AD / CrowdStrike, plus simulator script
- **Normalized schema** — log ทุกแหล่งถูก map เข้า schema กลางก่อนเก็บ 
- **Enrichment** — GeoIP (MaxMind) + reverse DNS พร้อม Redis cache
- **Search & Dashboard** — Top-N, Timeline, By Source/Severity, filter ตาม tenant/source/time/event
- **Alerting** — built-in **Login Failed Brute-Force** (≥ N ครั้งจาก IP เดียวใน 5 นาที) + custom rules ผ่าน UI
- **AuthN/AuthZ** — JWT ใน HttpOnly cookie, RBAC (`Admin` เห็นทุก tenant / `Viewer` เห็นเฉพาะ tenant ตนเอง)
- **Data retention** — ลบ log ที่เกิน 7 วัน (configurable ผ่าน `DATA_RETENTION_DAYS`)
- **Deployment** — Docker Compose (appliance) + Helm chart + Terraform IaC สำหรับ cloud
- **TLS** — self-signed certs สำหรับ appliance, Let's Encrypt สำหรับ SaaS

---

## Quick Start (Appliance Mode)

ต้องการแค่ Docker + Docker Compose + Make

```bash
# 1. clone & setup env
cp .env.example .env
openssl rand -hex 32 | xargs -I {} sed -i '' 's/^SECRET_KEY=.*/SECRET_KEY={}/' .env  # macOS
# หรือ Linux: sed -i "s/^SECRET_KEY=.*/SECRET_KEY=$(openssl rand -hex 32)/" .env

# 2. start ทุกอย่าง
make up
```

หลัง `make up` เสร็จ:

| Service | URL | Notes |
|---|---|---|
| Frontend (Dashboard) | http://localhost:3000 | React SPA |
| Backend API | http://localhost:8000 | FastAPI, docs ที่ `/docs` |
| HTTPS (nginx) | https://localhost | self-signed cert |
| Syslog UDP | udp://localhost:514 | RFC3164/5424 |
| Syslog TCP | tcp://localhost:514 | LF-delimited + octet-counted framed |

**Login ครั้งแรก** (seeded ตอน first boot):

| Username | Password | Role | Tenant |
|---|---|---|---|
| `admin` | `admin123` | Admin | `*` (all) |
| `viewer` | `viewer123` | Viewer | `demoA` |

> เปลี่ยน password ทั้งสองทันทีก่อน production deploy (override ผ่าน `ADMIN_PASSWORD` / `VIEWER_PASSWORD` ใน `.env`)

**ส่ง log ทดสอบ:**

```bash
make send-syslog          # ยิง syslog 1 บรรทัดเข้า localhost:514
make send-sample          # ยิง HTTP POST เข้า /ingest
python samples/post_logs.py http://localhost:8000/api/v1/ingest --loop   # continuous traffic
```

---

## Project Structure

```
.
├── docker-compose.yml          # Appliance stack: postgres, redis, backend, frontend, nginx
├── Makefile                    # up/down/test/certs/retention/send-syslog/send-sample
├── .env.example                # ค่า env ทั้งหมดที่ต้องตั้ง
│
├── backend/                    # FastAPI + SQLAlchemy async + asyncpg
│   ├── main.py
│   ├── routers/                # auth, ingest, logs, alerts, users, tenants
│   ├── normalizer/             # dispatch → ingest/normalizers/*
│   ├── services/               # alert_engine, enrichment (GeoIP+rDNS)
│   ├── auth/                   # JWT issue/verify, RBAC deps
│   └── storage/                # SQLAlchemy async models
│
├── frontend/                   # React 18 + Vite + Recharts + react-router
│   └── src/pages/              # Dashboard, LogSearch, AlertRules, AlertTriggered, UserManagement
│
├── ingest/                     # Standalone normalizers (per source)
│   └── normalizers/            # syslog, api, aws, m365, ad, crowdstrike
│
├── nginx/                      # TLS termination + reverse-proxy + stream block (syslog)
├── scripts/                    # init-db.sql, generate-certs.sh, retention.py
├── samples/                    # ตัวอย่าง log + senders (send_syslog.sh, post_logs.py)
│
├── docs/
│   ├── architecture.md         # Data flow + tenant model + component diagram
│   ├── setup_appliance.md      # ขั้นตอนติดตั้ง appliance แบบละเอียด
│   ├── setup_saas.md           # ขั้นตอน deploy SaaS + Let's Encrypt
│   └── observability-dashboard.md
│
├── helm/log-management/        # Helm chart (cloud / k8s)
├── terraform/                  # IaC: VPC + RDS + EKS modules
├── tests/                      # pytest — auth, ingest, alerts, normalizer, syslog, retention
│
└── _internal/                  # spec, demo video script, action plan, code review
```

---

## Deployment Modes

### Appliance (default)
Single host / VM — Ubuntu 22.04+, 4 vCPU, 8 GB RAM, 40 GB disk
รัน: `make up` → เปิด port `80`, `443`, `514`
ดูขั้นตอนเต็ม: [`docs/setup_appliance.md`](docs/setup_appliance.md)

### SaaS / Cloud
Cloud VM + domain + Let's Encrypt (หรือ self-signed สำหรับทดสอบ)
Helm chart สำหรับ k8s: `helm/log-management/`
Terraform modules (VPC + RDS + EKS): `terraform/`
ดูขั้นตอนเต็ม: [`docs/setup_saas.md`](docs/setup_saas.md)

---

## API Endpoints (Base: `/api/v1`)

| Group | Endpoints | Auth |
|---|---|---|
| **Auth** | `POST /auth/login`, `POST /auth/logout`, `GET /auth/me` | login เปิด, อื่น ๆ ต้อง auth |
| **Ingest** | `POST /ingest`, `POST /ingest/batch`, UDP/TCP `:514` | open (rate-limited ที่ nginx + slowapi) |
| **Logs** | `GET /logs`, `GET /logs/facets`, `GET /logs/stats` | any |
| **Alerts** | `GET/POST/PUT/DELETE /alerts`, `GET /alerts/triggered`, `POST /alerts/{id}/acknowledge` | any (CRUD = Admin); `DELETE` ลบ rule + triggered_alerts ที่อ้างถึง (cascade) |
| **Users** | `GET/POST/PATCH/DELETE /users` | Admin |
| **Tenants** | `GET/POST/DELETE /tenants` | Admin |
| **Ops** | `GET /health`, `GET /metrics`, `GET /docs` (OpenAPI) | varies |

ดู schema ครบทุก endpoint ที่ http://localhost:8000/docs หลัง start

---

## Tech Stack

| Layer | Technology | Why |
|---|---|---|
| Backend | FastAPI + Uvicorn (async) | Auto OpenAPI, async fits asyncpg |
| Storage | PostgreSQL 15 + JSONB + GIN | ACID, JSON ops, partition-friendly |
| Cache | Redis 7 | enrichment (GeoIP / rDNS) cache |
| Frontend | React 18 + Vite + Recharts | Component model, declarative charts |
| Auth | JWT (HS256) ใน HttpOnly cookie | กัน XSS exfiltrate จาก localStorage |
| Enrichment | MaxMind GeoLite2 + reverse DNS | spec §14 nice-to-have |
| Ingest | Python async syslog listener (embedded) | same codebase, simpler ops |
| TLS | Self-signed (appliance) / Let's Encrypt (SaaS) | อนุญาตทั้งสองแบบ |
| Observability | OpenTelemetry + `/metrics` + `/health` | nice-to-have |
| IaC | Helm chart + Terraform | nice-to-have |

---

## Development

### Run tests

```bash
make test                  # backend pytest (unit + integration)
make test-frontend         # frontend Vitest
```

Tests ครอบ: `test_auth.py`, `test_auth_cookie.py`, `test_ingest.py`, `test_alerts.py`, `test_normalizer.py`, `test_syslog.py`, `test_retention.py`

### Run retention one-shot

```bash
make retention             # ลบ log ที่เกิน DATA_RETENTION_DAYS (default 7)
```

สำหรับ production ตั้ง cron:

```cron
0 2 * * * cd /path/to/repo && docker compose exec -T backend python -m scripts.retention
```

### Reset ทั้ง stack (ลบ volume)

```bash
make clean                 # docker compose down -v
```

---

## Documentation

- [Architecture & data flow](docs/architecture.md)
- [Appliance setup](docs/setup_appliance.md)
- [SaaS setup](docs/setup_saas.md)
- [Backend API](backend/README.md)
- [Frontend](frontend/README.md)
- [Ingest / Normalizers](ingest/README.md)

---

## Environment Variables

ค่าที่ **ต้องตั้ง** ก่อน `make up`:

| Var | Required | Notes |
|---|---|---|
| `SECRET_KEY` | ✅ | ≥32 chars random — `openssl rand -hex 32` |
| `DATABASE_URL` | — (มี default) | `postgresql+asyncpg://...` |
| `ADMIN_PASSWORD` | — | override seed `admin` password |
| `VIEWER_PASSWORD` | — | override seed `viewer` password |
| `DATA_RETENTION_DAYS` | — | default `7` |
| `GEOIP_DB_PATH` | — | path ถึง MaxMind GeoLite2-City.mmdb |
| `ALLOWED_ORIGINS` | — | CORS comma-separated |

ดูทั้งหมด: [`.env.example`](.env.example)

---

## License

Internal — no public license declared.

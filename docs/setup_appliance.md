# Setup Guide — Appliance Mode

## Overview

Appliance mode รันทุกอย่างบนเครื่องเดียว / VM เดียว ด้วย Docker Compose
ทั้ง ingest, backend API, frontend, nginx (TLS), postgres, redis อยู่ใน stack เดียวกัน

อ้างอิง: `spec.md` §9.1

## Requirements

- Ubuntu 22.04+ (แนะนำ) หรือ OS ที่รองรับ Docker
- Minimum spec (spec §9.1):
  - 4 vCPU
  - 8 GB RAM
  - 40 GB Disk
- Docker Engine 24+ และ Docker Compose v2
- Ports ที่ต้องเปิด: `80`, `443`, `514/udp`, `514/tcp`, `3000` (frontend dev), `8000` (backend dev), `5432` (postgres), `6379` (redis)

## Quick Start

### 1. Clone Repository

```bash
git clone <repository-url>
cd Test-Intern-Full-stack-developer
```

### 2. ตั้งค่า Environment

```bash
cp .env.example .env
# Generate strong SECRET_KEY (จำเป็น — docker-compose จะ fail ถ้า SECRET_KEY ว่าง)
echo "SECRET_KEY=$(openssl rand -hex 32)" >> .env

# แก้ค่าอื่นตามต้องการ (DATA_RETENTION_DAYS, ADMIN_PASSWORD, ...)
```

`.env` ที่จำเป็นต้องตั้ง:
- `SECRET_KEY` — ต้องตั้ง (≥32 chars random)
- `DATA_RETENTION_DAYS` — default `7` (spec §10)
- `ADMIN_PASSWORD` / `VIEWER_PASSWORD` — default seed มี `admin123` / `viewer123` สำหรับ dev เท่านั้น

### 3. Start Services

```bash
# ใช้ Makefile (แนะนำ — generate self-signed certs ก่อน แล้วค่อย up)
make up

# หรือ docker compose ตรง ๆ
docker compose up -d --build
```

`make up` จะเรียงงานเป็น:
1. `make certs` — สร้าง self-signed TLS certs ที่ `nginx/certs/` (idempotent)
2. `docker compose up -d --build` — build + start ทุก service
3. รอ healthcheck ผ่าน

### 4. Verify Services

```bash
make ps       # ดู container status
make logs     # tail logs ทุก service
```

Services ที่ควรขึ้น (6 containers):

| Container | Image | Port |
|---|---|---|
| `app-postgres-1` | `postgres:15-alpine` | `5432` |
| `app-redis-1` | `redis:7-alpine` | `6379` |
| `app-backend-1` | `app-backend` | `8000`, `514/udp`, `514/tcp` |
| `app-frontend-1` | `app-frontend` | `3000` (map to container `:80`) |
| `app-nginx-1` | `nginx:alpine` | `80`, `443` |
| `app-certs-init-1` | `alpine:3.19` (one-shot) | — |

## Access URLs

| Service | URL | Auth |
|---|---|---|
| Frontend (via nginx, HTTPS) | https://localhost | login required |
| Frontend (direct, dev) | http://localhost:3000 | login required |
| Backend API (via nginx) | https://localhost/api/v1 | JWT cookie |
| Backend API (direct) | http://localhost:8000/api/v1 | JWT cookie |
| OpenAPI docs | http://localhost:8000/docs | — |
| Backend health | http://localhost:8000/health | — |
| Syslog | udp://localhost:514, tcp://localhost:514 | — |

หมายเหตุ: browser จะเตือน "self-signed certificate" — ใน dev ให้กด Proceed ได้ (spec §9.2 อนุญาต self-signed ถ้ามี docs)

## Test Ingestion

### Syslog (Firewall/Network)

```bash
# ใช้ sample script
make send-syslog

# หรือส่งด้วย netcat ตรง ๆ
echo '<134>Aug 20 12:44:56 fw01 vendor=demo product=ngfw action=deny src=10.0.1.10 dst=8.8.8.8 spt=5353 dpt=53 proto=udp msg="DNS blocked" policy=Block-DNS' | nc -u -w1 localhost 514
```

### HTTP POST (single log)

```bash
make send-sample

# หรือ curl ตรง ๆ
curl -X POST http://localhost:8000/api/v1/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "tenant": "demoA",
    "source": "api",
    "event_type": "app_login_failed",
    "user": "alice",
    "ip": "203.0.113.7",
    "reason": "wrong_password"
  }'
```

### Batch file upload (AWS / M365 / AD)

```bash
# ใช้ sample ใน samples/
curl -X POST http://localhost:8000/api/v1/ingest/batch \
  -H "Content-Type: application/json" \
  -d "$(cat samples/sample_aws_cloudtrail.json | jq '{source: "aws", tenant: "demoB", files: [{logs: .}]}')"
```

หรือ ingest sample ทั้งหมดผ่าน script `samples/post_logs.py`

## Test Dashboard

1. เปิด https://localhost (ยอมรับ self-signed cert warning)
2. Login: `admin` / `admin123`
3. ไปที่ **Dashboard** — เห็น Top N (src_ip/user/event_type), Timeline, By Source, By Severity
4. ไปที่ **Log Search** — ลอง filter (tenant, source, severity bucket, time range, full-text)
5. ไปที่ **Alert Rules** — ดู rule seeded + สร้าง/แก้ rule ใหม่
6. ไปที่ **Triggered** — ดู alerts ที่ trigger แล้ว กด acknowledge ได้
7. (Admin) ไปที่ **Users** — จัดการ users/tenants

## Default Seed Users

Seed จาก `backend/main.py:_seed_users()` ตอน first boot (ถ้ายังไม่มีใน DB):

| Username | Password | Role | Tenant | Notes |
|---|---|---|---|---|
| `admin` | `admin123` (หรือ `ADMIN_PASSWORD`) | Admin | `*` (all tenants) | Built-in — ลบไม่ได้ |
| `viewer` | `viewer123` (หรือ `VIEWER_PASSWORD`) | Viewer | `demoA` | Demo tenant สำหรับทดสอบ RBAC |

⚠️ ใน production **ต้องเปลี่ยน password ทั้งสอง** ก่อน deploy

## Useful Commands

```bash
make up          # start stack (auto-generate certs)
make down        # stop stack (เก็บ data volume)
make restart     # down + up
make ps          # container status
make logs        # tail logs ทุก service
make certs       # regenerate self-signed certs ที่ nginx/certs/
make init        # re-apply scripts/init-db.sql เข้า postgres
make test        # pytest (backend)
make test-frontend  # vitest (frontend)
make retention   # run scripts/retention.py ครั้งเดียว (spec §10)
make send-syslog # ส่ง sample syslog เข้า localhost:514
make send-sample # ส่ง sample HTTP logs เข้า /ingest
make clean       # down + ลบ volumes (ลบ data ทั้งหมด)
make shell-backend   # bash ใน backend container
make shell-postgres  # psql ใน postgres container
```

## Troubleshooting

### Services won't start

```bash
docker ps                       # ดู container ที่รัน
docker compose logs             # ดู error
docker compose logs backend     # ดูเฉพาะ backend
```

Common causes:
- `SECRET_KEY` ไม่ได้ตั้งใน `.env` — docker-compose จะ fail ด้วย error "SECRET_KEY must be set"
- Port 514 ติด — `sudo lsof -i :514` แล้ว kill process หรือเปลี่ยน SYSLOG_PORT
- Port 80/443 ติด — `sudo lsof -i :80` (มักเป็น apache/nginx เก่า)

### Backend health fails

```bash
curl -fsS http://localhost:8000/health
docker compose logs backend
```

### Database connection issues

```bash
docker compose exec postgres pg_isready -U postgres
make init       # apply scripts/init-db.sql ใหม่
```

### Syslog ไม่เข้า

```bash
# ตรวจว่า port 514 listen
sudo lsof -iUDP:514
sudo lsof -iTCP:514

# ลองส่งจาก host
logger -n localhost -P 514 "test"
echo "test" | nc -u -w1 localhost 514

# ดู log backend (ควรเห็น parse)
docker compose logs -f backend | grep -i syslog
```

### HTTPS cert warning

ใน browser คลิก "Advanced" → "Proceed to localhost" — เป็น self-signed cert ปกติ (spec §9.2 อนุญาต)
ถ้าต้องการ cert จริง ดู `docs/setup_saas.md` สำหรับ Let's Encrypt

### Frontend เปล่า / 401

- Clear cookie + login ใหม่
- ตรวจว่า backend `/auth/me` ตอบ 200:
  ```bash
  curl -i http://localhost:8000/api/v1/auth/me
  ```
- ดู browser console สำหรับ CORS error

## Ports Summary

| Port | Service | Notes |
|---|---|---|
| 80 | nginx (HTTP→HTTPS redirect) | |
| 443 | nginx (HTTPS termination) | self-signed ใน appliance mode |
| 3000 | frontend (direct, dev) | nginx proxy ใช้แทนได้ |
| 514/udp | syslog UDP | spec §5.1 |
| 514/tcp | syslog TCP | spec §5.1 |
| 5432 | postgres | spec §4 storage |
| 6379 | redis | enrichment cache |
| 8000 | backend API + OpenAPI docs | |

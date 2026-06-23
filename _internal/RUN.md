# Run Guide - Daily Usage

คู่มือ run project ในแต่ละวัน หลังจาก clone ครั้งแรกเสร็จแล้ว (ดู [setup_appliance.md](setup_appliance.md) สำหรับ install ครั้งแรก)

## Quick Start (5 คำสั่ง)

```bash
# 1. เริ่มทุก service
make up

# 2. รอ ~30 วินาที แล้วเช็คว่า healthy ครบ
docker compose ps
# ทุก service ต้องขึ้น STATUS = "Up ... (healthy)"

# 3. ถ้า DB ว่าง ใส่ข้อมูลตัวอย่างจาก spec
make send-sample

# 4. เปิดเว็บ
#    HTTP:  http://localhost:3000
#    HTTPS: https://localhost   (self-signed → browser เตือน กด proceed)

# 5. login
#    admin  / admin123   → เห็นทุก tenant
#    viewer / viewer123  → เห็นเฉพาะ tenant demoA
```

---

## Service URLs

| Service | URL | Notes |
|---|---|---|
| Frontend (UI) | http://localhost:3000 | Main app |
| Frontend (HTTPS) | https://localhost | ผ่าน nginx + self-signed cert |
| Backend API | http://localhost:8000 | FastAPI |
| API docs | http://localhost:8000/docs | Swagger UI |
| Syslog UDP | udp://localhost:514 | RFC 5424 |
| Syslog TCP | tcp://localhost:514 | RFC 5424 |
| Postgres | `localhost:5432` | user `postgres` / pass `postgres` / db `logs` |
| Redis | `localhost:6379` | rate limit + cache |

---

## Default Users

สร้างตอน `make init` (รันครั้งแรกตอน postgres init)

| Username | Password | Role | Tenant |
|---|---|---|---|
| `admin` | `admin123` | Admin | `*` (เห็นทุก tenant) |
| `viewer` | `viewer123` | Viewer | `demoA` (เห็นเฉพาะ demoA) |

เปลี่ยนรหัสได้ที่ `POST /api/v1/users` (ต้อง login เป็น Admin)

---

## Common Commands

| คำสั่ง | ทำอะไร |
|---|---|
| `make up` | start + build image + สร้าง cert |
| `make down` | หยุด containers (volume ไม่หาย → data ยังอยู่) |
| `make restart` | `down` แล้ว `up` ใหม่ |
| `make ps` | ดูสถานะ containers |
| `make logs` | tail log ทุก service |
| `make logs backend` | tail log service เดียว |
| `make clean` | หยุด + **ลบ volumes** (data หาย! ใช้ตอนอยาก reset) |
| `make test` | รัน backend pytest (~88 tests) |
| `make test-frontend` | รัน vitest |
| `make build` | build images อย่างเดียว ไม่ start |
| `make shell-backend` | shell เข้า backend container |
| `make shell-postgres` | shell เข้า postgres container |
| `make send-sample` | ยิง sample log ตาม spec §4 ทุก source เข้า `/ingest` |
| `make send-syslog` | ยิง syslog message เข้า port 514 |
| `make docs` | serve docs ผ่าน mkdocs |

---

## เมื่อไหร่ต้องใช้คำสั่งไหน

**เปิดทำงานเช้า** → `make up` แล้ว `make send-sample` ถ้าอยากเห็น dashboard

**ปิดเย็น** → `make down` (data ยังอยู่ เปิดใหม่ได้เลย)

**ต้องการ reset ทั้งหมด (data หายหมด)** → `make clean` แล้ว `make up` แล้ว `make init` แล้ว `make send-sample`

**แก้ code แล้วอยากเห็นผล** →
- backend: `docker compose restart backend` (ไม่ใช่ `up -d` เฉยๆ เพราะไม่ restart container ที่ up อยู่)
- frontend: `docker compose build --no-cache frontend && docker compose up -d frontend`
- หรือ `make restart` ทำให้ทั้งคู่

**run tests หลังแก้ code** → `make test` แล้ว `make test-frontend`

---

## Troubleshooting - "Log ไม่ขึ้น"

อาการ: dashboard โล่ง, LogSearch ไม่มี row, facets ตอบ array ว่าง

เช็คตามลำดับนี้:

### 1. Service healthy ไหม

```bash
docker compose ps
```

ทุก service ต้องขึ้น `Up X minutes (healthy)` ถ้ามีตัวไหน `Up ... (unhealthy)` หรือ `Restarting`:

```bash
make logs backend      # หรือชื่อ service ที่มีปัญหา
```

ดู error แล้วแก้ตามนั้น

### 2. DB มีข้อมูลไหม

```bash
docker compose exec -T postgres psql -U postgres -d logs \
  -c "SELECT COUNT(*), MIN(\"timestamp\"), MAX(\"timestamp\") FROM logs;"
```

- ถ้า `count = 0` → DB ว่าง รัน `make send-sample` ใส่ข้อมูล
- ถ้า `count > 0` แต่ UI โล่ง → ไปข้อ 3

### 3. API ตอบ 200 ไหม

login ก่อน แล้วลองดึง logs:

```bash
# login (เก็บ cookie)
curl -s -c /tmp/c.txt -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"viewer","password":"viewer123"}'

# ดึง logs
curl -s -b /tmp/c.txt "http://localhost:8000/api/v1/logs?limit=3" | python3 -m json.tool
```

- ถ้า `"total": 0` → DB ว่างจริง (ย้อนกลับไปข้อ 2)
- ถ้า 401 → cookie ไม่ถูกส่ง หรือ user role ผิด
- ถ้า 500 → ดู `make logs backend` หา error

### 4. Frontend bundle ตรงกับ source ไหม

เคยเจอ: แก้ code แล้ว `docker compose up -d frontend` แต่ bundle ใน container เป็นของเก่า (Vite ใช้ content hash เช่น `index-DAuHEU5R.js` — ถ้า hash ใน browser ไม่ตรงกับที่ build ล่าสุด จะรัน code เก่า)

ตรวจ:

```bash
# hash ใน source (built file)
ls frontend/dist/assets/

# hash ใน container
docker compose exec -T frontend ls /usr/share/nginx/html/assets/
```

ถ้าไม่ตรงกัน:

```bash
docker compose build --no-cache frontend
docker compose up -d frontend
```

แล้ว hard-refresh browser (Cmd+Shift+R) เพื่อ clear cache

### 5. Browser cache

ถ้าแก้ทุกอย่างแล้วยังเห็นอาการเดิม:

- เปิด DevTools → Network → ติ๊ก "Disable cache"
- หรือ hard refresh: `Cmd+Shift+R` (macOS) / `Ctrl+Shift+R` (Windows/Linux)
- หรือเปิด Incognito/Private window

---

## Data Retention

`DATA_RETENTION_DAYS=7` (default) — backend มี background loop ลบ log ที่ `timestamp < now − 7d` ทุก 1 ชั่วโมง ตาม spec §10

**sample logs ไม่โดนลบ** เพราะ `samples/post_logs.py` ใช้ `datetime.now(timezone.utc)` เป็น `@timestamp` เสมอ

ถ้าอยากปิด retention ชั่วคราว (เช่น debug):

```bash
# .env
DATA_RETENTION_DAYS=365
```

แล้ว `docker compose restart backend`

ถ้าอยากลบ retention ออกจาก startup loop ดูที่ `backend/main.py:_retention_loop`

รัน retention แบบ manual (เช่นตอนอยากเช็คว่ามีอะไรจะถูกลบ):

```bash
make retention
# หรือ
docker compose exec backend python scripts/retention.py --days 7
```

---

## ใช้งานกับ external data

นอกจาก `make send-sample` ยังมี 2 วิธีหลักส่ง log เข้า:

**HTTP POST (spec §4.3)**:
```bash
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

**Syslog UDP (spec §4.1)**:
```bash
echo '<14>1 2026-06-19T10:00:00Z host1 myapp - - - login failed user=alice' | \
  nc -u -w1 localhost 514
```

**JSON Batch**:
```bash
curl -X POST http://localhost:8000/api/v1/ingest/batch \
  -H "Content-Type: application/json" \
  -d '[{"tenant":"demoA","source":"api","event_type":"x"}, ...]'
```

รายละเอียด spec แต่ละ source (api, crowdstrike, aws, m365, ad, firewall) ดูที่ `spec.md` section 4

---

## โครงสร้าง project (quick reference)

```
.
├── Makefile                    # คำสั่งหลักทั้งหมด
├── docker-compose.yml          # 5 services: backend, frontend, nginx, postgres, redis
├── backend/                    # FastAPI
│   ├── main.py                 # app + lifespan + retention loop
│   ├── routers/                # auth, ingest, logs, alerts, users, tenants
│   ├── normalizer/             # schema normalization (spec §3)
│   ├── services/               # alert engine, JWT
│   └── storage/                # SQLAlchemy models
├── frontend/                   # React + Vite
├── ingest/normalizers/         # per-source normalizer (api, ad, m365, aws, crowdstrike, syslog)
├── samples/post_logs.py        # `make send-sample`
├── scripts/retention.py        # `make retention`
├── tests/                      # pytest (~88 tests)
└── docs/
    ├── RUN.md                  # ไฟล์นี้
    ├── architecture.md
    ├── setup_appliance.md
    └── setup_saas.md
```

---

## เอกสารที่เกี่ยวข้อง

- [setup_appliance.md](setup_appliance.md) — install ครั้งแรก
- [setup_saas.md](setup_saas.md) — deploy บน cloud
- [architecture.md](architecture.md) — data flow + tenant model
- [observability-dashboard.md](observability-dashboard.md) — dashboard + alert metrics
- `spec.md` (root) — source of truth สำหรับ schema, API, alert rules, retention

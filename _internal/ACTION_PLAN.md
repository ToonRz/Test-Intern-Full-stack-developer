# Action Plan — Code Review Findings

แผนการแก้ปัญหา 35 ข้อจาก `CODE_REVIEW.md` — จัดเป็น batch ตามความเร่งด่วน พร้อม effort estimate และ dependencies

**อ้างอิง:** `CODE_REVIEW.md`, `SPEC_COMPLIANCE_REVIEW.md`, `spec.md`

---

## Conventions

- **Effort:** XS = <30 นาที · S = 30นาที-2ชม. · M = 2-4 ชม. · L = 4-8 ชม. · XL = >1 วัน
- **Risk:** 🔴 breaking schema/contract · 🟠 behavior change · 🟢 internal only
- **Verify:** ทุก batch ต้องผ่าน `make test` + smoke test ที่ระบุ
- **Files:** ระบุ path ครบทุกไฟล์ที่แตะ

---

## Batch 0 — Smoke Fixes (ทำได้ทันที, ไม่กระทบ contract)

**Effort รวม:** ~30 นาที | **Risk:** 🟢 | **ไม่ต้องทำ PR แยก รวมได้**

| # | รายการ | Effort | ไฟล์ |
|---|---|---|---|
| 9 | ลบ `\|\| true` ออกจาก CI | XS | `.github/workflows/ci.yml:36,44` |
| 10 | `npm uninstall tailwind-merge` | XS | `frontend/package.json` |
| 12 | ลบ `python-syslog-ng` ออกจาก `ingest/requirements.txt` | XS | `ingest/requirements.txt` |
| 11 | เพิ่ม TCP syslog listener ใน nginx | XS | `nginx/nginx.conf` (เพิ่ม block) |
| 15 | ลบ duplicate docstring + dead `import bcrypt` ใน `users.py` | XS | `backend/routers/users.py:1-4` |
| 19 | ลบ dead `if formData.tenant === '*'` block | XS | `frontend/src/pages/UserManagement.jsx:69-72` |

**Verify:**
```bash
make test                                    # 37/37 ต้องผ่าน
docker compose up -d && make smoke           # ingest ใช้งานได้
curl -X POST http://localhost:514 -d '...'   # TCP syslog forward ผ่าน nginx
```

---

## Batch 1 — Critical #1 + Critical #3 (quick wins ที่ critical จริง)

**Effort:** ~2 ชม. | **Risk:** 🟢 internal · 🔴 contract ไม่เปลี่ยน
**ทำทั้งคู่ใน PR เดียว เพราะทั้งคู่เป็น session/auth hardening**

### 1A. enrich_and_save session rollback
- **ไฟล์:** `backend/routers/ingest.py:79-94`
- **แก้:** เพิ่ม `await db.rollback()` ใน except block ก่อน log
- **Effort:** XS (1 บรรทัด)
- **Test ใหม่:** `tests/test_enrichment.py::test_redis_failure_continues_batch`
  - mock `EnrichmentService.enrich` ให้ raise
  - POST batch 7 logs
  - assert: ไม่มี `PendingRollbackError`, log #2-7 ถูก save สำเร็จ

### 1B. acknowledge tenant check
- **ไฟล์:** `backend/routers/alerts.py:217-228`, `backend/services/alert_engine.py:264-273`
- **แก้:** เพิ่ม `if viewer.tenant != alert.tenant: raise HTTPException(403)`
- **Effort:** XS
- **Test:** `tests/test_alerts.py::test_viewer_cannot_ack_cross_tenant_alert`

**Verify:**
```bash
pytest tests/test_enrichment.py tests/test_alerts.py -v
# Smoke: stop redis, POST batch → log ถูก save ครบทุกตัว
docker compose stop redis
curl -X POST http://localhost:8000/ingest -H "Authorization: Bearer $ADMIN" \
  -d '[{"source":"api",...},{"source":"api",...},...]'
docker compose start redis
```

---

## Batch 2 — Critical #2 + High #6 (alert tenant scoping + telemetry lifecycle)

**Effort:** ~4-6 ชม. | **Risk:** 🔴 DB schema migration
**ทำเป็น PR เดียว เพราะเกี่ยวกับ schema change ต้องประสานกัน**

### 2A. AlertRule tenant column
- **ไฟล์:**
  - `backend/storage/database.py` — เพิ่ม `tenant = Column(String, nullable=False, index=True)` ใน `AlertRuleDB`
  - `backend/services/alert_engine.py:46-55` — filter `AlertRuleDB.tenant == log.tenant`
  - `backend/services/alert_engine.py:264-273` — acknowledge ใช้ tenant check ที่ทำใน Batch 1B
  - `backend/main.py:233` — `_seed_default_alert_rule` ใช้ `tenant="*"` (global)
  - `backend/routers/alerts.py:43` — POST rule ต้อง set tenant (Viewer = บังคับ own tenant, Admin = ระบุเอง)

- **Migration:** ใช้ `Base.metadata.create_all` แทน manual SQL
  - เพิ่ม column `tenant` default `"*"` ให้ rules เดิม (backward-compat: `*` = match all)
  - ถ้าไม่อยากใช้ `*` ให้ทำ Alembic migration — แต่ `init_db()` ใน `main.py` ใช้ create_all อยู่แล้ว ขอเปลี่ยน behavior: ALTER TABLE ถ้า column ขาด

- **Effort:** M (3-4 ชม. รวม test)

- **Test ใหม่:** `tests/test_alert_engine.py`
  - `test_alert_only_triggers_for_same_tenant`
  - `test_global_rule_triggers_for_all_tenants` (tenant="*")
  - `test_admin_can_create_rule_for_other_tenant`
  - `test_viewer_can_only_create_rule_for_own_tenant`

### 2B. setup_telemetry ใน lifespan
- **ไฟล์:** `backend/main.py:159-188`
- **แก้:** ลบ module-level call → เรียกใน `lifespan` startup
- **Effort:** XS
- **Test:** existing `test_main.py` ต้อง import ได้ไม่ crash

**Verify:**
```bash
pytest tests/test_alert_engine.py tests/test_main.py -v
make test

# Smoke: ingest log tenant A → alert ของ tenant B ไม่ trigger
# Smoke: ingest log tenant A → alert tenant="*" trigger ข้าม tenant ได้
```

---

## Batch 3 — Critical #4 + Critical #5 (auth hardening)

**Effort:** ~6-8 ชม. | **Risk:** 🔴 breaking user-facing auth flow
**ทำเป็น PR เดียว เพราะ JWT changes ต้องประสานกัน**

### 3A. /auth/login rate limit
- **ไฟล์:** `backend/routers/auth.py:11-21`, `backend/main.py:40`
- **แก้:**
  ```python
  from slowapi.errors import RateLimitExceeded
  from backend.main import limiter

  @router.post("/login")
  @limiter.limit("5/minute")
  async def login(request: Request, data: LoginRequest, ...):
  ```
- **Effort:** S (30 นาที รวม test)
- **Test:** `tests/test_auth.py::test_login_rate_limit_5_per_minute`

### 3B. JWT short-lived + re-validation

มี 3 ทางเลือก (เลือก 1 — แนะนำข้อแรก):

**Option A (recommended): Short-lived access + refresh token**
- access token: 5 นาที
- refresh token: 7 วัน, เก็บใน DB (revocable)
- endpoint ใหม่: `POST /auth/refresh`
- logout = revoke refresh token
- **Effort:** L (5-6 ชม. รวม frontend token refresh interceptor)
- **Breaking:** Frontend ต้องอัพเดต `api.js` ให้ handle 401 → refresh → retry

**Option B: iat vs updated_at check**
- เพิ่ม `updated_at = Column(DateTime)` ใน `UserDB`
- `get_current_user`: `if payload["iat"] < user.updated_at: raise 401`
- **Effort:** M (3-4 ชม.)
- **Trade-off:** Logout ทุก user เมื่อใดก็ตามที่ admin แก้ role/tenant (ไม่ granular)

**Option C: Blacklist table**
- `RevokedTokenDB` table (jti, expires_at)
- logout = insert row
- `get_current_user`: check blacklist
- **Effort:** M
- **Trade-off:** ต้อง query DB ทุก request (cache ได้)

**แนะนำ Option A** — เพราะเป็น standard, scalable, และ frontend interceptor ทำครั้งเดียว reuse ได้

**Verify:**
```bash
# Brute force test
for i in {1..10}; do curl -X POST .../auth/login -d '{...}'; done
# → 6 calls return 429

# Privilege escalation test
# 1. Login user_a as Admin
# 2. Admin demote user_a to Viewer
# 3. user_a ใช้ token เดิม → ใหม่ต้อง reject ภายใน 5 นาที
```

---

## Batch 4 — High #7, #8 (syslog + redis resilience)

**Effort:** ~4 ชม. | **Risk:** 🟠 behavior change

### 4A. RFC6587 octet-counted TCP syslog
- **ไฟล์:** `backend/main.py:354-381`
- **แก้:** Implement octet-counted parsing ก่อน LF fallback
  ```python
  # ตรวจ prefix เป็น digits + space → parse length → read N bytes
  # ถ้าไม่ใช่ → fallback LF-delimited
  ```
- **Effort:** M (3-4 ชม.)
- **Test:** `tests/test_syslog.py`
  - `test_octet_counted_tcp_parsing`
  - `test_lf_delimited_tcp_legacy`
  - `test_garbage_prefix_rejected`
- **ถ้าไม่อยาก implement:** แค่แก้ docstring ให้ตรงกับ code (S)

### 4B. RedisCache reset on connection failure
- **ไฟล์:** `backend/services/enrichment.py:46-57, 80-95`
- **แก้:** `except redis.ConnectionError: RedisCache._instance = None; raise`
- **Effort:** XS
- **Test:** mock connection fail → instance reset → retry succeeds

**Verify:**
```bash
# RFC6587: rsyslog -t ส่งแบบ octet-counted → parse ถูก
# RedisCache: stop redis, call enrich, start redis, call enrich → ทำงาน
```

---

## Batch 5 — Medium fixes (refactor + UX)

**Effort:** ~1-2 วัน | **Risk:** 🟠

### 5A. Schema + type fixes (XS-S ต่อข้อ)
- **#13 `_tags` Pydantic v2 drop:** rename เป็น `tags` + alias `_tags` (S, breaking)
- **#14 aws_normalizer cloud=str crash:** type check (XS)
- **#16 UserCreate.tenant default:** `Field(min_length=1)` (XS)
- **#20 Literal["Admin", "Viewer"]** ใน UserCreate/UserUpdate (XS)
- **#30 password bytes validation:** custom validator (S)
- **#31 .env.example SECRET_KEY=""** (XS)
- **#22 SEED_DEMO_USERS default false** (XS, แต่ breaking change สำหรับ dev)

### 5B. UI gaps (S-M ต่อข้อ)
- **#17 AlertRules edit/delete UI** (M, 2-3 ชม.)
- **#18 UserManagement edit UI** (M, 2-3 ชม.)
- **#23 AlertRules custom event type input** (S)
- **#25 Dashboard tenant dropdown** (S, ใช้ `/logs/facets`)
- **#26 401 handler ใช้ navigate** (XS)
- **#28 AlertTriggered auto-refresh** (XS)

### 5C. Refactor (S)
- **#24 _bcrypt_hash ใช้ shared helper** (S)
- **#21 init-db.sql vs SQLAlchemy:** ลบ init-db.sql ใช้ create_all อย่างเดียว หรือใช้ Alembic (M)

---

## Batch 6 — Tests + Docs (ปิด gap ที่ review เจอ)

**Effort:** ~1 วัน | **Risk:** 🟢

### 6A. Unit tests ใหม่
- **#32 tests/test_normalizer.py** — unit test ทั้ง 6 sources (M)
- **#33 tests/test_enrichment.py::test_redis_graceful_degrade** (S)
- **#34 tests/test_syslog.py::test_udp_tcp_listener** (M)
- **#35 tests/test_retention.py::test_8_day_logs_deleted** (S)

### 6B. Docs อัพเดต
- `docs/architecture.md` — อัพเดต flow ถ้า batch 2 เปลี่ยน alert tenant model
- `docs/setup_appliance.md` — เพิ่มหมายเหตุ SECRET_KEY empty
- `README.md` — เพิ่ม troubleshooting section "Redis down = batch ingest still works"

---

## Batch 7 — Low priority (backlog)

ทำเมื่อมีเวลา:
- **#27** Frontend token → httpOnly cookie (L, breaking frontend+backend)
- **#29** JSONB → tsvector full-text search (L, requires DB migration)

---

## Recommended Execution Order

```
Week 1 (M/T/W/Th/F = ~40 ชม.)
├── Day 1 (4 ชม.): Batch 0 + Batch 1    (smoke + 2 critical fixes)
├── Day 2 (6 ชม.): Batch 2               (alert tenant scoping — schema migration)
├── Day 3 (8 ชม.): Batch 3               (auth hardening — JWT)
├── Day 4 (4 ชม.): Batch 4               (syslog + redis resilience)
└── Day 5 (16 ชม.): Batch 5 + 6          (medium + tests)
```

---

## Cross-cutting concerns

1. **Spec compliance:** ทุก batch ต้อง verify กับ `spec.md`
   - Batch 2 alert tenant: align กับ spec §6 (field-level isolation)
   - Batch 3 JWT short-lived: ไม่ละเมิด spec §6
   - Batch 4 RFC6587: align กับ spec §5.1 (UDP+TCP)

2. **Multi-tenant safety:** ทุก router ที่แก้ต้องตรวจ tenant สำหรับ Viewer role
   - ใช้ helper `assert_tenant_access(user, resource)` ถ้ายังไม่มี (ดู `routers/logs.py:99` เป็นตัวอย่าง)

3. **Backwards compatibility:**
   - DB migration: รองรับ rows เดิมด้วย default (`tenant="*"`)
   - JWT: รองรับ token เก่าจนกว่าจะหมดอายุ (overlap 5 นาที)

4. **CI gate:** หลัง Batch 0, CI จะ fail ถ้า test fail → ทุก batch ถัดไปต้องผ่าน CI ก่อน merge

---

## Tracking

ใช้ TaskCreate แยกต่อ batch เมื่อเริ่มทำ แต่ละ batch = 1 PR ใหญ่:
- PR #N: Batch 0 (smoke) — ทำเสร็จแล้ว merge ได้เลย
- PR #N+1: Batch 1 (Critical quick wins)
- PR #N+2: Batch 2 (alert tenant + telemetry)
- PR #N+3: Batch 3 (auth hardening) — review พิเศษ เพราะ breaking
- PR #N+4: Batch 4 (syslog + redis)
- PR #N+5: Batch 5+6 (medium + tests + docs)

---

## Questions to resolve before starting

1. **Batch 3 (JWT):** เลือก Option A (short-lived + refresh), B (iat check), หรือ C (blacklist)?
   - Default plan = Option A

2. **Batch 5A #22 (SEED_DEMO_USERS default):** default เป็น false → dev/CI ต้อง set env var เอง ตกลงไหม?

3. **Batch 6B (docs):** อัพเดตเฉพาะที่จำเป็น หรือ audit ทั้งหมด?

4. **Batch 0 + 1:** ทำเป็น PR เดียวหรือแยก? (default = รวม PR เดียว เพราะทั้งคู่ internal + quick)

---

**สรุป:** ถ้าทำ Batch 0-4 ครบ (ราว ๆ 1 สัปดาห์) → ระบบ production-ready ในแง่ data integrity + auth + multi-tenant
Batch 5-7 เป็น quality-of-life ทำตามหลังได้

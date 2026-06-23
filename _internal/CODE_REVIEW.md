# Code Review — Log Management System

ผลการ review ทั้งโปรเจกต์ — ณ วันที่ 2026-06-19

หลังจาก refactor `/ingest/normalizers/` (ปัญหาข้อ 1 ใน spec_compliance_review.md) ผม review code ที่เหลือทั้งหมด พบ bugs/ข้อกังวลหลายข้อ — เรียงตาม severity

---

## 🔴 Critical — ต้องแก้ก่อน production

### 1. `enrich_and_save` ไม่ rollback session เมื่อ enrich fail → batch ingest พังทั้ง batch

**ไฟล์:** `backend/routers/ingest.py:79-94`

```python
async def enrich_and_save(db: AsyncSession, log: NormalizedLog) -> LogEntry:
    enrichment: Optional[dict] = None
    if log.src_ip:
        try:
            result = await EnrichmentService.enrich(log.src_ip)
            enrichment = {...}
        except Exception:
            logger.exception("Enrichment failed for src_ip=%s", log.src_ip)
    return await save_log(db, log, enrichment)  # ← session poisoned here
```

**ปัญหา:** เมื่อ Redis down, `EnrichmentService.enrich` throws `gaierror`/`ConnectionError`. `try/except` จับและ log ได้ แต่ `db` ยังอยู่ใน failed-transaction state. `save_log` ตามมาเรียก `db.commit()` ก็ fail ด้วย `PendingRollbackError`.

**ผลกระทบ:** POST 1 batch ที่มี 2+ logs → log ตัวแรก enrich fail → log ตัวที่ 2-N fail ทั้งหมด. Smoke test ยืนยันแล้ว: log ตัวที่ 1 error `gaierror`, ตัวที่ 2-7 error `PendingRollbackError`. **Request ทั้งก้อน 500.**

**ทดสอบ:**
```bash
# ตอน Redis down, POST batch:
curl -X POST .../ingest -d '[{"source":"api",...}, {"source":"api",...}]'
# → log #1 500 (gaierror), log #2+ 500 (PendingRollbackError) — ทั้ง batch fail
```

**แก้:** เพิ่ม `await db.rollback()` ใน except block
```python
except Exception:
    await db.rollback()
    logger.exception("Enrichment failed for src_ip=%s", log.src_ip)
```

---

### 2. Alert rule ไม่ผูกกับ tenant — multi-tenant leakage ใน alert engine

**ไฟล์:** `backend/services/alert_engine.py:46-55`, `backend/storage/database.py:75-90`

```python
# alert_engine.py:46
result = await self.db.execute(
    select(AlertRuleDB).where(
        AlertRuleDB.enabled == True,
        AlertRuleDB.event_types.cast(String).contains(log.event_type),
    )
)
# ↑ ไม่มี .where(AlertRuleDB.tenant == log.tenant)
```

**ปัญหา:** `AlertRuleDB` ไม่มี column `tenant`. Rules เป็น global — rule ของ tenant A จะ trigger เมื่อ tenant B ingest log ที่ match. **Spec §6 บอกว่าทุกอย่างต้อง tenant-isolated, แต่ alert engine ละเมิด.**

**ผลกระทบ:** Tenant B ingest failed-login → trigger alert ของ Tenant A. Tenant A เห็น alert ที่ไม่ใช่ของตัวเอง. ร้ายแรงถ้า alert ส่ง webhook/email ออกไปข้างนอก.

**แก้:**
1. เพิ่ม `tenant = Column(String, nullable=False, index=True)` ใน `AlertRuleDB`
2. Migration: ผูก rules เดิมกับ tenant `"*"` (global) หรือ tenant แรก
3. Filter `select(AlertRuleDB).where(... AlertRuleDB.tenant == log.tenant)` ใน alert engine
4. Update `_seed_default_alert_rule` ให้ใช้ tenant `"*"`

---

### 3. `/alerts/{id}/acknowledge` ไม่ตรวจ tenant — Viewer acknowledge alert ของ tenant อื่นได้

**ไฟล์:** `backend/routers/alerts.py:217-228`, `backend/services/alert_engine.py:264-273`

```python
# routers/alerts.py:217
@router.post("/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: int, current_user:..., db: ...):
    engine = AlertEngine(db)
    alert = await engine.acknowledge_alert(alert_id)  # ← ไม่มี tenant check
    if not alert: raise HTTPException(404)
    return {"status": "acknowledged", "alert_id": alert_id}
```

**ปัญหา:** `acknowledge_alert` ใน engine ไม่ตรวจ `alert.tenant == current_user.tenant` สำหรับ Viewer. Detail endpoint (line 143) มี check แต่ acknowledge endpoint ไม่มี.

**ผลกระทบ:** Viewer tenant A ส่ง `POST /alerts/123/acknowledge` (id ของ tenant B) → ได้ 200, alert ของ tenant B ถูก mark acknowledged โดย tenant A.

**แก้:** เพิ่ม tenant check ใน `acknowledge_alert` หรือใน router:
```python
if current_user.role == "Viewer" and alert.tenant != current_user.tenant:
    raise HTTPException(403, "Access denied")
```

---

### 4. `/auth/login` ไม่มี rate limit ใน FastAPI layer (มีแค่ nginx)

**ไฟล์:** `backend/routers/auth.py:11-21`, `nginx/nginx.conf:91-96`

```python
# routers/auth.py — ไม่มี @limiter.limit(...)
@router.post("/login", response_model=Token)
async def login(request: LoginRequest, db: ...):
    ...
```

**ปัญหา:** Brute force attack ตรงเข้า backend ได้ผ่าน IP อื่น (ผ่าน nginx = 100r/m แต่ตรง backend ถ้าเปิด port 8000 สาธารณะ = unlimited). `verify_password` ใช้ bcrypt ที่ช้า (~100ms) แต่ attacker ยังลองได้หลายพันครั้ง/วินาที.

**ผลกระทบ:** Brute force password ได้ในเวลาไม่กี่ชั่วโมง.

**แก้:** เพิ่มใน `routers/auth.py`:
```python
from slowapi import Limiter
from backend.main import limiter

@router.post("/login", response_model=Token)
@limiter.limit("5/minute")  # 5 attempts/min/IP
async def login(request: Request, login_data: LoginRequest, ...):
    ...
```

---

### 5. JWT claims (`role`, `tenant`) ใช้จาก DB แต่ไม่ re-validate หลัง login — privilege escalation หลัง demote

**ไฟล์:** `backend/auth/jwt.py:56-76`, `backend/routers/auth.py:20`

```python
# auth.py:20
access_token = create_access_token(data={"sub": user.username, "role": user.role, "tenant": user.tenant})
# ↑ claims ถูก signed ลง JWT แล้วเชื่อถือได้ตลอด 60 นาที

# auth/jwt.py:67
payload = decode_token(credentials.credentials)  # ใช้แค่ sub → query DB
user = result.scalar_one_or_none()                # ใช้ role/tenant จาก DB
```

**ปัญหา:** หลัง login ได้ token, ถ้า Admin demote user นั้นเป็น Viewer ใน DB, **token เดิมยังใช้ได้จนกว่าจะหมดอายุ** (60 นาที default). User ที่ถูก demote แล้วยังเข้าถึง admin endpoints ได้ด้วย token เก่า.

**ผลกระทบ:** Revoked user ยังใช้งานได้ 60 นาที. ร้ายแรงถ้า compromise account.

**แก้ (เลือก 1):**
- Short-lived access token (5-15 นาที) + refresh token (revocable ใน DB)
- หรือ: blacklist table สำหรับ revoked tokens
- หรือ: ตรวจ `payload["iat"]` กับ `user.updated_at` ใน `get_current_user`

---

## 🟠 High — ควรแก้

### 6. `setup_telemetry()` ถูกเรียก module-level แต่ใช้ `app` — execution order fragile

**ไฟล์:** `backend/main.py:159-188`

```python
app = FastAPI(..., lifespan=lifespan)  # line 98

def setup_telemetry():
    ...
    FastAPIInstrumentor.instrument_app(app)  # line 182 — ใช้ app

setup_telemetry()  # line 188 — module-level
```

**ปัญหา:** `setup_telemetry()` ต้องรันหลัง `app = FastAPI(...)` ถูก define. ถ้าใครย้าย line ใด line หนึ่ง → `NameError: name 'app' is not defined`. ไม่มี test จับ.

**แก้:** ย้ายไปเรียกใน `lifespan` startup:
```python
async def lifespan(app):
    await init_db()
    await seed_defaults()
    setup_telemetry()  # ← ที่นี่
    app.state.syslog_task = ...
```

---

### 7. `_handle_syslog_line` docstring บอก RFC6587 octet-counted แต่ code เป็น LF-delimited

**ไฟملف:** `backend/main.py:354-381`

```python
async def tcp_loop():
    """RFC6587-style octet-counted or LF-delimited TCP syslog.   ← โกหก
    ...
async def _handle_tcp_client(...):
    ...
    data = await reader.readuntil(b"\n")  # ← LF-delimited ล้วน ไม่รองรับ octet-counted
```

**ปัญหา:** Production syslog forwarders (rsyslog, syslog-ng) ส่งแบบ octet-counted (RFC6587 §3.4.1) เป็น default. Code รับแค่ LF-delimited (legacy mode). Bytes ที่ตามมาจะถูกตีความผิดเป็น garbage log.

**แก้:** Implement octet-counted parsing (ตรวบ byte count แรก → อ่าน N bytes → แล้ววน loop) หรือลด docstring ลง

---

### 8. `RedisCache.get()` cache singleton แม้ first call fail

**ไฟล์:** `backend/services/enrichment.py:46-57`

```python
class RedisCache:
    _instance = None
    @classmethod
    async def get(cls):
        if cls._instance is None:
            cls._instance = redis.from_url(settings.REDIS_URL, ...)  # ถ้า fail?
        return cls._instance
```

**ปัญหา:** ถ้า `redis.from_url(...)` throws (เช่น bad URL format), `_instance` ไม่ถูก set แต่ exception propagate ขึ้นไป. แต่ถ้า `from_url` สำเร็จ (lazy connect) แต่ command แรก (`hgetall`) fail, `_instance` ถูก cache แล้ว — ทุก call ถัดไปใช้ broken connection.

**ผลกระทบ:** ถ้า Redis ตายกลางคัน, enrichment fail ตลอดจนกว่า process จะ restart.

**แก้:** Reset `_instance = None` ใน except ของ enrich():
```python
except redis.ConnectionError:
    RedisCache._instance = None
    raise
```

---

### 9. CI ใช้ `|| true` ทำให้ test fail ก็ merge ได้

**ไฟล์:** `.github/workflows/ci.yml:36, 44`

```yaml
- name: Run backend tests
  run: pytest tests/ -v --tb=short || true   # ← failure swallowed

- name: Run frontend tests
  run: npm test --prefix frontend -- --run || true
```

**ปัญหา:** Test fail = exit 0 → CI pass → merge ได้. **ทำให้ CI ไร้ค่า.**

**แก้:** ลบ `|| true` ออก

---

### 10. `package.json` มี dep ที่ไม่ใช้ (`tailwind-merge`)

**ไฟล์:** `frontend/package.json:21`, `frontend/src/**/*.jsx`

```bash
$ grep -rn "tailwind-merge\|twMerge" frontend/src/
# (ไม่มีผลลัพธ์)
```

**ปัญหา:** `tailwind-merge` ติดตั้งแต่ไม่มีไฟล์ไหน import. เพิ่ม bundle size ฟรี.

**แก้:** `npm uninstall tailwind-merge`

---

### 11. `nginx/nginx.conf` ไม่ forward TCP syslog — spec §5.1 ต้องการ UDP+TCP

**ไฟล์:** `nginx/nginx.conf:10-20`

```nginx
stream {
    upstream syslog_backend { server backend:514; }
    server { listen 514 udp; proxy_pass syslog_backend; }  # ← UDP only
    # ไม่มี TCP listener
}
```

**ปัญหา:** Spec §5.1 บอก "Syslog UDP/TCP 514". Backend listen ทั้งสอง (verified), แต่ nginx forward แค่ UDP. TCP syslog เข้า port 514 จะโดน reject เพราะ nginx ไม่ listen TCP.

**ผลกระทบ:** ใครส่ง TCP syslog ผ่าน nginx เข้ามา → connection refused. เห็นใน docker-compose comment "Note: 514 (both UDP and TCP) is owned by the backend service above" แต่จริง ๆ ถ้าใช้ nginx เป็น entry point, TCP จะหาย

**แก้:** เพิ่ม TCP syslog stream block:
```nginx
server {
    listen 514 tcp;
    proxy_pass syslog_backend;
}
```

---

### 12. `ingest/requirements.txt` มี dep ที่ไม่ได้ใช้ + version เก่า

**ไฟล์:** `ingest/requirements.txt`

```
fastapi==0.109.2
uvicorn==0.27.1
python-syslog-ng==0.1.0   ← ไม่มี code ไหน import (grep ยืนยัน)
```

**ปัญหา:** `python-syslog-ng` ไม่ได้ใช้. เพิ่ม install time ฟรี.

**แก้:** ลบ `python-syslog-ng` ออก หรือถ้าตั้งใจให้ ingest/ เป็น standalone service ในอนาคต ก็ keep ไว้

---

## 🟡 Medium — ควรปรับปรุง

### 13. `NormalizedLog._tags` เงียบหาย — Pydantic v2 treats `_tags` as private

**ไฟล์:** `backend/models/schemas.py:40`, `backend/normalizer/core.py:_to_model`

**ปัญหา:** Pydantic v2 ignores fields starting with `_` (private attributes). `NormalizedLog._tags: List[str] = []` ดูเหมือน field แต่ถูก treat เป็น private attr → ไม่ถูก validate, ไม่ถูก populate, ไม่ถูก dump. **Test ยืนยัน:** `_tags: []` เสมอแม้ ingest ใส่มา.

```python
m = NormalizedLog.model_validate({'@timestamp': '...', 'tenant': 't', 'source': 'crowdstrike',
                                  'event_type': 'x', '_tags': ['malware']})
m._tags  # → [] (not ['malware'])
```

**ผลกระทบ:** ไม่มีทาง query หรือ filter ด้วย tags. Spec §3 กำหนด `_tags` เป็น field ที่ต้องมี.

**แก้:** Rename ใน schema เป็น `tags` (ไม่มี prefix) แล้ว alias ด้วย `_tags`:
```python
tags: List[str] = Field(default=[], alias="_tags", serialization_alias="_tags")
# หรือใช้ ConfigDict(protected_namespaces=()) แล้วใช้ field name เดิม
```

**Breaking change:** ต้องอัพเดตทุกที่ที่ reference `_tags` (UI, router)

---

### 14. `ingest/aws_normalizer.py` crash เมื่อ `cloud` ไม่ใช่ dict

**ไฟล์:** `ingest/normalizers/aws_normalizer.py:6`

```python
cloud_data = data.get("cloud", {}) or {}
# ถ้า data["cloud"] = "string" (truthy), cloud_data = "string" แล้ว .get() crash
tags = cloud_data.get("service")  # AttributeError: 'str' object has no attribute 'get'
```

**ทดสอบ:** POST `/ingest` body `{"source":"aws", "event_type":"x", "cloud":"oops"}` → 500 `AttributeError`. Attacker ส่ง malformed JSON ก็ทำให้ ingest fail ได้.

**แก้:** เพิ่ม type check:
```python
cloud_data = data.get("cloud") if isinstance(data.get("cloud"), dict) else {}
```

---

### 15. `users.py` มี duplicate docstring + dead import

**ไฟملف:** `backend/routers/users.py:1-4`

```python
"""User Management API — Admin-only user CRUD."""
import bcrypt
"""User Management API — Admin-only user CRUD."""   ← ซ้ำ
import bcrypt                                          ← ซ้ำ
from fastapi import APIRouter, Depends, HTTPException
```

**ปัญหา:** Docstring/import ซ้ำ. `import bcrypt` ไม่ได้ใช้ (code ใช้ `get_password_hash` จาก `auth.jwt`).

**แก้:** ลบ duplicate

---

### 16. `UserCreate.tenant` default เป็น empty string — silently ใช้งานไม่ได้

**ไฟล์:** `backend/routers/users.py:23`

```python
class UserCreate(BaseModel):
    ...
    tenant: str = ""  # ← default empty
```

**ปัญหา:** ถ้า Admin สร้าง Viewer โดยไม่ใส่ tenant → `tenant = ""` → `WHERE tenant == ""` ไม่ match อะไรเลย. User ถูกสร้างแต่ใช้งานไม่ได้.

**แก้:** `tenant: str = Field(min_length=1)` หรือ validate ใน endpoint

---

### 17. `AlertRules.jsx` ไม่มี UI edit/delete — backend API มีแต่หน้าบ้านเรียกไม่ครบ

**ไฟملف:** `frontend/src/pages/AlertRules.jsx`, `frontend/src/services/api.js:69-82`

**ปัญหา:** `api.alerts.update()` และ `api.alerts.delete()` มีอยู่ใน api.js แต่ `AlertRules.jsx` ไม่มีปุ่ม edit/delete. Admin สร้าง rule แล้วลบไม่ได้.

**แก้:** เพิ่ม edit form + delete confirm ใน AlertRules.jsx

---

### 18. `UserManagement.jsx` ไม่มี UI edit

**ไฟملف:** `frontend/src/pages/UserManagement.jsx`

**ปัญหา:** เหมือนกัน — `users.update` มีใน api.js แต่ไม่มี UI เรียก. Admin เปลี่ยน role/tenant ของ user ไม่ได้.

**แก้:** เพิ่ม edit modal

---

### 19. `handleCreate` dead code ใน UserManagement.jsx

**ไฟملف:** `frontend/src/pages/UserManagement.jsx:69-72`

```javascript
const payload = { ...formData }
if (formData.role === 'Admin' && formData.tenant === '*') {
  payload.tenant = '*'  // ← formData.tenant เป็น '*' อยู่แล้ว spread มา
}
```

**ปัญหา:** condition check แล้ว set ค่าเดิม — dead code

**แก้:** ลบ if block

---

### 20. `users.py` ไม่ validate role enum — string ใดก็ได้ผ่าน create endpoint (แต่ admin ใช้แค่)

**ไฟملف:** `backend/routers/users.py:78-79`

```python
if data.role not in ("Admin", "Viewer"):
    raise HTTPException(400, "role must be Admin or Viewer")
```

**ปัญหา:** ตรวจใน endpoint ได้ แต่ schema `UserCreate.role: str` ไม่ constrain. Pydantic v2 มี Literal:
```python
role: Literal["Admin", "Viewer"] = "Viewer"
```
จะ validate ที่ schema layer ทันที ไม่ต้องเขียนซ้ำใน endpoint

**แก้:** ใช้ `Literal` ใน `UserCreate` และ `UserUpdate`

---

### 21. `init-db.sql` กับ SQLAlchemy model drift — schema 2 แห่งไม่ sync

**ไฟملف:** `backend/storage/database.py` vs `scripts/init-db.sql`

**ปัญหา:** 2 แห่ง define table. ถ้าเพิ่ม column ใน model ต้อง remember ไปแก้ SQL ด้วย หรือกลับกัน.

**แก้:** Generate SQL จาก model ด้วย `Base.metadata.create_all` (มีอยู่แล้วใน `init_db()`) แล้วลบ init-db.sql ออก — แต่ init-db.sql มี point: `make init` ทำงานก่อน backend start. ทางเลือก: ใช้ Alembic migration

---

### 22. `_seed_users` defaults เป็น "true" + ไม่มี DEBUG-mode check

**ไฟملف:** `backend/main.py:202-230`

```python
if os.getenv("SEED_DEMO_USERS", "true").lower() not in ("1", "true", "yes"):
    return
```

**ปัญหา:** Default `SEED_DEMO_USERS=true` + default password `admin123`/`viewer123`. ถ้า operator ลืม set env ใน production, seed users ด้วย password ที่รู้ทั่ว.

**แก้:** Default false, หรือ check `if not settings.DEBUG`

---

### 23. `AlertRules.jsx` event types เป็น hard-coded suggestions — ไม่รับ custom

**ไฟملف:** `frontend/src/pages/AlertRules.jsx:7-10, 200-218`

```javascript
const EVENT_TYPE_SUGGESTIONS = [
  'LogonFailed', 'app_login_failed', 'malware_detected',
  'CreateUser', 'DeleteUser', 'UserLoggedIn',
]
// UI แสดงแค่ 6 ตัวนี้ ไม่มี input สำหรับเพิ่ม event type ใหม่
```

**ปัญหา:** ถ้า user มี event type เอง (เช่น `SuspiciousProcessDetected`) สร้าง rule ไม่ได้

**แก้:** เพิ่ม input + chips ให้พิมพ์เองได้

---

### 24. `_bcrypt_hash` duplicated ใน `auth/jwt.py` กับ `main.py`

**ไฟملف:** `backend/main.py:266-273`, `backend/auth/jwt.py:24-39`

ทั้งสอง file มี logic เดียวกัน (pre-hash ด้วย SHA-256 ถ้า >72 bytes) แต่ main.py copy มาเอง ไม่ import

**แก้:** import `_bcrypt_input` จาก `auth.jwt`

---

## 🟢 Low — nice-to-have

### 25. `tenant` filter ใน Dashboard เป็น free-text — ไม่ validate ว่า tenant มีจริง

**ไฟملف:** `frontend/src/pages/Dashboard.jsx:142-145`

```javascript
<input className="input" placeholder="(all)" value={tenant} onChange={...} />
```

**ปัญหา:** User พิมพ์ tenant ผิด → query ได้ 0 results โดยไม่รู้ว่าพิมพ์ผิด

**แก้:** ใช้ dropdown จาก `/logs/facets` (เหมือน LogSearch)

---

### 26. `frontend/src/services/api.js` 401 handler ใช้ full page reload — กระตุก UI

**ไฟملف:** `frontend/src/services/api.js:41-54`

```javascript
if (status === 401) {
  localStorage.removeItem('token')
  if (window.location.pathname !== '/login') {
    window.location.href = '/login'  // ← full page reload
  }
}
```

**ปัญหา:** Token หมดอายุ → user โดน kick ไป login แบบกระตุก แทนที่จะ toast + redirect ผ่าน React Router

**แก้:** ใช้ `navigate('/login')` แทน `window.location.href`

---

### 27. Frontend localStorage token — vulnerable to XSS ✅ FIXED

**เดิม:** Frontend เก็บ JWT ใน `localStorage` → XSS = token ถูกขโมยได้

**แก้แล้ว:** ย้ายไป HttpOnly cookie

**ไฟล์ที่เปลี่ยน:**
- `backend/config.py` — เพิ่ม `AUTH_COOKIE_NAME`, `AUTH_COOKIE_PATH`, `AUTH_COOKIE_SAMESITE`
- `backend/auth/jwt.py` — `get_current_user` อ่านจาก cookie ก่อน แล้ว fallback ไป `Authorization: Bearer` header (สำหรับ CLI/curl/tests)
- `backend/routers/auth.py` — `/auth/login` ตอบกลับด้วย `Set-Cookie: access_token=...; HttpOnly; SameSite=Lax; Path=/api/v1; Max-Age=3600` (Secure ตาม request scheme) + เพิ่ม `/auth/logout` ที่ clear cookie
- `frontend/src/services/api.js` — `withCredentials: true` + ลบ Authorization header injection + เพิ่ม `auth.logout()`
- `frontend/src/App.jsx` — `token` state → `session` state (null=loading, true=auth, false=unauth) + probe `/auth/me` ตอน mount
- `frontend/src/components/Layout.jsx` — fetch user จาก `/auth/me` แทน `jwtDecode(localStorage.token)` + ลบ `jwt-decode` import
- `frontend/src/pages/Login.jsx` — ลบ `localStorage.setItem('token', ...)`, แค่ `onLogin()` หลัง login success
- `tests/test_auth_cookie.py` (ใหม่) — 8 tests ตรวจ HttpOnly, SameSite, Path, Max-Age, logout clear, cookie-only auth, header fallback

**OWASP session management checklist:**
- ✅ HttpOnly (JS อ่านไม่ได้ — `document.cookie` ไม่เห็น token)
- ✅ Secure (HTTPS-only ใน production — local dev HTTP ยังทำงาน)
- ✅ SameSite=Lax (CSRF defense — block cross-origin POST/PUT/DELETE)
- ✅ Path scoping (`/api/v1` ไม่ leak ไป static assets)
- ✅ Explicit Max-Age (ไม่ใช่ session cookie — TTL ผูกกับ JWT expiry)
- ✅ Server-side logout endpoint (`/auth/logout` clear cookie ทันที)

---

**ไฟملف:** `frontend/src/App.jsx:20`, `frontend/src/services/api.js:33-39`

**ปัญหา:** JWT เก็บใน `localStorage` → XSS = token ถูกขโมยได้

**แก้:** httpOnly cookie (ต้องปรับ backend CORS credentials handling) หรือ session storage (ลด attack window)

---

### 28. `AlertTriggered.jsx` ไม่มี auto-refresh

**ไฟملف:** `frontend/src/pages/AlertTriggered.jsx:78`

```javascript
useEffect(() => { loadAlerts() }, [filters])
```

**ปัญหา:** ไม่ refresh อัตโนมัติ, user ต้องกด Refresh เอง

**แก้:** เพิ่ม `setInterval(loadAlerts, 30000)` พร้อม cleanup

---

### 29. `routers/logs.py:332` ใช้ `cast(LogEntry.raw, Text).ilike(...)` — JSON cast + LIKE ช้ามาก

**ไฟملف:** `backend/routers/logs.py:320-323`

```python
if db.bind.dialect.name == "postgres":
    search_filter = search_filter.or_(
        cast(LogEntry.raw, Text).ilike(f"%{q}%")  # ← O(n*size) scan
    )
```

**ปัญหา:** แปลง JSONB → text → LIKE ไม่ใช้ index. ทุก row ถูก scan + convert. Log row 1M+ → query หลายวินาที

**แก้:** ใช้ PostgreSQL `tsvector` full-text index หรือ JSONB containment queries

---

### 30. `users.py` `MAX_PASSWORD_BYTES = 72` แต่ไม่ enforce ผ่าน schema

**ไฟملف:** `backend/routers/users.py:15, 21`

```python
MAX_PASSWORD_BYTES = 72
class UserCreate(BaseModel):
    password: str = Field(min_length=8, max_length=128)  # ← char count
```

**ปัญหา:** `max_length=128` คือ character count, แต่ bcrypt limit 72 **bytes**. Password 50 ASCII char = 50 bytes, OK. Password 50 Thai char = ~150 bytes (UTF-8) → bcrypt silent-truncate (pre-hash กันไว้แล้ว แต่ schema ไม่ enforce byte length)

**แก้:** Custom validator ที่นับ bytes หรือ `Field(max_length=72)`

---

### 31. `.env.example` SECRET_KEY เป็น placeholder 41 chars — ผ่าน boot check

**ไฟملف:** `.env.example:8`

```
SECRET_KEY=change-me-in-production-use-strong-random-key   # 41 chars
```

**ปัญหา:** boot check `len(SECRET_KEY) < 32` ผ่าน. ถ้า user copy `.env.example` → `.env` โดยไม่แก้ → SECRET_KEY = "change-me-in-production-..." → JWT sign ได้ด้วย known key

**แก้:** ใส่ `SECRET_KEY=` (empty) ใน .env.example ให้ boot check fail

---

### 32. ไม่มี `test_normalizer.py` — refactor ใหม่ไม่มี unit test

**ไฟملف:** `tests/`

**ปัญหา:** ทั้ง 6 normalizer (api, aws, m365, ad, crowdstrike, syslog) ไม่มี direct unit test. Tests ทั้งหมด test ผ่าน HTTP endpoint ซึ่ง coverage ไม่ละเอียดพอ

**แก้:** เพิ่ม `tests/test_normalizer.py` ที่ test:
- แต่ละ source → dict keys + values
- Edge cases (missing field, invalid IP, bad action)
- Round-trip: `normalize_log` → save → query

---

### 33. ไม่มี test สำหรับ `enrich_and_save` graceful degradation

**ไฟملف:** `tests/test_enrichment.py`

**ปัญหา:** ไม่มี test "ถ้า Redis fail ต้อง rollback session แล้ว ingest log ต่อได้"

**แก้:** เพิ่ม test mock Redis failure

---

### 34. ไม่มี test สำหรับ syslog UDP/TCP listener

**ไฟملف:** `backend/main.py:328-387`

**ปัญหา:** ไม่มี test `_handle_syslog_line`, `start_syslog_listener`

**แก้:** integration test ที่ส่ง syslog เข้า socket จริง

---

### 35. ไม่มี test สำหรับ retention loop

**ไฟملف:** `backend/main.py:43-60`, `scripts/retention.py`

**ปัญหา:** Spec §10 บอก "7-day retention" แต่ไม่มี test ว่า log เก่า 8 วันถูกลบจริง

**แก้:** เพิ่ม test ingest log with timestamp 8 days ago, run retention, assert deleted

---

## ✅ ไม่พบปัญหา (verified)

- **37/37 tests pass** (baseline หลัง refactor)
- **Refactor (`/ingest/normalizers/` → `backend/normalizer/core.py` adapter)** ไม่มี bug ใหม่
- **Sample files** (syslog, crowdstrike, aws, m365, ad) ingest ผ่านครบ 6/6 sources
- **Auth flow** (login + JWT) ใช้งานได้
- **RBAC Viewer** ทำงานถูกต้อง (test ยืนยัน)
- **Security headers** (X-Frame-Options, HSTS, CSP-lite via Permissions-Policy) ครบ
- **Rate limiting** (slowapi + nginx dual-layer) ทำงาน
- **Bcrypt** pre-hash SHA-256 สำหรับ password >72 bytes (ป้องกัน silent truncation)

---

## สรุปตาม severity

| Severity | Count | ต้องแก้ก่อน production |
|----------|-------|------------------------|
| 🔴 Critical | 5 | 1, 2, 3, 4, 5 |
| 🟠 High | 7 | 6-12 |
| 🟡 Medium | 12 | 13-24 |
| 🟢 Low | 11 | 25-35 |
| ✅ Verified OK | 8 | - |

**Top 3 ต้องแก้ก่อน:**
1. **#1 enrich_and_save session poisoning** — Redis down = batch ingest fail
2. **#2 alert rule ไม่ tenant-scoped** — multi-tenant leak
3. **#4 login ไม่มี rate limit ที่ FastAPI layer** — brute force ได้

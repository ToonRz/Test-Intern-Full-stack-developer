# Spec Compliance Review

ผลการเปรียบเทียบโค้ดใน repo กับ `spec.md` — รีวิว ณ วันที่ 2026-06-19

---

## ส่วนที่ครบตาม spec

### §1 Repository Structure

ครบ — `/docs/{architecture,setup_appliance,setup_saas}.md`, `docker-compose.yml`, `.env.example`, `Makefile`, `/samples/`, `/tests/`, `/backend/README.md`, `/frontend/README.md`, `/ingest/README.md`

### §2 Log Sources (ต้อง ≥4, โปรเจกต์นี้มี 6)

| Source | ตำแหน่งโค้ด | Sample |
|---|---|---|
| Firewall/Syslog | `backend/normalizer/core.py:7` | `samples/send_syslog.sh` |
| Network Router Syslog | `backend/normalizer/core.py:50` | `samples/send_syslog.sh` |
| HTTP API | `backend/routers/ingest.py:97` | `samples/post_logs.py` |
| CrowdStrike | `backend/normalizer/core.py:113` | `samples/sample_crowdstrike.json` |
| AWS CloudTrail | `backend/normalizer/core.py:131` | `samples/sample_aws_cloudtrail.json` |
| Microsoft 365 | `backend/normalizer/core.py:150` | `samples/sample_m365.json` |
| Microsoft AD/Windows | `backend/normalizer/core.py:166` | `samples/sample_ad_4625.json` |

### §3 Normalized Schema

`backend/models/schemas.py:12` ครบทุก field ตาม spec: `@timestamp`, `tenant`, `source`, `vendor`, `product`, `event_type`, `event_subtype`, `severity`, `action`, `src_ip`, `src_port`, `dst_ip`, `dst_port`, `protocol`, `user`, `host`, `process`, `url`, `http_method`, `status_code`, `rule_name`, `rule_id`, `cloud`, `raw`, `_tags`

### §4 Tech Stack

- Backend: FastAPI
- UI: React + Recharts
- Storage: PostgreSQL + JSONB
- Collector: Custom Python (UDP/TCP syslog listener ใน `backend/main.py:328`)

### §5 Backend API

| Endpoint | Spec | สถานะ | ตำแหน่ง |
|---|---|---|---|
| `POST /ingest` (single+batch) | §5.1 | ครบ | `routers/ingest.py:97` |
| `POST /ingest/batch` | §5.1 | ครบ | `routers/ingest.py:140` |
| UDP/TCP 514 syslog | §5.1 | ครบ | `backend/main.py:328` |
| `GET /logs` (+ tenant/source/event_type/start/end/page/size) | §5.2 | ครบ + bonus (q, action, severity, geo_country) | `routers/logs.py:275` |
| `GET /alerts` | §5.3 | ครบ | `routers/alerts.py:13` |
| `POST /alerts` | §5.3 | ครบ | `routers/alerts.py:43` |
| `GET /alerts/triggered` | §5.3 | ครบ | `routers/alerts.py:84` |
| `POST /auth/login` | §5.4 | ครบ | `routers/auth.py:11` |
| `GET /auth/me` | §5.4 | ครบ | `routers/auth.py:24` |

### §6 AuthN/AuthZ

- JWT — `backend/auth/jwt.py:42`
- Admin + Viewer roles — seed ใน `main.py:202`
- Multi-tenant ผ่าน JWT claim + field `tenant` ใน LogEntry
- Auth middleware ครอบทุก endpoint

### §7 Dashboard Pages

ครบทั้ง 5 หน้า: `/` Dashboard, `/logs` Log Search, `/alerts` Alert Rules, `/alerts/triggered` Alert Triggered, `/login` Login

### §8 Alerting

- Login Failed Brute-Force rule ถูก seed อัตโนมัติ — `main.py:233` (threshold=5, window=5 min, group by src_ip)
- Trigger + store — `services/alert_engine.py:35`
- Webhook — ใช้ httpx ใน `_send_webhook`
- Email — **เป็น stub** (ดู §ปัญหาที่พบ)

### §9 Deployment

- Appliance — `make up` ใช้งานได้
- SaaS/HTTPS — `nginx/nginx.conf` + `scripts/generate-certs.sh`

### §10 Data Retention

- 7 วัน default — `DATA_RETENTION_DAYS=7` ใน `.env.example`
- Mechanism — background loop ใน `main.py:_retention_loop` + `scripts/retention.py`

### §11 Deliverables

Postman/Insomnia collection — `api_collection.json`

### §12 Acceptance Checklist

ครบทุกข้อ: เปิดระบบ Appliance, ส่ง Syslog, POST /ingest, batch upload, Dashboard, alert rule + trigger, RBAC Viewer, SaaS HTTPS

---

## ส่วนที่อยู่นอกเหนือ spec

### A. Enrichment (GeoIP + Reverse DNS) — §14 Nice-to-Have ที่กลายเป็น core

- `backend/services/enrichment.py` เต็มระบบ (Redis cache, suspicious-country auto-tag)
- เก็บในคอลัมน์เพิ่ม: `geo_country`, `geo_city`, `geo_lat`, `geo_lon`, `rdns_hostname` ใน `LogEntry`
- ปัญหา: `GEOIP_DB_PATH=/var/lib/geoip/GeoLite2-City.mmdb` ถูก reference แต่**ไม่มี download/install ใน docker-compose หรือ Makefile** — graceful degrade ก็จริง แต่ GeoIP จะใช้ไม่ได้ out-of-the-box

### B. Tenants CRUD API + UI — ไม่อยู่ใน spec

- `backend/routers/tenants.py` (GET/POST/DELETE `/tenants`)
- ตาราง `TenantDB` ใน database
- Spec §6 บอกว่าเป็น **field-level isolation** เท่านั้น ไม่ต้องมี tenant registry — โปรเจกต์นี้เพิ่มเข้ามาเอง

### C. User Management API + UI — ไม่อยู่ใน spec

- `backend/routers/users.py` (GET/POST/PATCH/DELETE `/users`)
- `frontend/src/pages/UserManagement.jsx`
- Spec §5.4 มีแค่ `/auth/login` กับ `/auth/me` — โปรเจกต์นี้เพิ่มเข้ามาเอง

### D. Acknowledge Alerts — ไม่อยู่ใน spec

- `POST /alerts/{id}/acknowledge` + UI ปุ่ม Acknowledge
- Spec §8 ไม่ได้พูดถึง workflow นี้

### E. Severity Bucket Filter (UI) — ส่วนขยาย

- `routers/logs.py` รับ `?severity=critical` แล้วแปลงเป็น numeric range 9-10
- ส่วนนี้ไม่อยู่ใน spec schema (ที่กำหนด severity เป็น integer 0-10) — UI สร้าง abstraction เพิ่ม

### F. Action enum ขยาย — เกิน spec

- Spec §3 กำหนด action: `"allow | deny | create | delete | login | logout | alert"`
- `schemas.py:24` รับเพิ่ม: `"quarantine", "block", "detect", "prevent", "notify"` — เพื่อรองรับ CrowdStrike เช่น `action="quarantine"` ใน sample §4.4
- ถ้า strict spec ต้อง flag

### G. Helm Chart + Terraform — §14 Nice-to-Have

- `helm/log-management/` (backend + frontend subcharts)
- `terraform/` (EKS, VPC, RDS modules)
- ไม่มี test รองรับ — สถานะใช้งานได้จริงไม่ได้ตรวจ

### H. Observability (OpenTelemetry) — §14 Nice-to-Have

- `setup_telemetry()` ใน `main.py:159` — optional (เปิดเฉพาะเมื่อ `OTEL_EXPORTER_OTLP_ENDPOINT` ตั้ง)
- ไม่มี Prometheus/metrics endpoint

### I. Security Headers + Rate Limiting + CORS

- `X-Frame-Options`, `HSTS`, `Permissions-Policy` ใน `main.py:109`
- `slowapi` rate limit 100 req/min ใน `main.py:40`
- CORS — ไม่อยู่ใน spec (ดีแล้ว แต่ไม่ required)

### J. Dead Code: `/ingest/normalizers/`

- มีไฟล์ `api_normalizer.py`, `aws_normalizer.py`, `crowdstrike_normalizer.py`, `m365_normalizer.py`, `ad_normalizer.py`, `syslog_normalizer.py` ครบ 6 ตัว
- **ไม่มีไฟล์ไหนใน backend import มันเลย** — backend ใช้ `backend/normalizer/core.py` ล้วน ตรวจด้วย grep แล้วไม่มี `from ingest` หรือ `import ingest`
- เป็น duplicate logic ที่ไม่ได้ใช้งาน ควรลบทิ้งหรือต่อให้ทำงานจริง

---

## ตรวจ log examples เทียบกับ spec §4

| Spec section | Sample format | ไฟล์ใน repo | ตรงกับ spec |
|---|---|---|---|
| §4.1 Firewall/Syslog | `<134>Aug 20 12:44:56 fw01 vendor=demo product=ngfw action=deny src=... dst=... spt=... dpt=... proto=... msg=... policy=...` | `samples/sample_firewall.log` + `samples/send_syslog.sh` | ตรง |
| §4.2 Network Router Syslog | `<190>Aug 20 13:01:02 r1 if=ge-0/0/1 event=link-down mac=... reason=carrier-loss` | `samples/send_syslog.sh` บรรทัด 22-26 | ตรง |
| §4.3 HTTP API | `{tenant, source:api, event_type:app_login_failed, user, ip, reason, @timestamp}` | `samples/post_logs.py` บรรทัด 48-56 | ตรง |
| §4.4 CrowdStrike | `{tenant, source:crowdstrike, event_type:malware_detected, host, process, severity:8, sha256, action:quarantine, @timestamp}` | `samples/sample_crowdstrike.json` บรรทัด 1-12 | ตรง |
| §4.5 AWS CloudTrail | `{tenant, source:aws, cloud:{service,account_id,region}, event_type:CreateUser, user, @timestamp, raw:{eventName, requestParameters}}` | `samples/sample_aws_cloudtrail.json` บรรทัด 1-10 | ตรง |
| §4.6 Microsoft 365 | `{tenant, source:m365, event_type:UserLoggedIn, user, ip, status:Success, workload:Exchange, @timestamp}` | `samples/sample_m365.json` บรรทัด 1-11 | ตรง |
| §4.7 Microsoft AD EventID 4625 | `{tenant, source:ad, event_id:4625, event_type:LogonFailed, user, host, ip, logon_type, @timestamp}` | `samples/sample_ad_4625.json` บรรทัด 1-12 | ตรง |

**สรุป: ทุก log example ใน spec ตรงกับ sample ใน repo 100%** — field name, format, value ทุกอย่างตรง

หมายเหตุ: `samples/sample_crowdstrike.json` มี log ที่ 2 ที่เพิ่มเข้ามาเอง (event_type=`process_created`, action=`detected`) ซึ่งไม่ได้อยู่ใน spec แต่เป็น variant ที่สมเหตุสมผล ไม่ใช่การละเมิด spec เพราะ spec แค่ยกตัวอย่างเดียวต่อ source

---

## ปัญหาที่พบ — แนะนำให้แก้

1. **ลบ `/ingest/normalizers/`** หรือ refactor ให้ backend ใช้จริง — เป็น dead code 6 ไฟล์
2. **Email alert เป็น stub** — ถ้าจะ claim "Webhook + Email" ต้องต่อ SMTP จริง ตอนนี้แค่ log
3. **GeoIP DB ไม่ได้ติดตั้ง** — `GEOIP_DB_PATH` ชี้ไป path ที่ว่างเปล่า ถ้าจะใช้ enrichment จริงต้องเพิ่ม download step ใน docker-compose
4. **Action enum ขยายเกิน spec** — ถ้าจะ strict กับ spec ต้องตัด `quarantine/block/detect/prevent/notify` ออก หรือเพิ่มใน spec ก่อน
5. **Tenants + Users CRUD** — ถ้าถือว่า "out of spec" ควร flag ใน PR ให้กรรมการรู้ว่าส่วนนี้เป็น extra

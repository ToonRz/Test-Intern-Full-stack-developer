# Log Management System — Implementation Spec

## Overview

Demo ระบบ Log Management รองรับแหล่งข้อมูลหลากหลาย ติดตั้งได้ 2 โหมด:
- **Appliance**: รันบนเครื่องเดียว / VM เดียว (Docker Compose)
- **SaaS/Cloud**: รันบน Cloud มี URL สำหรับเข้าใช้งานจากภายนอก

---

## 1. Repository Structure

```
/
├── docker-compose.yml
├── .env.example
├── Makefile (หรือ run.sh)
├── docs/
│   ├── architecture.md
│   ├── setup_appliance.md
│   └── setup_saas.md
├── backend/
│   └── README.md
├── frontend/
│   └── README.md
├── ingest/
│   └── README.md
├── samples/
│   ├── send_syslog.sh
│   ├── post_logs.py
│   └── (sample log files)
└── tests/
    └── (อย่างน้อย 2–3 test cases)
```

---

## 2. Log Sources (ต้องรองรับอย่างน้อย 4 แหล่งจริง)

| Source | Protocol | หมายเหตุ |
|---|---|---|
| Firewall / Network | Syslog UDP/TCP port 514 | ต้องรับจริง |
| API | HTTP POST JSON | ต้องรับจริง |
| CrowdStrike | File batch (JSON/CSV) หรือ simulator | sample ได้ |
| AWS (CloudTrail/ALB/NLB) | File batch (JSON) | sample ได้ |
| Microsoft 365 (Unified Audit Log) | File batch (JSON) | sample ได้ |
| Microsoft AD / Windows Security (EventID 4624/4625) | File batch (JSON) | sample ได้ |

> อย่างน้อย 4 แหล่งต้องยิงเข้าได้จริง เช่น Syslog + HTTP API + JSON batch + simulator script

---

## 3. Normalized Schema (Central Schema)

ทุก log ต้อง normalize เข้า schema นี้ก่อนเก็บ:

```json
{
  "@timestamp":     "RFC3339 string",
  "tenant":         "string",
  "source":         "firewall | crowdstrike | aws | m365 | ad | api | network",
  "vendor":         "string",
  "product":        "string",
  "event_type":     "string",
  "event_subtype":  "string",
  "severity":       "integer 0–10",
  "action":         "allow | deny | create | delete | login | logout | alert",
  "src_ip":         "string",
  "src_port":       "integer",
  "dst_ip":         "string",
  "dst_port":       "integer",
  "protocol":       "string",
  "user":           "string",
  "host":           "string",
  "process":        "string",
  "url":            "string",
  "http_method":    "string",
  "status_code":    "integer",
  "rule_name":      "string",
  "rule_id":        "string",
  "cloud": {
    "account_id":   "string",
    "region":       "string",
    "service":      "string"
  },
  "raw":            "object | string (ข้อความดิบ)",
  "_tags":          ["array of strings"]
}
```

### Sample Input → Normalized Output

**4.1 Firewall/Syslog**
```
<134>Aug 20 12:44:56 fw01 vendor=demo product=ngfw action=deny src=10.0.1.10 dst=8.8.8.8 spt=5353 dpt=53 proto=udp msg=DNS blocked policy=Block-DNS
```
→ parse `src`, `dst`, `spt`, `dpt`, `proto`, `action`, `vendor`, `product`, `rule_name` แล้วใส่ schema

**4.2 Network Router Syslog**
```
<190>Aug 20 13:01:02 r1 if=ge-0/0/1 event=link-down mac=aa:bb:cc:dd:ee:ff reason=carrier-loss
```

**4.3 HTTP API (POST /ingest)**
```json
{
  "tenant": "demoA",
  "source": "api",
  "event_type": "app_login_failed",
  "user": "alice",
  "ip": "203.0.113.7",
  "reason": "wrong_password",
  "@timestamp": "2025-08-20T07:20:00Z"
}
```

**4.4 CrowdStrike (sample JSON)**
```json
{
  "tenant": "demoA",
  "source": "crowdstrike",
  "event_type": "malware_detected",
  "host": "WIN10-01",
  "process": "powershell.exe",
  "severity": 8,
  "sha256": "abc...",
  "action": "quarantine",
  "@timestamp": "2025-08-20T08:00:00Z"
}
```

**4.5 AWS CloudTrail (sample)**
```json
{
  "tenant": "demoB",
  "source": "aws",
  "cloud": { "service": "iam", "account_id": "123456789012", "region": "ap-southeast-1" },
  "event_type": "CreateUser",
  "user": "admin",
  "@timestamp": "2025-08-20T09:10:00Z",
  "raw": { "eventName": "CreateUser", "requestParameters": { "userName": "temp-user" } }
}
```

**4.6 Microsoft 365 Audit (sample)**
```json
{
  "tenant": "demoB",
  "source": "m365",
  "event_type": "UserLoggedIn",
  "user": "bob@demo.local",
  "ip": "198.51.100.23",
  "status": "Success",
  "workload": "Exchange",
  "@timestamp": "2025-08-20T10:05:00Z"
}
```

**4.7 Microsoft AD / Windows Security (EventID 4625)**
```json
{
  "tenant": "demoA",
  "source": "ad",
  "event_id": 4625,
  "event_type": "LogonFailed",
  "user": "demo\\eve",
  "host": "DC01",
  "ip": "203.0.113.77",
  "logon_type": 3,
  "@timestamp": "2025-08-20T11:11:11Z"
}
```

---

## 4. Components & Tech Stack (แนะนำ — เลือกได้เอง)

| Layer | แนะนำ |
|---|---|
| Collector / Ingest | Vector / Fluent Bit / Logstash / Custom (Node/Go/Python) |
| Storage / Index | OpenSearch / ClickHouse / PostgreSQL (+JSONB/GIN) / Elasticsearch |
| Backend API | FastAPI / Express / Go Fiber / NestJS |
| UI / Dashboard | React/Vue + Chart library หรือ OpenSearch Dashboards / Grafana |
| Packaging | Docker Compose (Appliance) + Cloud VM/Container (SaaS) |

---

## 5. Backend API

### 5.1 Ingest Endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/ingest` | รับ JSON log (single หรือ batch array) |
| UDP/TCP 514 | Syslog listener | รับ Syslog จาก Firewall/Network |
| POST | `/ingest/batch` | อัปโหลด / ชี้ไฟล์ JSON batch (AWS, M365, AD) |

### 5.2 Search / Query Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/logs` | query logs พร้อม filter |
| Query params | `tenant`, `source`, `event_type`, `start`, `end`, `page`, `size` | filter ตามเวลา/tenant/source |

### 5.3 Alert Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/alerts` | ดึง alert rules ทั้งหมด |
| POST | `/alerts` | สร้าง alert rule ใหม่ |
| GET | `/alerts/triggered` | ดูการแจ้งเตือนที่ trigger แล้ว |

### 5.4 Auth Endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/auth/login` | login รับ JWT token |
| GET | `/auth/me` | ดู profile ของตัวเอง |

---

## 6. Authentication & Authorization (AuthN/AuthZ)

- ใช้ **JWT** หรือ session token
- มีอย่างน้อย **2 roles**: `Admin` และ `Viewer`
  - **Admin**: เห็นและจัดการ log ทุก tenant, จัดการ alert rules, จัดการ users
  - **Viewer**: เห็นเฉพาะ tenant ของตน เท่านั้น
- **Multi-tenant**: แยก log ตาม `tenant` field (parameter หรือ header/claim)
- ทุก API endpoint ต้องมี auth middleware ตรวจ token และ role

---

## 7. Dashboard / UI

หน้าหลักที่ต้องมี:

| หน้า | รายละเอียด |
|---|---|
| Dashboard | Top N IP / User / EventType (bar chart หรือ table), Timeline กราฟ (line/bar), Filter ตามช่วงเวลา / tenant / source |
| Log Search | ตาราง log พร้อม pagination, filter, full-text search |
| Alert Rules | ดู/สร้าง/แก้ไข alert rule |
| Alert Triggered | รายการแจ้งเตือนที่เกิดขึ้นแล้ว |
| Login | หน้า login สำหรับ AuthN |

---

## 8. Alerting

- ต้องมีอย่างน้อย **1 กฎ** เช่น:
  > **Login Failed Brute-Force**: เมื่อ `event_type=LogonFailed` หรือ `app_login_failed` จาก `src_ip` เดียวกัน เกิน N ครั้ง ภายใน 5 นาที
- เมื่อ trigger: แสดงในหน้า Alert UI **และ/หรือ** ส่ง Webhook/Email
- เก็บ alert triggered event ไว้ใน storage

---

## 9. Deployment

### 9.1 Appliance Mode (Docker Compose)

- รันได้บนเครื่องเดียว / VM เดียว
- Minimum spec: Ubuntu 22.04+, 4 vCPU, 8 GB RAM, 40 GB Disk
- เปิด port: `80`, `443`, `514` (Syslog), และ port อื่นที่จำเป็น
- คำสั่งเริ่มต้น: `make up` หรือ `docker compose up -d` หรือ `./run.sh`
- ต้องมี `docs/setup_appliance.md` อธิบายขั้นตอนละเอียด

### 9.2 SaaS / Cloud Mode

- รันบน Cloud (VM หรือ Container) มี URL ให้เข้าใช้จากภายนอก
- ต้องเปิด **HTTPS** (TLS) — Self-signed certificate ยอมรับได้ถ้าอธิบายขั้นตอนชัดเจน
- ต้องมี `docs/setup_saas.md` อธิบายขั้นตอนละเอียด

---

## 10. Data Retention

- เก็บข้อมูลอย่างน้อย **7 วัน**
- ต้องมี mechanism ลบ / rollover / partition ข้อมูลเก่า (เลือกอย่างใดอย่างหนึ่ง)

---

## 11. Required Deliverables

1. **Git Repository** ที่มี:
   - `/docs/architecture.md` — แผนภาพ + อธิบาย data flow / tenant model
   - `/docs/setup_appliance.md` — ขั้นตอนติดตั้ง Appliance ละเอียด
   - `/docs/setup_saas.md` — ขั้นตอนติดตั้ง SaaS ละเอียด
   - `docker-compose.yml` (และ/หรือ Helm chart) + init/seed scripts
   - `.env.example` — ค่าที่ต้องตั้งทั้งหมด
   - `Makefile` หรือ `run.sh`
   - `/samples/` — log ตัวอย่าง + script ส่ง (`send_syslog.sh`, `post_logs.py`)
   - `/backend/`, `/frontend/`, `/ingest/` โค้ดพร้อม README
   - `/tests/` — อย่างน้อย 2–3 test cases

2. **Demo Video 30 นาที**: อธิบายสถาปัตยกรรม + เดโม ingest → search → dashboard → alert

3. **URL Demo (SaaS)** และ/หรือ ไฟล์ OVA / วิธี spin-up Appliance

4. **Postman / Insomnia Collection** สำหรับ API ingest/search (ถ้ามี)

---

## 12. Acceptance Checklist (สิ่งที่กรรมการจะทดสอบ)

- [ ] เปิดระบบ Appliance mode ตามเอกสาร (1 คำสั่งหรือไม่กี่ขั้น)
- [ ] ส่ง Syslog ตัวอย่าง (เช่น `logger` / `nc`) แล้วเห็นใน UI ภายใน 1 นาที
- [ ] เรียก `POST /ingest` ด้วย JSON ตัวอย่าง แล้วค้นหาได้
- [ ] อัปโหลด / ชี้ไฟล์ sample AWS / M365 / AD แล้วระบบ normalize ได้
- [ ] Dashboard แสดง Top N, Timeline, Filter by tenant/source/time ทำงาน
- [ ] สร้าง Alert rule ตัวอย่างและเห็นการแจ้งเตือน (UI / Email / Webhook)
- [ ] ทดสอบ RBAC: ผู้ใช้ Viewer เห็นเฉพาะ tenant ของตน
- [ ] SaaS mode เข้าใช้งานผ่าน HTTPS ได้

---

## 13. Scoring (100 คะแนน)

| หมวด | รายละเอียด | คะแนน |
|---|---|---|
| สถาปัตยกรรม & เอกสาร | ความชัดเจน, แบบแผน, เหตุผลการเลือกเทคโนโลยี | 15 |
| Ingestion | รองรับหลายแหล่ง/โปรโตคอล, ความเสถียร, การจำลอง | 20 |
| Normalization/Schema | ออกแบบ schema และ mapping ได้เหมาะสม | 10 |
| Storage & Query | ค้นหาเร็ว/ถูกต้อง, index/partition ดี | 10 |
| Dashboard/UI | ใช้งานง่าย, มีกราฟ/ตาราง/filter จำเป็น | 10 |
| Alerting | มีกฎอย่างน้อย 1 แบบ + แจ้งเตือนสำเร็จ | 10 |
| Security | AuthN/AuthZ, RBAC, TLS ขั้นต่ำ | 10 |
| Deployment | Appliance + SaaS ใช้งานได้จริง | 10 |
| Tests & DX | ตัวอย่างทดสอบ, script/Makefile, .env.example | 5 |
| **รวม** | | **100** |

**คะแนนพิเศษ (สูงสุด +10):** Multi-tenant จริง (แยก index/table), Enrichment (reverse DNS, GeoIP), CI/CD, IaC (Terraform/Helm), Observability (metrics/trace), Hardening

**ผ่านขั้นต่ำ:** 60 คะแนน  
**Strong Hire:** ≥ 85 คะแนน พร้อมอธิบายเหตุผลการออกแบบได้ชัดเจน

---

## 14. Nice-to-Have (ไม่บังคับ แต่ได้คะแนนพิเศษ)

- Multi-tenant จริง: แยก index / table ต่อ tenant, RBAC ราย field/tenant
- Enrichment ขณะ ingest: reverse DNS, GeoIP lookup
- CI/CD: GitHub Actions หรือเทียบเท่า
- IaC: Terraform / Helm chart
- Unit / Integration tests
- Observability: metrics, distributed tracing

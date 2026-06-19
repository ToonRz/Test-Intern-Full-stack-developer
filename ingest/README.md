# Ingest — Log Management System

Ingest/Collector layer per `spec.md` §2 (Log Sources) และ §3 (Normalized Schema)

## Overview

โปรเจคนี้ฝัง ingest ไว้ใน backend เลย (Python async — syslog UDP/TCP listener + FastAPI routes)
`ingest/normalizers/` เป็น standalone normalizer modules ที่ใช้ได้ทั้ง:
- ใน backend (`backend/normalizer/core.py` dispatch → `ingest/normalizers/*.py`)
- เป็น standalone script (เช่น CLI ingest จาก batch file ตรง ๆ)

## Log Sources Supported

| Source | Protocol / Entry Point | Status | Normalizer |
|---|---|---|---|
| Firewall / Network | Syslog UDP/TCP `:514` (RFC3164 + RFC5424 + octet-counted TCP) | REAL | `ingest/normalizers/syslog_normalizer.py` |
| API | HTTP `POST /api/v1/ingest` (single JSON or array) | REAL | `ingest/normalizers/api_normalizer.py` |
| AWS (CloudTrail) | `POST /api/v1/ingest/batch` ด้วย `source=aws` | Sample | `ingest/normalizers/aws_normalizer.py` |
| Microsoft 365 (Unified Audit) | `POST /api/v1/ingest/batch` ด้วย `source=m365` | Sample | `ingest/normalizers/m365_normalizer.py` |
| Microsoft AD (EventID 4625) | `POST /api/v1/ingest/batch` ด้วย `source=ad` | Sample | `ingest/normalizers/ad_normalizer.py` |
| CrowdStrike Falcon | `POST /api/v1/ingest/batch` ด้วย `source=crowdstrike` | Sample | `ingest/normalizers/crowdstrike_normalizer.py` |

ตาม spec §2: อย่างน้อย **4 แหล่งที่ "ยิงเข้าได้จริง"** — ปัจจุบันยิงได้จริง 4 แหล่ง:
1. Syslog (UDP/TCP) — `make send-syslog`
2. HTTP API — `make send-sample`
3. JSON batch (AWS/M365/AD/CrowdStrike) — `samples/post_logs.py`
4. **Simulator** — `samples/post_logs.py` รันซ้ำเป็น continuous traffic generator

## Normalization Flow

ทุก log ผ่าน `backend/normalizer/core.py:normalize_log(log_data, source, tenant)` ก่อน save:
1. **Dispatch ตาม `source`** — เลือก per-source normalizer
2. **Map fields** → central schema (spec §3)
3. **Defaults** — เติม `tenant`, `source`, `@timestamp` (ถ้าขาด)
4. **Hand off** → enrichment (GeoIP + rDNS) → save (Postgres) → background alert eval

## Central Schema (spec §3)

ทุก log normalize เข้า schema นี้ก่อนเก็บ:

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

## Sample Input → Normalized Output

**Firewall/Syslog (spec §4.1):**
```
<134>Aug 20 12:44:56 fw01 vendor=demo product=ngfw action=deny src=10.0.1.10 dst=8.8.8.8 spt=5353 dpt=53 proto=udp msg="DNS blocked" policy=Block-DNS
```
→ parse `vendor`, `product`, `action`, `src`, `dst`, `spt`, `dpt`, `proto`, `policy` (→ `rule_name`)

**HTTP API (spec §4.3):**
```json
{
  "tenant": "demoA",
  "source": "api",
  "event_type": "app_login_failed",
  "user": "alice",
  "ip": "203.0.113.7",
  "reason": "wrong_password"
}
```
→ map `ip` → `src_ip`, infer `action=login`, severity จาก event_type

**CrowdStrike (spec §4.4):**
```json
{
  "tenant": "demoA",
  "source": "crowdstrike",
  "event_type": "malware_detected",
  "host": "WIN10-01",
  "process": "powershell.exe",
  "severity": 8,
  "action": "quarantine",
  "@timestamp": "2025-08-20T08:00:00Z"
}
```
→ direct mapping + derive `vendor=crowdstrike`, `product=falcon`

ดูตัวอย่างครบทั้ง 6 source ใน `samples/`:
- `sample_firewall.log`
- `sample_aws_cloudtrail.json`
- `sample_m365.json`
- `sample_ad_4625.json`
- `sample_crowdstrike.json`
- (API ไม่มี file — ส่งผ่าน `samples/post_logs.py`)

## Usage

### ผ่าน Backend (production)

Backend รับ ingest ตรงจาก:
- `POST http://localhost:8000/api/v1/ingest` — single or array
- `POST http://localhost:8000/api/v1/ingest/batch` — file batch
- Syslog UDP/TCP `localhost:514`

### Standalone (ingest/normalizers/*.py)

```python
from ingest.normalizers.aws_normalizer import normalize_aws_log

raw_event = {"eventName": "CreateUser", "userIdentity": {"userName": "admin"}, ...}
normalized = normalize_aws_log(raw_event, tenant="demoB", timestamp="2025-08-20T09:10:00Z")
```

แต่ละ module export `normalize_<source>_log(data, tenant, timestamp) -> NormalizedLog`

### ผ่าน Helper Scripts

```bash
make send-syslog          # ส่ง sample syslog 1 บรรทัดเข้า localhost:514
make send-sample          # ส่ง sample HTTP log เข้า /ingest
python samples/post_logs.py http://localhost:8000/api/v1/ingest    # POST หลาย events
python samples/post_logs.py http://localhost:8000/api/v1/ingest --loop   # continuous
```

## Alternative Collectors (spec §4 — optional)

`spec.md` §4 แนะนำ Vector / Fluent Bit / Logstash เป็นทางเลือก
ถ้าจะใช้แทน Python listener ในตัว สามารถ forward มาที่ `POST /api/v1/ingest` ได้ตรง ๆ:

**Vector (`vector.toml`):**
```toml
[sources.firewall]
type = "socket"
address = "0.0.0.0:514"
mode = "udp"

[sinks.api]
type = "http"
inputs = ["firewall"]
uri = "http://backend:8000/api/v1/ingest"
method = "post"
encoding.codec = "json"
```

**Fluent Bit (`fluent-bit.conf`):**
```
[INPUT]
    Name              syslog
    Listen            0.0.0.0
    Port              514
    Mode              udp

[OUTPUT]
    Name              http
    Match             *
    Host              backend
    Port              8000
    URI               /api/v1/ingest
    Format            json
```

## Requirements

```bash
pip install -r ingest/requirements.txt
```

(Backend มี deps ครบอยู่แล้ว — `ingest/requirements.txt` ใช้เฉพาะตอนรัน standalone)

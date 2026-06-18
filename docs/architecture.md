# Architecture - Log Management System

## Overview

Log Management System เป็นระบบจัดการ logs ที่รองรับหลายแหล่งข้อมูล ออกแบบมาสำหรับ 2 deployment modes:
- **Appliance**: รันบนเครื่องเดียว/VM เดียว (Docker Compose)
- **SaaS/Cloud**: รันบน Cloud มี URL สำหรับเข้าใช้งานจากภายนอก

## System Architecture

```
                    ┌─────────────────────────────────────────────┐
                    │              Log Management System          │
                    └─────────────────────────────────────────────┘
                                              │
        ┌─────────────────────────────────────┼─────────────────────────────────────┐
        │                                     │                                     │
        ▼                                     ▼                                     ▼
┌───────────────┐                    ┌───────────────┐                    ┌───────────────┐
│  Ingest       │                    │   Backend     │                    │   Frontend    │
│  (Collector)  │                    │   (FastAPI)   │                    │   (React)     │
│               │                    │               │                    │               │
│ • Syslog 514  │ ──────────────────▶│ • Normalize   │ ◀─────────────────│ • Dashboard   │
│ • HTTP /ingest│                    │ • Store       │                    │ • Log Search  │
│ • Batch files │                    │ • Auth/RBAC   │                    │ • Alerts      │
└───────────────┘                    │ • Alert Engine│                    └───────────────┘
                                      └───────┬───────┘
                                              │
                                              ▼
                                      ┌───────────────┐
                                      │  PostgreSQL   │
                                      │  + JSONB/GIN  │
                                      │  (Storage)    │
                                      └───────────────┘
```

## Data Flow

```
Log Sources                    Ingest Layer                    Backend
─────────────────────────────────────────────────────────────────────────

Firewall/Network              Syslog UDP/TCP 514
Syslog message ──────────────▶ Parser ─────▶ Normalizer ────▶ Store
                                    │
HTTP API Clients
POST /ingest ─────────────────▶ Parser ─────▶ Normalizer ────▶ Store
JSON body                       │
                                   │
Batch Files (AWS/M365/AD)          │
File upload ───────────▶ Parser ──▶ Normalizer ────▶ Store
                              │
                              ▼
                    Alert Engine (Brute-Force)
                              │
                              ▼
                    Triggered Alerts Store
```

## Tech Stack (per spec.md section 4)

| Layer | Technology | Rationale |
|---|---|---|
| Collector/Ingest | Custom Python (syslog listener) + Backend | Simple, works out of box |
| Storage | PostgreSQL + JSONB/GIN | Reliable, good JSON support, ACID |
| Backend API | FastAPI | Modern, fast, automatic docs |
| Frontend | React + Recharts | Popular, good chart support |
| Deployment | Docker Compose | Easy Appliance mode |

## Normalized Schema

All logs are normalized to the central schema per spec.md section 3:

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

## Multi-Tenant Model

Per spec.md section 6:
- Logs are isolated by `tenant` field
- JWT tokens contain `tenant` claim
- RBAC:
  - **Admin**: Sees all tenants, full access
  - **Viewer**: Sees only their assigned tenant

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

## Alerting Flow

Per spec.md section 8:

```
Incoming Log
     │
     ▼
┌─────────────────┐
│ Alert Engine    │
│                 │
│ Check: Is       │
│ event_type in   │
│ alert rule?     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐     ┌─────────────────┐
│ Count by src_ip │────▶│ Threshold       │
│ within window   │     │ exceeded?       │
└─────────────────┘     └────────┬────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │ Trigger Alert           │
                    │ • Store in DB           │
                    │ • Send Webhook/Email   │
                    └─────────────────────────┘
```

## Directory Structure

```
/
├── docker-compose.yml      # All services
├── .env.example            # Environment variables
├── Makefile               # Commands
├── backend/
│   ├── main.py            # FastAPI app
│   ├── routers/           # API endpoints
│   ├── models/            # Pydantic models
│   ├── auth/              # JWT auth
│   ├── normalizer/        # Log normalization
│   ├── services/          # Business logic
│   ├── storage/           # Database
│   └── Dockerfile
├── frontend/
│   ├── src/pages/         # React pages
│   ├── src/components/    # React components
│   └── Dockerfile
├── ingest/
│   └── normalizers/       # Log source normalizers
├── samples/               # Sample logs & scripts
├── tests/                 # Test cases
├── docs/                  # Documentation
│   ├── architecture.md
│   ├── setup_appliance.md
│   └── setup_saas.md
└── scripts/
    ├── init-db.sql
    └── retention.py
```

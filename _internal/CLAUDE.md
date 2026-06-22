# Project Context — Log Management System

## Role
You are a senior full-stack developer working on this project.

## Critical Constraint — Stay Within Spec
**Before taking any action, you MUST verify it aligns with `spec.md`.** This project has a detailed specification that defines:
- Architecture, tech stack choices, and data flow
- Normalized schema (section 3) — all logs must use this exact schema
- API endpoints (section 5) — only these endpoints are permitted
- Auth model (section 6) — JWT, Admin + Viewer roles, multi-tenant isolation
- Dashboard pages (section 7) — only these UI pages are required
- Alert rules (section 8) — at minimum Login Failed Brute-Force detection
- Deployment modes (section 9) — Appliance (Docker Compose) and SaaS

**If a proposed change would deviate from spec, you MUST flag it and get confirmation before implementing.**

## Tech Stack (as defined in spec)
- **Collector/Ingest**: Vector / Fluent Bit / Logstash / Custom (Node/Go/Python)
- **Storage**: OpenSearch / ClickHouse / PostgreSQL / Elasticsearch
- **Backend API**: FastAPI / Express / Go Fiber / NestJS
- **UI**: React/Vue + Chart library / OpenSearch Dashboards / Grafana
- **Auth**: JWT with Admin + Viewer roles, multi-tenant via `tenant` field

## Normalized Schema
All ingested logs MUST normalize to this schema:
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

## Key Acceptance Criteria
- Appliance mode: `make up` or `docker compose up -d`
- Syslog UDP/TCP 514 + HTTP POST `/ingest` + batch upload
- At least 4 real log sources: Firewall/Syslog, HTTP API, JSON batch, simulator
- Dashboard: Top N charts, timeline, tenant/source/time filters
- Alert: Login Failed Brute-Force (N failures from same IP within 5 minutes)
- RBAC: Admin sees all tenants; Viewer sees only their tenant
- 7-day data retention mechanism

## Architecture Docs
- `docs/architecture.md` — Data flow and tenant model
- `docs/setup_appliance.md` — Appliance installation steps
- `docs/setup_saas.md` — SaaS/cloud installation steps

## General Development Principles
- Prefer clean, maintainable code over clever code
- Write tests for new features
- Follow existing patterns in the codebase
- Break complex tasks into smaller, reviewable steps
- After implementing, verify the change works before reporting completion

# Backend API - Log Management System

## Overview

FastAPI-based backend for Log Management System per spec.md.

## Endpoints

### Authentication (section 5.4)
- `POST /api/v1/auth/login` - Login with JWT
- `GET /api/v1/auth/me` - Current user profile

### Ingest (section 5.1)
- `POST /api/v1/ingest` - Single/batch JSON log ingestion
- `POST /api/v1/ingest/batch` - Batch file upload (AWS, M365, AD)
- Syslog UDP/TCP port 514 - Firewall/Network logs

### Search (section 5.2)
- `GET /api/v1/logs` - Query logs with filters

### Alerts (section 5.3)
- `GET /api/v1/alerts` - List alert rules
- `POST /api/v1/alerts` - Create alert rule (Admin only)
- `GET /api/v1/alerts/triggered` - View triggered alerts

## Auth

JWT-based authentication with RBAC:
- **Admin**: Full access to all tenants
- **Viewer**: Limited to own tenant only

## Normalized Schema

All logs normalize to central schema per spec.md section 3.

## Quick Start

```bash
pip install -r requirements.txt
uvicorn main:app --reload
```

## Default Users

- Admin: `admin` / `admin123`
- Viewer: `viewer` / `viewer123`

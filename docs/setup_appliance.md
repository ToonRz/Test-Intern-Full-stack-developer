# Setup Guide - Appliance Mode

## Overview

Appliance mode รันทุกอย่างบนเครื่องเดียว/VM เดียวใช้ Docker Compose

## Requirements

- Ubuntu 22.04+ (แนะนำ) หรือ OS ที่รองรับ Docker
- Minimum spec:
  - 4 vCPU
  - 8 GB RAM
  - 40 GB Disk
- Docker & Docker Compose ติดตั้งแล้ว

## Quick Start

### 1. Clone Repository

```bash
git clone <repository-url>
cd Test-Intern-Full-stack-developer
```

### 2. Setup Environment

```bash
# Copy environment file
cp .env.example .env

# Edit .env with your settings (or use defaults for testing)
```

### 3. Start Services

```bash
# Using Makefile (recommended)
make up

# Or using docker compose directly
docker compose up -d
```

### 4. Verify Services

```bash
# Check status
make ps

# View logs
make logs
```

Expected output:
```
NAME                IMAGE               SERVICE
-----------------------------------------------------
app-backend-1       app-backend         backend
app-frontend-1      app-frontend        frontend
app-nginx-1         nginx:alpine        nginx
app-postgres-1      postgres:15-alpine  postgres
app-redis-1         redis:7-alpine      redis
```

## Access Services

หลังจาก start สำเร็จ:

| Service | URL | Default Credentials |
|---|---|---|
| Frontend | http://localhost:3000 | admin/admin123 |
| Backend API | http://localhost:8000 | - |
| API Docs | http://localhost:8000/docs | - |

## Test Ingestion

### Send Syslog

```bash
# Using sample script
make send-syslog

# Or manually with netcat
echo '<134>Aug 20 12:44:56 fw01 vendor=demo product=ngfw action=deny src=10.0.1.10 dst=8.8.8.8 spt=5353 dpt=53 proto=udp msg=DNS blocked policy=Block-DNS' | nc -u -w1 localhost 514
```

### Send HTTP POST

```bash
# Using sample script
make send-sample

# Or manually with curl
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

### Upload Batch Files

```bash
# AWS CloudTrail
curl -X POST http://localhost:8000/api/v1/ingest/batch \
  -H "Content-Type: application/json" \
  -d '{
    "source": "aws",
    "tenant": "demoB",
    "files": [{"logs": [{"tenant": "demoB", "source": "aws", "event_type": "CreateUser", "user": "admin", "@timestamp": "2025-08-20T09:10:00Z"}]}]
  }'
```

## Test Dashboard

1. เปิด http://localhost:3000
2. Login: `admin` / `admin123`
3. ไปที่ Dashboard - ควรเห็น logs ที่ส่งเข้าไป
4. ไปที่ Log Search - ลอง search
5. ไปที่ Alert Rules - ดู rules
6. ไปที่ Triggered - ดู alerts ที่ triggered

## Stop Services

```bash
make down
```

## Clean Up

```bash
# Remove containers and volumes
make clean
```

## Troubleshooting

### Services won't start

```bash
# Check Docker is running
docker ps

# Check logs
docker compose logs
```

### Cannot connect to backend

```bash
# Check backend is healthy
curl http://localhost:8000/health
```

### Database connection issues

```bash
# Check postgres is ready
docker compose exec postgres pg_isready -U postgres

# Reinitialize database
make init
```

### Syslog not received

```bash
# Check port 514 is listening
sudo netstat -ulnp | grep 514

# Send test syslog
logger -n localhost -P 514 "test message"
```

## Default Users

| Username | Password | Role | Tenant |
|---|---|---|---|
| admin | admin123 | Admin | * (all) |
| viewer | viewer123 | Viewer | demoA |

## Ports

| Port | Service |
|---|---|
| 80 | Nginx (HTTP) |
| 443 | Nginx (HTTPS - for SaaS mode) |
| 3000 | Frontend (direct) |
| 514 | Syslog UDP |
| 514 | Syslog TCP |
| 5432 | PostgreSQL |
| 6379 | Redis |
| 8000 | Backend API |

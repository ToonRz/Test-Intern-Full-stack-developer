# Setup Guide — SaaS / Cloud Mode

## Overview

SaaS mode รันบน Cloud (VM หรือ Container Service) เปิดให้ external users เข้าผ่าน HTTPS URL
ใช้ Docker Compose stack เดียวกับ Appliance + เพิ่ม domain, Let's Encrypt cert, และ cloud firewall

อ้างอิง: `spec.md` §9.2

## Requirements

- Cloud VM (AWS EC2, GCP Compute, Azure VM) หรือ Container Service
- Domain name (หรือใช้ public IP ชั่วคราว — self-signed ก็ได้)
- Minimum spec (spec §9.2):
  - 4 vCPU
  - 8 GB RAM
  - 40 GB Disk
- Public IPv4 + DNS A record ชี้มาที่ VM
- Docker Engine 24+ และ Docker Compose v2
- Ports ที่ต้องเปิดบน cloud firewall: `80`, `443`, `514/udp`, `514/tcp`, `22` (SSH)

## Architecture

```
                          Internet
                              │
                              ▼
                    ┌─────────────────────┐
                    │   Cloud LB /        │
                    │   Security Group    │
                    │   80, 443, 514      │
                    └─────────┬───────────┘
                              │
                              ▼
              ┌───────────────────────────────────────┐
              │           Cloud VM (public IP)        │
              │                                       │
              │   ┌──────────────────────────────┐    │
              │   │  Nginx (TLS termination)     │    │
              │   │  - HTTPS:443 → backend/      │    │
              │   │    frontend                  │    │
              │   │  - stream UDP/514, TCP/514 → │    │
              │   │    backend syslog listener   │    │
              │   └──────┬──────────────┬────────┘    │
              │          │              │             │
              │          ▼              ▼             │
              │   ┌──────────┐   ┌────────────┐       │
              │   │ Frontend │   │  Backend   │       │
              │   │ (React)  │   │  (FastAPI) │       │
              │   └──────────┘   └─────┬──────┘       │
              │                         │             │
              │                         ▼             │
              │                ┌──────────────────┐   │
              │                │  PostgreSQL      │   │
              │                │  Redis           │   │
              │                └──────────────────┘   │
              └───────────────────────────────────────┘
```

ต่างจาก Appliance mode: เพิ่ม domain + cert จริง + cloud firewall
**Stream block ของ nginx จะ forward syslog (UDP/TCP 514) ผ่านไป backend** — ไม่ต้อง expose backend port 514 ตรงออก internet (ทำได้ แต่ไม่แนะนำ)

## Step-by-Step Setup

### 1. เตรียม Cloud VM

```bash
ssh -i your-key.pem ubuntu@YOUR_VM_IP

sudo apt update && sudo apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker ubuntu
newgrp docker

# Install Docker Compose (v2 plugin)
sudo apt install docker-compose-plugin
docker compose version
```

### 2. ตั้ง Cloud Firewall / Security Group

Inbound rules ที่ต้องเปิด:

| Port | Protocol | Purpose |
|---|---|---|
| 22 | TCP | SSH (admin) |
| 80 | TCP | HTTP → HTTPS redirect |
| 443 | TCP | HTTPS (frontend + API) |
| 514 | UDP | Syslog (จาก firewall/network device) |
| 514 | TCP | Syslog over TCP |

ตัวอย่าง AWS:
```bash
aws ec2 authorize-security-group-ingress \
  --group-id sg-xxxx --protocol tcp --port 22  --cidr 0.0.0.0/0
aws ec2 authorize-security-group-ingress \
  --group-id sg-xxxx --protocol tcp --port 80  --cidr 0.0.0.0/0
aws ec2 authorize-security-group-ingress \
  --group-id sg-xxxx --protocol tcp --port 443 --cidr 0.0.0.0/0
aws ec2 authorize-security-group-ingress \
  --group-id sg-xxxx --protocol udp --port 514 --cidr 0.0.0.0/0
aws ec2 authorize-security-group-ingress \
  --group-id sg-xxxx --protocol tcp --port 514 --cidr 0.0.0.0/0
```

Ubuntu `ufw`:
```bash
sudo ufw allow 22
sudo ufw allow 80
sudo ufw allow 443
sudo ufw allow 514/udp
sudo ufw allow 514/tcp
sudo ufw enable
```

### 3. ตั้ง DNS

```
A   your-domain.com.    →    YOUR_VM_PUBLIC_IP
A   *.your-domain.com.  →    YOUR_VM_PUBLIC_IP   (ถ้าใช้ subdomain อื่น)
```

### 4. Clone Repository

```bash
git clone <repository-url>
cd Test-Intern-Full-stack-developer
```

### 5. ตั้งค่า Environment

```bash
cp .env.example .env
nano .env
```

ค่าที่ต้องตั้งใหม่สำหรับ production:

```bash
# Required — generate one
SECRET_KEY=$(openssl rand -hex 32)

# Production defaults
DEBUG=false
ALLOWED_ORIGINS=https://your-domain.com

# Stronger passwords for seed users (หรือ disable seed หลังสร้าง user จริง)
ADMIN_PASSWORD=<strong-password>
VIEWER_PASSWORD=<strong-password>

# Optional: increase retention
DATA_RETENTION_DAYS=30

# Redis / DB
DATABASE_URL=postgresql+asyncpg://postgres:STRONG_PASS@postgres:5432/logs
REDIS_URL=redis://redis:6379/0
```

### 6. ตั้ง TLS Certificate

มี 2 ตัวเลือก — **แนะนำ Let's Encrypt** สำหรับ production:

#### Option A: Let's Encrypt (แนะนำ — spec §9.2)

```bash
# ติดตั้ง certbot บน host (ไม่ใช่ใน container)
sudo apt install certbot

# ขอ cert (ต้อง point domain มาที่ VM แล้ว + port 80 เปิดอยู่)
sudo certbot certonly --standalone -d your-domain.com

# Copy cert ไป nginx/certs/ ในชื่อที่ nginx.conf คาดไว้
sudo cp /etc/letsencrypt/live/your-domain.com/fullchain.pem nginx/certs/server.crt
sudo cp /etc/letsencrypt/live/your-domain.com/privkey.pem   nginx/certs/server.key
sudo chown $USER:$USER nginx/certs/server.crt nginx/certs/server.key
```

ตั้ง cron auto-renew:
```bash
# Renew + copy ทุก ๆ 2 เดือน
0 3 1 */2 * sudo certbot renew --quiet && \
  sudo cp /etc/letsencrypt/live/your-domain.com/fullchain.pem /path/to/repo/nginx/certs/server.crt && \
  sudo cp /etc/letsencrypt/live/your-domain.com/privkey.pem   /path/to/repo/nginx/certs/server.key && \
  docker compose exec nginx nginx -s reload
```

#### Option B: Self-signed (ทดสอบ / internal เท่านั้น — spec §9.2 อนุญาต)

```bash
make certs
# → สร้าง nginx/certs/server.crt + server.key (365 วัน)
# browser จะเตือน warning — ยอมรับได้สำหรับ dev/internal
```

`scripts/generate-certs.sh` เป็น idempotent — รันซ้ำได้ไม่ทับ cert เดิมถ้ายังไม่หมดอายุ

### 7. Start Services

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f nginx backend
```

`certs-init` one-shot container จะรันก่อน (`generate-certs.sh`) เพื่อ ensure certs มีอยู่
ถ้าใช้ Option A (Let's Encrypt) `certs-init` จะ overwrite — ให้ปิดไว้หรือรัน `make certs` แล้ว comment service นี้ออกใน `docker-compose.yml`

### 8. Verify HTTPS

```bash
# HTTPS test
curl -I https://your-domain.com

# API health
curl -fsS https://your-domain.com/api/v1/health

# OpenAPI
curl -fsS https://your-domain.com/api/v1/docs
```

ถ้าใช้ self-signed:
```bash
curl -kI https://your-domain.com
```

## ให้ External Devices ส่ง Syslog

จาก Firewall / Network device:

```
Syslog server: your-domain.com
Port:          514
Protocol:      UDP (default) หรือ TCP
Facility:      local0-local7
Severity:      all (info+)
```

ทดสอบจากเครื่องใดก็ได้:
```bash
echo '<134>Aug 20 12:44:56 fw01 vendor=demo product=ngfw action=deny src=10.0.1.10 dst=8.8.8.8 spt=5353 dpt=53 proto=udp msg="DNS blocked" policy=Block-DNS' \
  | nc -u -w1 your-domain.com 514
```

ทดสอบ TCP:
```bash
echo '<134>test from tcp>' | nc -w1 your-domain.com 514
```

## Production Hardening

### Secrets

```bash
# ห้าม commit .env — ใช้ cloud secret manager แทน
# AWS SSM Parameter Store / Secrets Manager
# GCP Secret Manager
# Azure Key Vault
```

### Database

- เปลี่ยน `POSTGRES_PASSWORD` ใน `docker-compose.yml`
- Backup daily:
  ```bash
  docker compose exec -T postgres pg_dump -U postgres logs | \
    gzip > backup-$(date +%Y%m%d).sql.gz
  ```
- ใช้ managed Postgres (AWS RDS / Cloud SQL) สำหรับ HA — แก้ `DATABASE_URL` ใน `.env`

### Network

- ปิด port 5432 (postgres) และ 6379 (redis) จาก internet — เปิดเฉพาะ 80/443/514
- ใช้ cloud LB + private subnet สำหรับ backend ถ้าต้องการ HA
- ตั้ง rate limit ที่ cloud LB อีกชั้น — nginx มี rate limit ในตัวแล้ว (`/api/` 100r/m, `/api/v1/auth/login` 10r/m)

### Observability

- `/health` บน backend — ใช้ healthcheck ได้
- `/metrics` — gated ไว้เฉพาะ internal network (ดูใน `nginx/nginx.conf`)
- OpenTelemetry OTLP endpoint — ตั้งใน `.env` (`OTEL_EXPORTER_OTLP_ENDPOINT`)
- ดู `docs/observability-dashboard.md` สำหรับแนวทาค monitor

### Backups & Retention

```bash
# Backup อัตโนมัติ (cron)
0 2 * * * cd /path/to/repo && docker compose exec -T postgres pg_dump -U postgres logs | gzip > /backups/logs-$(date +\%Y\%m\%d).sql.gz

# Retention (ลบ log เก่ากว่า N วัน — spec §10)
0 3 * * * cd /path/to/repo && docker compose exec -T backend python -m scripts.retention --days ${DATA_RETENTION_DAYS:-7}
```

## Scaling

| Concern | Single VM | Scaled |
|---|---|---|
| Ingest throughput | ~5k logs/sec | แยก ingest nodes + load balancer ที่ :514 |
| Backend API | 1 instance | หลาย replicas หลัง nginx/cloud LB |
| Storage | Postgres local volume | Managed Postgres + read replica |
| Cache | Redis local | Managed Redis / ElastiCache |

## Troubleshooting

### ไม่ติดต่อจากภายนอก

```bash
# ตรวจ cloud firewall
aws ec2 describe-security-groups --group-ids sg-xxxx

# ตรวจ OS firewall
sudo ufw status

# ตรวจ VM public IP
curl ifconfig.me

# ทดสอบ port จาก local
nc -zv YOUR_VM_IP 443
nc -zuv YOUR_VM_IP 514
```

### TLS cert issues

```bash
# ดู cert ปัจจุบัน
openssl x509 -in nginx/certs/server.crt -text -noout

# Regenerate (self-signed)
make certs

# Let's Encrypt renew
sudo certbot renew --dry-run
```

### Backend crashes / 502 Bad Gateway

```bash
docker compose logs backend
docker compose restart backend
curl -fsS http://localhost:8000/health   # จากใน VM
```

### Syslog ไม่เข้า

```bash
# ตรวจว่า nginx stream block listen
docker compose exec nginx nginx -T 2>&1 | grep -A3 "listen 514"

# ตรวจว่า backend syslog listener ขึ้น
docker compose logs backend | grep -i syslog

# ทดสอบจาก VM เอง
nc -zuv localhost 514
```

### CORS error

ถ้า frontend เรียก API แล้วเจอ CORS:
- ตั้ง `ALLOWED_ORIGINS=https://your-domain.com` ใน `.env`
- Restart backend: `docker compose restart backend`

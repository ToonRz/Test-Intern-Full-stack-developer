# Setup Guide - SaaS/Cloud Mode

## Overview

SaaS mode รันบน Cloud (VM หรือ Container) มี URL สำหรับเข้าใช้งานจากภายนอก พร้อม HTTPS

## Requirements

- Cloud VM (AWS EC2, GCP Compute, Azure VM) หรือ Container Service
- Domain name (หรือใช้ IP)
- Minimum spec:
  - 4 vCPU
  - 8 GB RAM
  - 40 GB Disk
- Docker & Docker Compose ติดตั้งแล้ว

## Architecture

```
                    ┌─────────────────────────────────────────┐
                    │              Cloud VPC/Security Group     │
                    │                                           │
    ┌───────────────▼───────────────┐                          │
    │        Cloud VM               │                          │
    │                               │                          │
    │  ┌─────────┐  ┌─────────────┐ │     ┌─────────────────┐  │
    │  │  Nginx  │  │  Backend    │ │     │   PostgreSQL    │  │
    │  │  (TLS)  │──│  FastAPI    │ │     │   (Internal)   │  │
    │  └────┬────┘  └──────┬──────┘ │     └────────┬────────┘  │
    │       │              │            │         │           │
    │  ┌────▼────┐  ┌──────▼──────┐    │         │           │
    │  │Frontend │  │   Ingest    │    └─────────┼─────────┘  │
    │  │ (React) │  │ (Syslog:514)│────────────────           │
    │  └─────────┘  └─────────────┘                            │
    └───────────────────────────────────────────────────────────┘
                         │
                         ▼
              ┌─────────────────────────┐
              │    External Users       │
              │  HTTPS:443 / Syslog:514 │
              └─────────────────────────┘
```

## Step-by-Step Setup

### 1. Prepare Cloud VM

```bash
# SSH to your VM
ssh -i your-key.pem ubuntu@your-vm-ip

# Update system
sudo apt update && sudo apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker ubuntu

# Install Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose
```

### 2. Configure Firewall

```bash
# Open required ports
sudo ufw allow 22    # SSH
sudo ufw allow 80     # HTTP
sudo ufw allow 443    # HTTPS
sudo ufw allow 514    # Syslog
sudo ufw allow 514/udp
sudo ufw enable
```

For AWS Security Group:
- Inbound: 22 (SSH), 80 (HTTP), 443 (HTTPS), 514 (Syslog UDP/TCP)

### 3. Clone Repository

```bash
git clone <repository-url>
cd Test-Intern-Full-stack-developer
```

### 4. Generate TLS Certificates

```bash
# Create certificates directory
mkdir -p nginx/certs

# Generate self-signed certificate (for testing)
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout nginx/certs/server.key \
  -out nginx/certs/server.crt \
  -subj "/CN=your-domain-or-ip"

# For production, use Let's Encrypt:
# certbot --nginx -d your-domain.com
```

### 5. Configure Environment

```bash
# Copy and edit environment
cp .env.example .env
nano .env

# Key settings for production:
# SECRET_KEY=<generate-strong-random-key>
# DEBUG=false
# DATA_RETENTION_DAYS=30
```

### 6. Update Nginx Config for SaaS

สร้าง nginx.conf ใหม่:

```nginx
events {
    worker_connections 1024;
}

http {
    upstream backend {
        server backend:8000;
    }

    upstream frontend {
        server frontend:3000;
    }

    server {
        listen 80;
        server_name _;
        return 301 https://$host$request_uri;
    }

    server {
        listen 443 ssl;
        server_name _;

        ssl_certificate /etc/nginx/certs/server.crt;
        ssl_certificate_key /etc/nginx/certs/server.key;

        # Frontend
        location / {
            proxy_pass http://frontend;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
        }

        # Backend API
        location /api/ {
            proxy_pass http://backend;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-Proto $scheme;
        }

        # Syslog (TCP)
        location /syslog {
            proxy_pass http://backend:8000;
            proxy_set_header Host $host;
            proxy_connect_timeout 60s;
            proxy_send_timeout 60s;
        }
    }
}
```

### 7. Start Services

```bash
# Start in detached mode
docker compose up -d

# Check status
docker compose ps
```

### 8. Verify HTTPS

```bash
# Test HTTPS (self-signed will show warning)
curl -k https://localhost/

# Test API
curl -k https://localhost/api/v1/health
```

## DNS Configuration

For production with domain:

1. Create DNS A record:
   ```
   your-domain.com.    A    YOUR_VM_IP
   ```

2. Update nginx.conf with your domain

3. Consider using Let's Encrypt:
   ```bash
   sudo apt install certbot python3-certbot-nginx
   sudo certbot --nginx -d your-domain.com
   ```

## External Log Sources

### Configure Firewall to Send Syslog

```bash
# On firewall/network device, set:
# Syslog server: YOUR_VM_IP:514
# Protocol: UDP or TCP
```

### Send Test Logs Remotely

```bash
# From any machine
echo '<134>Aug 20 12:44:56 fw01 vendor=demo product=ngfw action=deny src=10.0.1.10 dst=8.8.8.8 spt=5353 dpt=53 proto=udp msg=DNS blocked policy=Block-DNS' | nc -u -w1 YOUR_VM_IP 514
```

## Monitoring

### Check Service Health

```bash
# SSH to VM
ssh ubuntu@your-vm-ip

# Check containers
docker compose ps

# View logs
docker compose logs -f backend

# Check resource usage
docker stats
```

### Setup Log Rotation

```bash
# Add to /etc/logrotate.d/docker-compose
/path/to/docker-compose.yml {
  rotate 7
  daily
  compress
  missingok
}
```

## Backup

### Backup PostgreSQL

```bash
# Create backup script
docker compose exec postgres pg_dump -U postgres logs > backup_$(date +%Y%m%d).sql
```

### Restore

```bash
cat backup_20250101.sql | docker compose exec -T postgres psql -U postgres logs
```

## Scaling Considerations

For high volume:

1. **Separate Ingest Server**: Run Vector/Fluent Bit on separate ingestion nodes
2. **Database Scaling**: Consider managed PostgreSQL (AWS RDS, Cloud SQL)
3. **Load Balancer**: Use cloud LB for multi-backend setup
4. **Caching**: Add Redis for frequent queries

## Security Hardening

1. **Disable root login**: `sudo passwd -l root`
2. **Use SSH keys only**: Edit `/etc/ssh/sshd_config`
3. **Firewall**: Only open needed ports
4. **TLS**: Use proper certificates (Let's Encrypt)
5. **Secrets**: Use strong SECRET_KEY
6. **Regular updates**: `sudo apt update && sudo apt upgrade`

## Troubleshooting

### Cannot connect externally

```bash
# Check firewall
sudo ufw status

# Check cloud security group
aws ec2 describe-security-groups ...

# Test port accessibility
nc -zv YOUR_VM_IP 443
```

### TLS certificate issues

```bash
# Check certificate
openssl x509 -in nginx/certs/server.crt -text -noout

# Regenerate if expired
make init-certs
```

### Backend crashes

```bash
# Check logs
docker compose logs backend

# Common issues:
# - Database not ready: wait for postgres health
# - Memory: increase VM RAM
```

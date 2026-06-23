.PHONY: up down restart logs ps test clean init build certs seed send-syslog send-sample shell-backend shell-postgres docs

# ── Appliance mode (single host, Docker Compose) ─────────────────────────

up: certs
	docker compose up -d --build
	@echo ""
	@echo "Services started. Access:"
	@echo "  - Dashboard (HTTPS): https://localhost"
	@echo "  - Backend API:       https://localhost/api/v1"
	@echo "  - API docs (direct): http://localhost:8000/docs"
	@echo "  - Syslog UDP:      udp://localhost:514"
	@echo "  - Syslog TCP:      tcp://localhost:514"

down:
	docker compose down

restart: down up

logs:
	docker compose logs -f

ps:
	docker compose ps

# Generate self-signed certs into nginx/certs (idempotent).
certs:
	bash scripts/generate-certs.sh nginx/certs

init:
	docker compose exec -T postgres psql -U postgres -d logs -f /docker-entrypoint-initdb.d/init.sql

# Backend unit + integration tests.
test:
	cd backend && python -m pytest ../tests/ -v

test-frontend:
	cd frontend && npm test -- --run

# Build images only.
build:
	docker compose build

clean:
	docker compose down -v
	docker compose rm -f

shell-backend:
	docker compose exec backend bash

shell-postgres:
	docker compose exec postgres psql -U postgres -d logs

# Run the retention cleanup once (spec §10).
retention:
	docker compose exec backend python -m scripts.retention

docs:
	@echo "API docs: http://localhost:8000/docs"

# Send sample syslog (host netcat → docker UDP/514).
send-syslog:
	./samples/send_syslog.sh localhost 514

send-sample:
	python samples/post_logs.py http://localhost:8000/api/v1/ingest

.PHONY: up down restart logs ps test clean init build certs seed send-syslog send-sample shell-backend shell-postgres docs retention test-frontend

# ── Appliance mode (single host, Docker Compose) ─────────────────────────

up: certs
	docker compose up -d --build
	@echo ""
	@echo "Services started. Access:"
	@echo "  - Frontend:        http://localhost:3000"
	@echo "  - Backend API:     http://localhost:8000  (docs: /docs)"
	@echo "  - HTTPS via nginx: https://localhost"
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

# I-22: `init` now depends on `up` so users running on a fresh clone
# don't hit "container is not running". The original `init` ran against
# an exec'd container that may not exist if `make up` was skipped.
init: up
	docker compose exec -T postgres psql -U $${POSTGRES_USER:-postgres} -d $${POSTGRES_DB:-logs} -f /docker-entrypoint-initdb.d/init.sql

# Backend unit + integration tests. I-Makefile-10: pytest needs to be run
# with the project root on PYTHONPATH and pytest.ini at the same level —
# the previous `cd backend && pytest ../tests/ -v` silently broke imports
# of `from backend...` because it ran with `backend/` as CWD.
test:
	PYTHONPATH=. python -m pytest -c pytest.ini tests/ -v

# I-Makefile-11: ditto for the frontend test target.
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
	docker compose exec postgres psql -U $${POSTGRES_USER:-postgres}

# Run the retention cleanup once (spec §10).
# I-Makefile-11: PYTHONPATH=/app + scripts/__init__.py so the module is
# importable inside the backend container. The bare `python -m scripts.retention`
# from the previous version failed with `No module named scripts.retention`.
retention:
	docker compose exec -T backend bash -c "cd /app && PYTHONPATH=/app python -m scripts.retention"

docs:
	@echo "API docs: http://localhost:8000/docs"

# Send sample syslog (host netcat → docker UDP/514).
send-syslog:
	./samples/send_syslog.sh localhost 514

# I-23: run the sample sender inside the backend container so the host
# doesn't need Python installed. The previous version required
# `python3` on the developer's machine and a port-forwarded 8000.
send-sample:
	docker compose exec -T backend python /app/samples/post_logs.py http://backend:8000/api/v1/ingest

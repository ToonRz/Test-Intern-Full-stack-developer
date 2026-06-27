# Runbook — Incident Entries

Operational playbooks for known issues. Each entry: what to alert on, how to identify, how to recover, what was done permanently, what to monitor.

Related docs:
- `_internal/POSTMORTEM.md` — internal learning (root cause + lessons)
- `_internal/observability-dashboard.md` — dashboard + alert metrics
- `_internal/RUN.md` — daily usage

---

## 2026-06-27 — SECRET_KEY boot guard refuses to start with `.env.example` placeholder

**Bug ID:** B-C1-SECRET-KEY-2026-06-27
**Severity:** SEV1 (latent — fix landed pre-deploy)

**Symptom**
Backend container fails to start. `docker compose ps` shows `backend` in a `(health: starting)` loop. `docker compose logs backend` shows `RuntimeError: SECRET_KEY must be set to a 32+ character random value, not a placeholder from .env.example.`. External signals: `curl http://<host>:8000/health` returns connection refused; ingest rate flatlines at 0/s; Grafana panel **Ingest & Query Rate** (`_internal/observability-dashboard.md:142`) flatlines.

**Cause**
Boot guard at `backend/main.py:42-80` refuses to start with a placeholder-shaped `SECRET_KEY` — denylist pins known placeholders; anchored `CHANGE_ME…` prefix regex catches the convention. This is the **fixed** behaviour. The latent bug pre-fix was the *absence* of this refusal: the old guard used strict equality against `"change-me-in-production"` and let `CHANGE_ME_GENERATE_WITH_OPENSSL_RAND_HEX_32` (44 chars) pass.

**Detection (post-fix)**
Primary alert `BackendRefusedToBoot`. Secondary alert `BackendRestartLoop`. See *Prevention* below.

**Mitigation (step-by-step)**

The guard runs **before** `FastAPI(...)` is constructed (`backend/main.py:72-80`). Process dies with `RuntimeError` before binding ports — there is no half-broken state. The operator must fix the secret and redeploy.

1. **Confirm the diagnosis** (don't guess):

   ```bash
   docker compose logs backend | grep -A1 "SECRET_KEY must"
   # Expected: the RuntimeError; if missing, you have a different outage.

   docker exec backend env | grep SECRET_KEY
   # If value is `CHANGE_ME_GENERATE_WITH_OPENSSL_RAND_HEX_32`,
   # `change-me-in-production`, or any `CHANGE_ME*` / `change-me*` prefix,
   # this is B-C1.
   ```

2. **Roll forward (preferred — <2 min):**

   1. Generate a real key on the operator machine (**NOT** inside the failing container):

      ```bash
      openssl rand -hex 32
      # 64-char hex, e.g. 9f3a1b...c2 — treat as a secret from this point on.
      ```

   2. Update the deployment's secret store. Pick the path your environment uses:

      - **Plain `.env` (dev / appliance):** edit `.env`, replace the `SECRET_KEY=` line with the generated value.
      - **Helm / Terraform / external secrets operator:** update the `secretKeyRef` backing the backend deployment's `SECRET_KEY` env var. **Do not commit the value to git.**
      - **CI / staging:** rotate the corresponding GitHub Actions / GitLab CI variable.

   3. **Rotation note:** if a legitimate `SECRET_KEY` was in use pre-incident, treat the new value as a key rotation — all existing JWTs become invalid; users must log in again.

   4. Redeploy / restart:

      ```bash
      docker compose up -d backend            # appliance
      kubectl rollout restart deploy/backend  # SaaS / Helm
      ```

3. **Roll back (only if the new guard is itself the problem):**

   Use this branch only if a different failure surfaces after upgrade — e.g., a config-management tool that legitimately injects a placeholder-prefixed value during CI. Do not roll back to mask a real placeholder secret.

   ```bash
   git revert 562886f
   git push origin revert-b-c1
   ```

   **Before deploying the revert**, set a real `SECRET_KEY` per §2 — reverting the guard does NOT make the placeholder safe; it just re-silences the failure. Open a follow-up issue referencing this runbook and route to `/harden` so the new guard is reintroduced with whatever override is needed.

4. **Verify recovery (all four required before paging off):**

   ```bash
   # 1. Process is up
   docker compose ps backend                # state = (healthy), not (health: starting)
   curl -fsS http://<host>:8000/health      # {"status":"healthy"}

   # 2. No RuntimeError in recent logs
   docker compose logs --since=5m backend | grep -i "RuntimeError\|SECRET_KEY must" || echo OK

   # 3. JWT path reachable end-to-end with a real user
   curl -fsS -c /tmp/c.txt -H 'Content-Type: application/json' \
     -d '{"username":"admin","password":"<your-admin-password>"}' \
     http://<host>:8000/api/v1/auth/login
   curl -fsS -b /tmp/c.txt http://<host>:8000/api/v1/auth/me
   # Should return user object with role/tenant populated.

   # 4. No placeholder-shaped key in the running pod
   docker exec backend python -c \
     "from backend.main import _is_placeholder_secret_key; from backend.config import get_settings; s=get_settings(); import sys; sys.exit(2 if _is_placeholder_secret_key(s.SECRET_KEY) or len(s.SECRET_KEY)<32 else 0)"
   # Exit 0 = good.
   ```

   If any check fails, **do not** page off — loop back to §2.1. Most failures are copy/paste errors on the secret value.

**Permanent fix**
Commit `562886f` on `toonMac` (`backend/main.py:42-80`). Two-layer guard via `_is_placeholder_secret_key` (denylist + anchored `CHANGE_ME…` prefix regex). 15 regression cases in `tests/test_secret_key_check.py`. Full suite: 132 passed, 1 skipped. Postmortem: `_internal/POSTMORTEM.md`.

**Prevention**

- **Alert — `BackendRefusedToBoot`** (page on first hit)
  - PromQL: `count_over_time({service="log-management-backend", level="ERROR"} |= "SECRET_KEY must be set"[5m]) > 0`
  - Window: 5m
  - Severity: **page** — primary on-call; a boot loop is a total outage.
- **Alert — `BackendRestartLoop`** (page on `>= 3` in 10m)
  - PromQL: `increase(kube_pod_container_status_restarts_total{container="backend"}[10m]) >= 3` (k8s), or `docker inspect --format='{{.RestartCount}}' backend` polled externally.
  - Severity: **page** — same root cause, secondary signal.
- **Alert — `SECRET_KEYInEnvIsPlaceholder`** (page on first, ticket on repeat)
  - Probe: periodic cron every 5m reads `kubectl get secret` / `docker exec env`, runs `_is_placeholder_secret_key`; emits synthetic `level=ERROR msg="placeholder SECRET_KEY detected in env" source=<vault|env|file>` on match.
  - Severity: **page** on first hit; **ticket** for repeats within 1h (suppress pager fatigue).
- **Alert — `IngestFlatline`** (ticket, not page)
  - PromQL: `rate(log_management_logs_total[5m]) < 0.001` for 10m **and** `up{job="backend"} == 0`.
  - Severity: **ticket** — could be unrelated ingest pipeline fault; investigate, don't page.
- **Dashboard panel — `Backend Boot Health`** (stat)
  - On dashboard `logmgmt-observability` (`_internal/observability-dashboard.md:159`).
  - Expression: `log_management_backend_up` (gauge — **not yet implemented**, route to `/harden`).
  - Mapping: `1 → UP (green)`, `0 → DOWN (red)`.
- **Cardinality / noise:** keep `BackendRefusedToBoot` and `SECRET_KEYInEnvIsPlaceholder` on a **separate notification policy** from the high-volume `HighErrorRate` rule so a single boot-loop incident does not throttle legitimate error alerts.
- **Test:** `tests/test_secret_key_check.py` — 15 cases covering legacy literal, `.env.example` literal, prefix variants, false-positive guards, conftest fixture.
- **Runbook drill:** on incident. (Quarterly is overkill for a config-only guard.)

**Customer-facing note**
None. The fix prevents the server from starting — users cannot reach the service to observe anything different. If §2.3 (rotation) was applied and existing JWTs are now invalid, the only user-visible effect is a forced re-login, handled by the existing 401 path in `get_current_user` (`backend/auth/jwt.py:81-83`). Skip unless your standard rotation runbook already mandates an advisory.

**Hardening follow-ups (NOT in this runbook — file as separate `/harden` tickets)**

1. `backend/main.py:76` — bare `raise RuntimeError(...)` instead of structured `logger.critical(...)` + raise. Same pattern needed for any future boot-time guards.
2. `backend/main.py:224-264` — `/metrics` has no `log_management_backend_up` gauge; the `Backend Boot Health` panel proposed above cannot be implemented until this is added.
3. `backend/main.py:267-293` — `setup_telemetry()` runs inside `lifespan`, so OTel is only configured *after* the boot guard at line 72. Guard failures produce no trace span.
4. `backend/config.py:18` — `SECRET_KEY: str = "change-me-in-production"` literal default still exists; rely on boot guard instead (per `/prevent` finding #1).
5. `backend/main.py:330,337` — `os.getenv("ADMIN_PASSWORD", "admin123")` / `os.getenv("VIEWER_PASSWORD", "viewer123")` (per `/prevent` finding #2).

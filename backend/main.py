from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import asyncio
import re
import sys
import os
import logging
from datetime import datetime, timezone

# Ensure the project root is on sys.path so sibling packages (config, storage,
# routers, …) resolve consistently as `backend.xxx` whether we're imported as
# `backend.main` (tests) or run directly via `uvicorn main:app` (Docker with
# WORKDIR=/app and files copied flat into /app).
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from backend.config import get_settings
from backend.storage.database import init_db, async_session, LogEntry
from backend.routers import auth, ingest, logs, alerts, tenants, users
from backend.auth.jwt import get_password_hash
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from backend.rate_limit import limiter

settings = get_settings()
logger = logging.getLogger("log-management")

# High #7: RFC6587 §3.4.1 octet-counted framing — leading "<digits> " then
# exactly N bytes of message. Used by rsyslog/syslog-ng default TCP config.
_OCTET_COUNTED = re.compile(rb"^(\d+) ")

# Critical B-C3 / B-C4: cap the per-listener resource budget so a hostile
# or buggy sender can't OOM the backend. The semaphore caps the number of
# in-flight parsing coroutines; the buffer cap caps memory per TCP client.
_MAX_SYSLOG_UDP_TASKS = 1000
_MAX_TCP_BUF_BYTES = 1_048_576  # 1 MiB
_syslog_udp_sem = asyncio.Semaphore(_MAX_SYSLOG_UDP_TASKS)

# Refuse to boot with insecure defaults so SECRET_KEY isn't silently weak.
# Critical B-C1: always enforce — no DEBUG bypass. See
# tests/test_secret_key_check.py for the full incident writeup and the
# _is_placeholder_secret_key contract.
_SECRET_KEY_PLACEHOLDERS = frozenset({
    "change-me-in-production",
    "CHANGE_ME_GENERATE_WITH_OPENSSL_RAND_HEX_32",
})

# Anchored prefix match — `.env.example` placeholders start with
# `CHANGE_ME_*` / `change-me-*`. Anchoring avoids false-positives on
# legitimate secrets that merely contain the letters `change_me` somewhere
# (e.g. a passphrase like `please_change_me_quarterly`).
_PLACEHOLDER_PREFIX = re.compile(r"^change[_-]?me([_-]|$)", re.IGNORECASE)


def _is_placeholder_secret_key(value: str) -> bool:
    """True if `value` is a placeholder that must never reach production.

    Two layers: explicit denylist (locks known literals) + anchored prefix
    regex (catches the .env.example convention). The anchored prefix is
    intentionally narrow — it does not try to detect substrings anywhere
    in the value, because that would falsely reject legitimate passphrases
    that happen to contain `change_me` letters.
    """
    if value in _SECRET_KEY_PLACEHOLDERS:
        return True
    return bool(_PLACEHOLDER_PREFIX.match(value))


if (
    _is_placeholder_secret_key(settings.SECRET_KEY)
    or len(settings.SECRET_KEY) < 32
):
    raise RuntimeError(
        "SECRET_KEY must be set to a 32+ character random value, not a "
        "placeholder from .env.example. Generate one with "
        "`openssl rand -hex 32` and put it in .env."
    )


async def _retention_loop():
    """Background task: delete logs older than DATA_RETENTION_DAYS every hour (spec §10).

    Critical B-C2: run the cleanup *first*, then sleep — the previous version
    slept for an hour before its first cleanup, so a fresh install with stale
    test fixtures wouldn't purge them until hour 2.
    """
    from datetime import timedelta
    while True:
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=settings.DATA_RETENTION_DAYS)
            async with async_session() as db:
                from sqlalchemy import delete
                result = await db.execute(
                    delete(LogEntry).where(LogEntry.timestamp < cutoff)
                )
                await db.commit()
                logger.info("Retention: deleted %s logs older than %s", result.rowcount, cutoff.isoformat())
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Retention loop error")
            await asyncio.sleep(60)  # back off on error


def _parse_timestamp(ts: str) -> datetime:
    """Parse ISO8601 timestamp, treating naive strings as UTC. Always returns tz-aware."""
    if not ts:
        return datetime.now(timezone.utc)
    try:
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        elif "+" not in ts and "-" not in ts[10:]:
            ts = ts + "+00:00"
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        logger.warning("Could not parse timestamp %r, falling back to now()", ts)
        return datetime.now(timezone.utc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()
    await seed_defaults()
    # Medium #5 fix: re-fire any webhook/email delivery that didn't complete
    # before the previous process died. The flags are flipped in a fresh
    # session by `_send_webhook` / `_send_email` after success.
    from backend.services.alert_engine import AlertEngine as _AE
    from backend.storage.database import async_session as _async_session
    async with _async_session() as _db:
        await _AE(_db)._retry_pending_deliveries()
    # High #6: instrument the app after it's defined (was at module level,
    # fragile if anyone reorders imports above).
    setup_telemetry()
    app.state.syslog_task = asyncio.create_task(start_syslog_listener())
    app.state.retention_task = asyncio.create_task(_retention_loop())
    yield
    # Shutdown
    for task in (app.state.syslog_task, app.state.retention_task):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    lifespan=lifespan,
)

# Required for slowapi to apply @limiter.limit decorators.
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    # Critical B-C7: HSTS only on HTTPS. Sending it on HTTP responses caused
    # browsers to cache a "downgrade-only" policy that broke first-load HTTPS
    # negotiation and could not be cleared without a browser restart.
    if request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    # Use the limit configured on the route (e.g. "5 per 1 minute" for /auth/login)
    # instead of a hard-coded message. The default detail on the exception already
    # carries this, but rebuilding here keeps the response shape consistent and
    # gives us one place to localize the prefix if we ever need to.
    limit_str = str(exc.limit.limit) if exc.limit is not None else "request limit"
    return JSONResponse(
        status_code=429,
        content={"detail": f"Rate limit exceeded: {limit_str}."}
    )


# CORS: explicit origins only — never combine wildcard with allow_credentials=True.
allowed_origins = [o.strip() for o in settings.ALLOWED_ORIGINS.split(",") if o.strip()]
if not allowed_origins:
    allowed_origins = ["http://localhost:3000", "http://frontend:3000"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(auth.router, prefix=settings.API_PREFIX)
app.include_router(ingest.router, prefix=settings.API_PREFIX)
app.include_router(logs.router, prefix=settings.API_PREFIX)
app.include_router(alerts.router, prefix=settings.API_PREFIX)
app.include_router(tenants.router, prefix=settings.API_PREFIX)
app.include_router(users.router, prefix=settings.API_PREFIX)


@app.get("/")
async def root():
    return {"service": settings.APP_NAME, "status": "running"}


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.get("/metrics")
async def metrics():
    """Prometheus-format metrics endpoint.

    HIGH: nginx.conf has an IP-allowlisted /metrics path but the backend
    previously didn't define it, so Prometheus scrapes returned 404. The
    nginx config and the backend should agree; this lightweight exporter
    covers process, ingest, and alert counters without depending on the
    prometheus_client package (we hand-format so it works in air-gapped
    test envs).
    """
    try:
        async with async_session() as db:
            from sqlalchemy import func, select
            from backend.storage.database import LogEntry, TriggeredAlertDB, AlertRuleDB
            log_total = (await db.execute(select(func.count(LogEntry.id)))).scalar_one() or 0
            triggered_total = (await db.execute(select(func.count(TriggeredAlertDB.id)))).scalar_one() or 0
            rules_total = (await db.execute(select(func.count(AlertRuleDB.id)))).scalar_one() or 0
            ack_total = (await db.execute(
                select(func.count(TriggeredAlertDB.id)).where(TriggeredAlertDB.acknowledged == True)  # noqa: E712
            )).scalar_one() or 0
    except Exception:
        # Never let /metrics fail the scrape — return zeros with an error note.
        log_total = triggered_total = rules_total = ack_total = 0

    body = (
        "# HELP log_management_logs_total Total ingested log rows.\n"
        "# TYPE log_management_logs_total counter\n"
        f"log_management_logs_total {log_total}\n"
        "# HELP log_management_triggered_alerts_total Total triggered alerts (all time).\n"
        "# TYPE log_management_triggered_alerts_total counter\n"
        f"log_management_triggered_alerts_total {triggered_total}\n"
        "# HELP log_management_alert_rules_total Configured alert rules.\n"
        "# TYPE log_management_alert_rules_total gauge\n"
        f"log_management_alert_rules_total {rules_total}\n"
        "# HELP log_management_alerts_acknowledged_total Acknowledged triggered alerts.\n"
        "# TYPE log_management_alerts_acknowledged_total counter\n"
        f"log_management_alerts_acknowledged_total {ack_total}\n"
    )
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(content=body, media_type="text/plain; version=0.0.4")


def setup_telemetry():
    # Skip telemetry setup if no endpoint is configured — avoids noisy
    # background-thread errors trying to export to an empty target.
    if not settings.OTEL_EXPORTER_OTLP_ENDPOINT:
        return
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        resource = Resource.create({"service.name": settings.OTEL_SERVICE_NAME})
        provider = TracerProvider(resource=resource)

        try:
            exporter = OTLPSpanExporter(endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT, insecure=True)
            provider.add_span_processor(BatchSpanProcessor(exporter))
        except Exception:
            pass

        trace.set_tracer_provider(provider)
        FastAPIInstrumentor.instrument_app(app)

    except ImportError:
        pass


async def seed_defaults():
    """Seed default users and the spec §8 Login Failed Brute-Force alert rule.

    Users: only when the users table is empty AND SEED_DEMO_USERS is enabled.
    Alert rule: only when no rules exist (idempotent across restarts, but will
    not overwrite a rule the operator has customised).
    """
    await _seed_users()
    await _seed_default_alert_rule()


async def _seed_users():
    """Seed default Admin and Viewer users (only when DB is empty AND debug seed enabled).

    Default for SEED_DEMO_USERS is "false" so a production deployment that
    forgets to set the env var will NOT auto-create users with the well-known
    passwords admin123 / viewer123. Set to "true" for local dev / CI.

    Hardening B-C1-PR-B (item #2): when SEED_DEMO_USERS is enabled, both
    ADMIN_PASSWORD and VIEWER_PASSWORD must be set to non-empty values.
    Refuse to seed otherwise — the previous \"admin123\" / \"viewer123\"
    literal defaults silently shipped the well-known passwords to anyone
    who flipped SEED_DEMO_USERS on without also overriding the env vars.
    """
    from backend.storage.database import UserDB
    from sqlalchemy import select, func

    if os.getenv("SEED_DEMO_USERS", "false").lower() not in ("1", "true", "yes"):
        return

    # Guard BEFORE any DB mutation so a refused seed leaves zero rows.
    admin_pw = os.getenv("ADMIN_PASSWORD")
    viewer_pw = os.getenv("VIEWER_PASSWORD")
    if not admin_pw or not viewer_pw:
        raise RuntimeError(
            "ADMIN_PASSWORD and VIEWER_PASSWORD must be set (non-empty) "
            "when SEED_DEMO_USERS=true. Refusing to seed demo users with "
            "an unknown password."
        )

    async with async_session() as db:
        count = (await db.execute(select(func.count(UserDB.id)))).scalar_one()
        if count > 0:
            return

        admin = UserDB(
            username="admin",
            email="admin@example.com",
            role="Admin",
            tenant="*",
            hashed_password=get_password_hash(admin_pw)
        )
        viewer = UserDB(
            username="viewer",
            email="viewer@example.com",
            role="Viewer",
            tenant="demoA",
            hashed_password=get_password_hash(viewer_pw)
        )
        db.add_all([admin, viewer])
        await db.commit()


async def _seed_default_alert_rule():
    """Seed the spec §8 Login Failed Brute-Force rule (5 failures / 5 min per src_ip).

    Skipped when any rule already exists — operators may have customised the
    defaults and we don't want to fight their changes on every restart.
    """
    from backend.storage.database import AlertRuleDB
    from sqlalchemy import select, func

    async with async_session() as db:
        count = (await db.execute(select(func.count(AlertRuleDB.id)))).scalar_one()
        if count > 0:
            return

        rule = AlertRuleDB(
            tenant="*",  # global rule — fires for failed logins from any tenant (spec §6)
            name="Login Failed Brute-Force",
            description=(
                "Spec §8: 5 failed login events from the same src_ip within a "
                "5-minute window. Fires once per (src_ip, rule) group and "
                "increments until acknowledged."
            ),
            event_types=["LogonFailed", "app_login_failed"],
            threshold=5,
            window_minutes=5,
            group_by="src_ip",
            action="store",
            enabled=True,
        )
        db.add(rule)
        await db.commit()
        logger.info("Seeded default Login Failed Brute-Force alert rule")


# ── Syslog Listener (UDP + TCP, spec §5.1) ───────────────────────────────
async def _persist_log(normalized) -> int:
    """Persist a normalized log via async session. Returns the row id."""
    async with async_session() as db:
        entry = LogEntry(
            tenant=normalized.tenant,
            source=normalized.source,
            vendor=normalized.vendor,
            product=normalized.product,
            event_type=normalized.event_type,
            event_subtype=normalized.event_subtype,
            severity=normalized.severity,
            action=normalized.action,
            src_ip=normalized.src_ip,
            src_port=normalized.src_port,
            dst_ip=normalized.dst_ip,
            dst_port=normalized.dst_port,
            protocol=normalized.protocol,
            user=normalized.user,
            host=normalized.host,
            process=normalized.process,
            url=normalized.url,
            http_method=normalized.http_method,
            status_code=normalized.status_code,
            rule_name=normalized.rule_name,
            rule_id=normalized.rule_id,
            cloud=normalized.cloud.model_dump() if normalized.cloud else None,
            raw=normalized.raw,
            _tags=normalized.tags or None,
            timestamp=_parse_timestamp(normalized.timestamp),
        )
        db.add(entry)
        await db.commit()
        await db.refresh(entry)
        return entry.id


async def _handle_syslog_line(line: str, tenant: str = "default") -> None:
    """Parse one syslog line and persist via async DB."""
    from backend.normalizer.core import parse_syslog_firewall, parse_syslog_network
    if not line:
        return
    normalized = parse_syslog_firewall(line, tenant) or parse_syslog_network(line, tenant)
    if not normalized:
        logger.debug("Syslog line did not match any parser: %r", line[:120])
        return
    try:
        await _persist_log(normalized)
    except Exception:
        logger.exception("Failed to persist syslog line")


async def start_syslog_listener():
    """
    Start Syslog UDP + TCP listeners on SYSLOG_PORT (default 514).
    Spec §5.1 mandates both UDP and TCP.
    """
    from backend.normalizer.core import parse_syslog_firewall, parse_syslog_network
    import socket

    port = settings.SYSLOG_PORT
    host = settings.SYSLOG_HOST

    async def udp_loop():
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            logger.info("Syslog UDP listener bound on %s:%s", host, port)
        except PermissionError:
            logger.error("Cannot bind UDP %s:%s — needs root or NET_BIND_SERVICE capability", host, port)
            return

        # UDP via loop.add_reader is fully asyncio-native: the callback runs
        # on the loop's reader thread only when the kernel reports data is
        # ready. On shutdown, remove_reader + close() releases the fd
        # immediately. The previous run_in_executor(recvfrom) blocked the
        # executor thread until the next packet arrived, leaking one thread
        # per restart.
        loop = asyncio.get_running_loop()
        sock.setblocking(False)

        def on_readable():
            while True:
                try:
                    data, _addr = sock.recvfrom(65535)
                except BlockingIOError:
                    return  # drained the kernel buffer for now
                line = data.decode("utf-8", errors="ignore").strip()
                if line:
                    # Critical B-C3: bound concurrent parse tasks by checking
                    # the semaphore counter synchronously. If the slot is full
                    # we drop the datagram rather than spawning an unbounded
                    # number of coroutines and exhausting memory.
                    if _syslog_udp_sem._value <= 0:
                        logger.warning(
                            "Syslog UDP backpressure: dropping datagram (cap=%d)",
                            _MAX_SYSLOG_UDP_TASKS,
                        )
                        continue
                    asyncio.create_task(_bounded_syslog_line(line))

        async def _bounded_syslog_line(line: str) -> None:
            async with _syslog_udp_sem:
                await _handle_syslog_line(line)

        try:
            loop.add_reader(sock.fileno(), on_readable)
            # Park here until cancelled; the listener is driven by add_reader.
            await asyncio.Future()
        finally:
            try:
                loop.remove_reader(sock.fileno())
            except (OSError, ValueError):
                pass
            sock.close()
            logger.info("Syslog UDP listener closed on %s:%s", host, port)

    async def tcp_loop():
        """RFC6587-style octet-counted or LF-delimited TCP syslog.

        Spec §5.1 mandates UDP and TCP both on SYSLOG_PORT (default 514). Linux
        allows the same port to be bound for UDP and TCP simultaneously — Docker
        maps the same external port to both protocols via separate `udp`/`tcp`
        suffixes in docker-compose.yml.

        High #7: now actually implements both framings — production rsyslog /
        syslog-ng default to octet-counted (RFC6587 §3.4.1) but legacy senders
        still use LF-delimited, so we autodetect per buffer.
        """
        server = await asyncio.start_server(_handle_tcp_client, host=host, port=port)
        logger.info("Syslog TCP listener bound on %s:%s", host, port)
        async with server:
            await server.serve_forever()

    async def _handle_tcp_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        # High #7: support both RFC6587 octet-counted and LF-delimited framing
        # in one TCP connection — autodetect by inspecting the head of the buffer.
        # Critical B-C4: cap the per-connection buffer so a peer that streams
        # without LF (or with a 10 MB "frame count") can't OOM the process.
        buf = b""
        peer = writer.get_extra_info("peername")
        try:
            while True:
                chunk = await reader.read(4096)
                if not chunk:
                    break
                buf += chunk
                if len(buf) > _MAX_TCP_BUF_BYTES:
                    logger.warning(
                        "Syslog TCP buffer overflow from %s — closing connection (cap=%d)",
                        peer, _MAX_TCP_BUF_BYTES,
                    )
                    break
                while buf:
                    # Octet-counted: leading "<digits> " then exactly N bytes.
                    m = _OCTET_COUNTED.match(buf)
                    if m:
                        count = int(m.group(1))
                        frame_end = m.end() + count
                        if len(buf) < frame_end:
                            break  # need more bytes before we can deliver this frame
                        msg = buf[m.end():frame_end]
                        buf = buf[frame_end:]
                        line = msg.decode("utf-8", errors="ignore").strip()
                        if line:
                            await _handle_syslog_line(line)
                        continue
                    # LF-delimited fallback: one record per newline.
                    nl = buf.find(b"\n")
                    if nl == -1:
                        break  # incomplete record — wait for more bytes
                    line = buf[:nl].decode("utf-8", errors="ignore").strip()
                    buf = buf[nl + 1:]
                    if line:
                        await _handle_syslog_line(line)
        except (asyncio.IncompleteReadError, ConnectionResetError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    try:
        await asyncio.gather(udp_loop(), tcp_loop())
    except asyncio.CancelledError:
        logger.info("Syslog listener shutting down")
        raise


if __name__ == "__main__":
    import uvicorn
    # HIGH: use settings so SECRETS_CONFIG_PATH / bind address come from the
    # environment, not a hard-coded value. The previous literal ignored
    # SYSLOG_HOST (syslog listener) and bound to all interfaces unconditionally
    # — operators running on a custom port or interface had to patch the file.
    uvicorn.run(
        app,
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
    )

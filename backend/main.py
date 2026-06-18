from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import asyncio
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
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

settings = get_settings()
logger = logging.getLogger("log-management")

# Refuse to boot with insecure defaults so SECRET_KEY isn't silently weak.
if settings.SECRET_KEY == "change-me-in-production" or len(settings.SECRET_KEY) < 32:
    if not settings.DEBUG:
        raise RuntimeError(
            "SECRET_KEY must be set to a 32+ character random value in production. "
            "Set SECRET_KEY in .env to a value generated via `openssl rand -hex 32`."
        )
    logger.warning("SECRET_KEY is using the insecure development default — do not run with DEBUG=False in prod.")

# Rate limiter — wired via app.state so slowapi decorators work.
limiter = Limiter(key_func=get_remote_address)


async def _retention_loop():
    """Background task: delete logs older than DATA_RETENTION_DAYS every hour (spec §10)."""
    from datetime import timedelta
    while True:
        try:
            await asyncio.sleep(3600)
            cutoff = datetime.now(timezone.utc) - timedelta(days=settings.DATA_RETENTION_DAYS)
            async with async_session() as db:
                from sqlalchemy import delete
                result = await db.execute(
                    delete(LogEntry).where(LogEntry.timestamp < cutoff)
                )
                await db.commit()
                logger.info("Retention: deleted %s logs older than %s", result.rowcount, cutoff.isoformat())
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Retention loop error")


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
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded. Max 100 requests per minute."}
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


setup_telemetry()


async def seed_defaults():
    """Seed default users and the spec §8 Login Failed Brute-Force alert rule.

    Users: only when the users table is empty AND SEED_DEMO_USERS is enabled.
    Alert rule: only when no rules exist (idempotent across restarts, but will
    not overwrite a rule the operator has customised).
    """
    await _seed_users()
    await _seed_default_alert_rule()


async def _seed_users():
    """Seed default Admin and Viewer users (only when DB is empty AND debug seed enabled)."""
    from backend.storage.database import UserDB
    from sqlalchemy import select, func

    if os.getenv("SEED_DEMO_USERS", "true").lower() not in ("1", "true", "yes"):
        return

    async with async_session() as db:
        count = (await db.execute(select(func.count(UserDB.id)))).scalar_one()
        if count > 0:
            return

        admin = UserDB(
            username="admin",
            email="admin@example.com",
            role="Admin",
            tenant="*",
            hashed_password=_bcrypt_hash(os.getenv("ADMIN_PASSWORD", "admin123"))
        )
        viewer = UserDB(
            username="viewer",
            email="viewer@example.com",
            role="Viewer",
            tenant="demoA",
            hashed_password=_bcrypt_hash(os.getenv("VIEWER_PASSWORD", "viewer123"))
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


def _bcrypt_hash(password: str) -> str:
    """Hash a password — pre-hash with SHA256 if >72 bytes to avoid bcrypt silent truncation."""
    import bcrypt
    pw = password.encode("utf-8")
    if len(pw) > 72:
        import hashlib
        pw = hashlib.sha256(pw).hexdigest().encode("utf-8")
    return bcrypt.hashpw(pw, bcrypt.gensalt()).decode("utf-8")


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
            _tags=normalized._tags or None,
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
        loop = asyncio.get_running_loop()
        while True:
            data, _addr = await loop.run_in_executor(None, sock.recvfrom, 65535)
            line = data.decode("utf-8", errors="ignore").strip()
            await _handle_syslog_line(line)

    async def tcp_loop():
        """RFC6587-style octet-counted or LF-delimited TCP syslog.

        Spec §5.1 mandates UDP and TCP both on SYSLOG_PORT (default 514). Linux
        allows the same port to be bound for UDP and TCP simultaneously — Docker
        maps the same external port to both protocols via separate `udp`/`tcp`
        suffixes in docker-compose.yml.
        """
        server = await asyncio.start_server(_handle_tcp_client, host=host, port=port)
        logger.info("Syslog TCP listener bound on %s:%s", host, port)
        async with server:
            await server.serve_forever()

    async def _handle_tcp_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            while True:
                data = await reader.readuntil(b"\n")
                line = data.decode("utf-8", errors="ignore").strip()
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
    uvicorn.run(app, host="0.0.0.0", port=8000)

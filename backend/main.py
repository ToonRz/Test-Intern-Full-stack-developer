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

# Refuse to boot with insecure defaults so SECRET_KEY isn't silently weak.
if settings.SECRET_KEY == "change-me-in-production" or len(settings.SECRET_KEY) < 32:
    if not settings.DEBUG:
        raise RuntimeError(
            "SECRET_KEY must be set to a 32+ character random value in production. "
            "Set SECRET_KEY in .env to a value generated via `openssl rand -hex 32`."
        )
    logger.warning("SECRET_KEY is using the insecure development default — do not run with DEBUG=False in prod.")


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
    """
    from backend.storage.database import UserDB
    from sqlalchemy import select, func

    if os.getenv("SEED_DEMO_USERS", "false").lower() not in ("1", "true", "yes"):
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
            hashed_password=get_password_hash(os.getenv("ADMIN_PASSWORD", "admin123"))
        )
        viewer = UserDB(
            username="viewer",
            email="viewer@example.com",
            role="Viewer",
            tenant="demoA",
            hashed_password=get_password_hash(os.getenv("VIEWER_PASSWORD", "viewer123"))
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
                    # Schedule the coroutine on the loop — the reader
                    # callback itself is synchronous.
                    asyncio.create_task(_handle_syslog_line(line))

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
        buf = b""
        try:
            while True:
                chunk = await reader.read(4096)
                if not chunk:
                    break
                buf += chunk
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
    uvicorn.run(app, host="0.0.0.0", port=8000)

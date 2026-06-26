import logging
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.storage.database import get_db, LogEntry, async_session
from backend.models.schemas import LogIngest, NormalizedLog
from backend.normalizer.core import normalize_log
from backend.services.alert_engine import AlertEngine
from backend.services.enrichment import EnrichmentService
from backend.rate_limit import limiter

router = APIRouter(prefix="/ingest", tags=["Ingest"])
logger = logging.getLogger("log-management.ingest")

# Critical B-C5: cap the request body to defend against memory-exhaustion
# via a 1 GB JSON blob. 16 MiB comfortably accommodates a batch of tens of
# thousands of compact log lines but won't OOM the process.
_MAX_INGEST_BODY_BYTES = 16 * 1024 * 1024  # 16 MiB


def _parse_timestamp(ts: Optional[str]) -> datetime:
    """Parse ISO8601, return tz-aware datetime or now(). Never raises."""
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
        logger.warning("Could not parse timestamp %r — using now()", ts)
        return datetime.now(timezone.utc)


async def save_log(db: AsyncSession, log: NormalizedLog, enrichment: Optional[dict] = None) -> LogEntry:
    tags = list(log.tags) if log.tags else []
    if enrichment and enrichment.get("_tags"):
        tags.extend(enrichment["_tags"])

    entry = LogEntry(
        tenant=log.tenant,
        source=log.source,
        vendor=log.vendor,
        product=log.product,
        event_type=log.event_type,
        event_subtype=log.event_subtype,
        severity=log.severity,
        action=log.action,
        src_ip=log.src_ip,
        src_port=log.src_port,
        dst_ip=log.dst_ip,
        dst_port=log.dst_port,
        protocol=log.protocol,
        user=log.user,
        host=log.host,
        process=log.process,
        url=log.url,
        http_method=log.http_method,
        status_code=log.status_code,
        rule_name=log.rule_name,
        rule_id=log.rule_id,
        cloud=log.cloud.model_dump() if log.cloud else None,
        raw=log.raw,
        _tags=tags or None,
        geo_country=(enrichment or {}).get("geo_country"),
        geo_city=(enrichment or {}).get("geo_city"),
        geo_lat=(enrichment or {}).get("geo_lat"),
        geo_lon=(enrichment or {}).get("geo_lon"),
        rdns_hostname=(enrichment or {}).get("rdns_hostname"),
        timestamp=_parse_timestamp(log.timestamp),
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return entry


async def enrich_and_save(db: AsyncSession, log: NormalizedLog) -> LogEntry:
    enrichment: Optional[dict] = None
    if log.src_ip:
        try:
            result = await EnrichmentService.enrich(log.src_ip)
            enrichment = {
                "geo_country": result.geo_country,
                "geo_city": result.geo_city,
                "geo_lat": result.geo_lat,
                "geo_lon": result.geo_lon,
                "rdns_hostname": result.rdns_hostname,
                "_tags": result._tags,
            }
        except Exception:
            # Enrichment failure must not poison the DB session — the next
            # save_log() call shares this session and would otherwise hit
            # PendingRollbackError on commit. Rollback to clear the failed
            # transaction state, then save the log without enrichment data.
            #
            # HIGH: do NOT mutate `RedisCache._instance` from this module.
            # That class-level singleton is owned by the enrichment module —
            # cross-module mutation is a hidden side effect that confuses
            # readers and races with concurrent coroutines. The enrichment
            # module now handles its own cache reset on connection failure
            # (see EnrichmentService.enrich).
            logger.exception("Enrichment failed for src_ip=%s", log.src_ip)
            await db.rollback()
    return await save_log(db, log, enrichment)


@router.post("")
@limiter.limit("120/minute")
async def ingest_log(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """POST /ingest — receive JSON log (single object or batch array) per spec §5.1.

    Critical B-C5: rate-limited to 120 req/min/IP and capped at 16 MiB body
    so a single client can't OOM the process or starve other ingesters. The
    body-size check happens before `await request.json()` so a 1 GB blob is
    rejected as soon as Content-Length is read, without buffering into memory.
    """
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > _MAX_INGEST_BODY_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Request body too large (>{_MAX_INGEST_BODY_BYTES} bytes)",
        )
    body = await request.json()
    logs = body if isinstance(body, list) else [body]

    results = []
    for log_data in logs:
        if not isinstance(log_data, dict):
            raise HTTPException(status_code=400, detail="Each log entry must be a JSON object")

        tenant = log_data.get("tenant") or "default"
        source = log_data.get("source") or "api"
        normalized = normalize_log(log_data, source, tenant)
        entry = await enrich_and_save(db, normalized)
        results.append({"id": entry.id, "status": "ingested"})
        background_tasks.add_task(check_alerts, entry.id)

    return {"status": "ok", "ingested": len(results), "logs": results}


async def check_alerts(log_id: int):
    """Run alert evaluation on a freshly-ingested log row in the background."""
    try:
        async with async_session() as db:
            result = await db.execute(select(LogEntry).where(LogEntry.id == log_id))
            log = result.scalar_one_or_none()
            if log:
                engine = AlertEngine(db)
                triggered = await engine.check_brute_force(log)
                if triggered:
                    logger.info(
                        "Alert triggered: rule=%s src_ip=%s count=%s id=%s",
                        triggered.rule_name, triggered.src_ip, triggered.count, triggered.id,
                    )
    except Exception:
        logger.exception("Alert check failed for log_id=%s", log_id)


@router.post("/batch")
@limiter.limit("60/minute")
async def ingest_batch(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """POST /ingest/batch — upload JSON batch (AWS, M365, AD) per spec §5.1.

    Critical B-C5: same body-size cap and rate limit as /ingest. The
    batch endpoint historically was the worst offender for accidental
    multi-hundred-MB uploads because upstream tooling serialises the whole
    daily export into one request.
    """
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > _MAX_INGEST_BODY_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Request body too large (>{_MAX_INGEST_BODY_BYTES} bytes)",
        )
    body = await request.json()
    files = body.get("files", [])
    source = body.get("source", "api")
    tenant = body.get("tenant", "default")

    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    results = []
    for file_data in files:
        logs = file_data.get("logs", [])
        for log_data in logs:
            normalized = normalize_log(log_data, source, tenant)
            entry = await enrich_and_save(db, normalized)
            results.append({"id": entry.id, "status": "ingested"})
            background_tasks.add_task(check_alerts, entry.id)

    return {"status": "ok", "ingested": len(results), "logs": results}

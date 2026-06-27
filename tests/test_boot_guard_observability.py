"""
Regression tests for PR-A (hardening #1): the SECRET_KEY boot guard must
emit a structured CRITICAL log (with event=, placeholder_detected=,
secret_length=, secret_source=) and the /metrics endpoint must surface
a `log_management_backend_up 1` gauge after the guard passes.

The crucial invariant: the secret value itself MUST NOT appear in any
log payload or in the /metrics body. Operators inspect logs in plaintext
dashboards; a leaked signing key is a complete compromise.

Why in-process (post PR-C):
- After PR-C, the boot guard lives in `_check_secret_key()` (called from
  lifespan startup), not at module-load-time. caplog can attach to the
  parent process's logger and capture the CRITICAL record directly.
- A subprocess test would need asgi-lifespan in the subprocess to drive
  lifespan, which adds dependency surface for a single invariant.
"""
from __future__ import annotations

import logging
import os
import re

import pytest
from httpx import AsyncClient


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# A placeholder value with a distinctive tail so we can grep for the
# SECRET PREFIX leaking into any log field. The tail is unique enough
# to never appear in unrelated framework logs.
_PLACEHOLDER_SECRET = "CHANGE_ME_DO_NOT_LOG_abcdef0123456789_SECRET_TAIL"
# The "tail" we grep for - must NEVER appear in any log payload.
_FORBIDDEN_TAIL = "DO_NOT_LOG_abcdef0123456789"


# Reserved LogRecord attributes that logging adds on its own; everything
# else in record.__dict__ came from `extra=` and is the operator-visible
# structured payload we are asserting against.
_RESERVED_LOGRECORD_ATTRS = {
    "name", "msg", "args", "levelname", "levelno",
    "pathname", "filename", "module", "exc_info",
    "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread",
    "threadName", "processName", "process", "taskName",
    "message", "asctime",
}


# ── Tests ───────────────────────────────────────────────────────────────

def test_boot_refusal_emits_structured_log(monkeypatch, caplog):
    """The boot guard must emit a single CRITICAL record on the
    `log-management` logger with structured extras: event=,
    placeholder_detected=, secret_length=, secret_source=.

    Crucially, the secret value (or a recognizable substring of it) MUST
    NOT appear in the log message or any extra field.
    """
    import backend.main as _bm
    monkeypatch.setattr(_bm.settings, "SECRET_KEY", _PLACEHOLDER_SECRET)

    with caplog.at_level(logging.CRITICAL, logger="log-management"):
        with pytest.raises(RuntimeError):
            _bm._check_secret_key()

    critical = [r for r in caplog.records if r.levelno == logging.CRITICAL]
    assert len(critical) >= 1, (
        "Expected at least one CRITICAL record from the boot guard. "
        "records=%r" % [(r.levelname, r.getMessage()) for r in caplog.records]
    )

    # The first CRITICAL record is the one the guard emitted right
    # before raising. Operators look at it first.
    first = critical[0]

    # Structured extras (the load-bearing assertions):
    assert getattr(first, "event", None) == "secret_key_boot_refused", (
        "Boot guard log must carry event='secret_key_boot_refused' so "
        "log queries / alerts can match on a stable identifier. "
        "record=%r" % first.__dict__
    )
    assert getattr(first, "placeholder_detected", None) is True, (
        "placeholder_detected must be True for a placeholder-shaped "
        "secret; got %r" % getattr(first, "placeholder_detected", None)
    )
    assert getattr(first, "secret_length", None) == len(_PLACEHOLDER_SECRET), (
        "secret_length must be %d, got %r"
        % (len(_PLACEHOLDER_SECRET), getattr(first, "secret_length", None))
    )
    assert hasattr(first, "secret_source"), (
        "Boot guard log must carry secret_source. record=%r" % first.__dict__
    )

    # The critical safety invariant: the secret value (or any substring
    # of it that an attacker could recognize) MUST NOT appear anywhere
    # in the formatted message or in any extra field.
    extras_text = " ".join(
        str(v) for k, v in first.__dict__.items()
        if k not in _RESERVED_LOGRECORD_ATTRS
    )
    full_record_text = first.getMessage() + " " + extras_text
    assert _FORBIDDEN_TAIL not in full_record_text, (
        "SECRET KEY LEAKED INTO LOG: forbidden tail %r found in record"
        % _FORBIDDEN_TAIL
    )
    assert _PLACEHOLDER_SECRET not in full_record_text, (
        "SECRET KEY LEAKED INTO LOG: full placeholder value found in record"
    )


# ── /metrics invariants (in-process) ────────────────────────────────────

@pytest.mark.asyncio
async def test_metrics_includes_backend_up_gauge():
    """`/metrics` body must contain `log_management_backend_up 1` after
    the boot guard passes.

    After PR-C moves the guard into lifespan startup, the gauge flips
    during lifespan, not at module import. ASGITransport does NOT drive
    lifespan events, so we wrap the request in a LifespanManager to fire
    startup before scraping /metrics. Skips when asgi-lifespan is absent.
    """
    asgi_lifespan = pytest.importorskip("asgi_lifespan")
    from httpx import ASGITransport
    from backend.main import app

    transport = ASGITransport(app=app)
    async with asgi_lifespan.LifespanManager(app):
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/metrics")
    assert resp.status_code == 200, "GET /metrics should succeed; got %s %s" % (
        resp.status_code, resp.text
    )
    body = resp.text
    m = re.search(r"^log_management_backend_up\s+(\S+)$", body, re.MULTILINE)
    assert m is not None, (
        "Expected line `log_management_backend_up <value>` in /metrics "
        "body. Body was:\n%s" % body
    )
    assert m.group(1) == "1", (
        "log_management_backend_up must be 1 after boot guard passes; "
        "got %r" % m.group(1)
    )


@pytest.mark.asyncio
async def test_metrics_does_not_expose_secret(client: AsyncClient):
    """Defensive: the /metrics body must NOT contain the SECRET_KEY value
    or any obvious substring of it.

    Prometheus scrapes are typically exposed via an IP-allowlisted path
    on nginx, but if the scrape target leaks secrets, anyone with access
    to the scrape path (or a misconfigured proxy log) gets a free
    signing key. This test guards against an implementer who stuffs
    debug info into the metrics body.
    """
    # Use the secret conftest set - must not appear anywhere in the
    # metrics output.
    from backend.config import get_settings
    secret = get_settings().SECRET_KEY
    # Substring check (last 8 chars) so we don't fail on incidental
    # overlap with non-secret fields. A real leak would include a
    # recognizable chunk.
    tail = secret[-8:]

    resp = await client.get("/metrics")
    body = resp.text
    assert secret not in body, "SECRET_KEY leaked into /metrics body verbatim"
    assert tail not in body, (
        "SECRET_KEY tail %r leaked into /metrics body. Body:\n%s"
        % (tail, body)
    )

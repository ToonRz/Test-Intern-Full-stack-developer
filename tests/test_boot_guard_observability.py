"""
Regression tests for PR-A (hardening #1): the SECRET_KEY boot guard must
emit a structured CRITICAL log (with event=, placeholder_detected=,
secret_length=, secret_source=) and the /metrics endpoint must surface
a `log_management_backend_up 1` gauge after the guard passes.

The crucial invariant: the secret value itself MUST NOT appear in any
log payload or in the /metrics body. Operators inspect logs in plaintext
dashboards; a leaked signing key is a complete compromise.

Why subprocess for the structured-log test:
- caplog attaches to the parent process's logging module. The boot guard
  runs at import time of backend.main - by the time the test function
  executes, the import already happened and the log was already emitted
  (or not). subprocess.run gives us a fresh Python process whose logging
  handlers we control via stderr capture.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
import textwrap

import pytest
from httpx import AsyncClient


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ── Subprocess helper for the boot-refusal log capture ─────────────────

# A placeholder value with a distinctive tail so we can grep for the
# SECRET PREFIX leaking into any log field. The tail is unique enough
# to never appear in unrelated framework logs.
_PLACEHOLDER_SECRET = "CHANGE_ME_DO_NOT_LOG_abcdef0123456789_SECRET_TAIL"
# The "tail" we grep for - must NEVER appear in any log payload.
_FORBIDDEN_TAIL = "DO_NOT_LOG_abcdef0123456789"


def _run_import_capturing_logs(env_overrides: dict) -> subprocess.CompletedProcess:
    """Run `import backend.main` in a fresh interpreter, structured-log
    output to stderr, capture exit code + stderr.

    The boot guard is expected to emit ONE CRITICAL record on the
    `log-management` logger before raising. The subprocess script below
    configures a handler that captures every record along with its
    `extra=` fields, formatted as LEVEL|message|key=value|key=value|...
    """
    base_env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": REPO_ROOT,
        "HOME": os.environ.get("HOME", "/tmp"),
        "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
        "REDIS_URL": "redis://localhost:6379/0",
        "SEED_DEMO_USERS": "false",
        "ADMIN_PASSWORD": "",
        "VIEWER_PASSWORD": "",
    }
    base_env.update(env_overrides)
    script = textwrap.dedent(
        """
        import logging
        import sys
        import os

        captured = []

        class CaptureHandler(logging.Handler):
            def emit(self, record):
                extras = []
                reserved = {
                    "name", "msg", "args", "levelname", "levelno",
                    "pathname", "filename", "module", "exc_info",
                    "exc_text", "stack_info", "lineno", "funcName",
                    "created", "msecs", "relativeCreated", "thread",
                    "threadName", "processName", "process", "taskName",
                }
                for k, v in record.__dict__.items():
                    if k in reserved:
                        continue
                    extras.append("{}=%r".format(k) % v)
                line = "{}|{}|{}".format(
                    record.levelname,
                    record.getMessage(),
                    "|".join(extras),
                )
                captured.append(line)

        h = CaptureHandler()
        h.setLevel(logging.CRITICAL)
        logging.getLogger("log-management").addHandler(h)
        logging.getLogger("log-management").setLevel(logging.CRITICAL)

        try:
            import backend.main  # noqa: F401
        except RuntimeError:
            for line in captured:
                print(line, file=sys.stderr)
            sys.exit(42)
        for line in captured:
            print(line, file=sys.stderr)
        sys.exit(0)
        """
    )
    return subprocess.run(
        [sys.executable, "-c", script],
        env=base_env,
        capture_output=True,
        text=True,
        timeout=30,
        cwd=REPO_ROOT,
    )


def _parse_capture_lines(stderr: str) -> list[dict]:
    """Parse the captured log lines emitted by _run_import_capturing_logs.

    Each line: LEVEL|message|key=value|key=value|...
    Returns list of {level, message, extras: dict}.
    """
    lines = [ln for ln in stderr.splitlines() if "|" in ln]
    parsed = []
    for ln in lines:
        parts = ln.split("|")
        if len(parts) < 2:
            continue
        level = parts[0]
        message = parts[1]
        extras = {}
        for kv in parts[2:]:
            if "=" not in kv:
                continue
            k, v = kv.split("=", 1)
            extras[k] = v
        parsed.append({"level": level, "message": message, "extras": extras})
    return parsed


# ── Tests ───────────────────────────────────────────────────────────────

def test_boot_refusal_emits_structured_log():
    """The boot guard must emit a single CRITICAL record on the
    `log-management` logger with structured extras: event=,
    placeholder_detected=, secret_length=, secret_source=.

    Crucially, the secret value (or a recognizable substring of it) MUST
    NOT appear in the log message or any extra field. We check the full
    stderr for a unique tail marker.
    """
    result = _run_import_capturing_logs({"SECRET_KEY": _PLACEHOLDER_SECRET})

    # The guard must have raised - exit code 42 from the script.
    assert result.returncode == 42, (
        "Boot guard must raise RuntimeError on placeholder SECRET_KEY. "
        "returncode=%s stderr=%s" % (result.returncode, result.stderr)
    )

    records = _parse_capture_lines(result.stderr)
    critical = [r for r in records if r["level"] == "CRITICAL"]
    assert len(critical) >= 1, (
        "Expected at least one CRITICAL record from the boot guard. "
        "records=%r" % records
    )

    # The first CRITICAL record is the one the guard emitted right
    # before raising. Operators look at it first.
    first = critical[0]

    # Structured extras (the load-bearing assertions):
    assert first["extras"].get("event") == "secret_key_boot_refused", (
        "Boot guard log must carry event='secret_key_boot_refused' so "
        "log queries / alerts can match on a stable identifier. "
        "extras=%r" % first["extras"]
    )
    # placeholder_detected is a bool - the implementer may set it True
    # for a placeholder refusal, False for an empty-value refusal; we
    # accept either, but the field MUST exist.
    assert "placeholder_detected" in first["extras"], (
        "Boot guard log must carry placeholder_detected. "
        "extras=%r" % first["extras"]
    )
    # secret_length MUST be present and MUST equal the length of what
    # we set - not the value, not a hash.
    assert "secret_length" in first["extras"], (
        "Boot guard log must carry secret_length for ops dashboards. "
        "extras=%r" % first["extras"]
    )
    assert first["extras"]["secret_length"] == str(len(_PLACEHOLDER_SECRET)), (
        "secret_length must be %d, got %r"
        % (len(_PLACEHOLDER_SECRET), first["extras"].get("secret_length"))
    )
    # secret_source - must be a token like "env" or "default", NOT the value.
    assert "secret_source" in first["extras"], (
        "Boot guard log must carry secret_source. extras=%r" % first["extras"]
    )

    # The critical safety invariant: the secret value (or any substring
    # of it that an attacker could recognize) MUST NOT appear anywhere
    # in the formatted message or in any extra field.
    full_record_text = (
        first["message"]
        + " ".join(str(v) for v in first["extras"].values())
    )
    assert _FORBIDDEN_TAIL not in full_record_text, (
        "SECRET KEY LEAKED INTO LOG: forbidden tail %r found in record %r"
        % (_FORBIDDEN_TAIL, first)
    )
    assert _PLACEHOLDER_SECRET not in full_record_text, (
        "SECRET KEY LEAKED INTO LOG: full placeholder value found in record %r"
        % first
    )
    # Also defensively scan the full stderr in case the leak is outside
    # the captured-record format (e.g. an uncaught traceback printing
    # locals).
    assert _FORBIDDEN_TAIL not in result.stderr, (
        "SECRET KEY TAIL found somewhere in subprocess stderr - log "
        "leakage. stderr=%r" % result.stderr
    )


# ── /metrics invariants (in-process) ────────────────────────────────────

@pytest.mark.asyncio
async def test_metrics_includes_backend_up_gauge(client: AsyncClient):
    """`/metrics` body must contain `log_management_backend_up 1` after
    the boot guard passes.

    The conftest sets a valid SECRET_KEY via os.environ.setdefault, so
    the parent process's boot guard passed at import time. The gauge
    must therefore be 1 by the time the test runs.

    Note: ASGITransport does NOT drive lifespan (see conftest line 43),
    so if the implementer flips the gauge ONLY inside lifespan startup,
    this test will see 0. The implementer MUST flip the gauge
    synchronously at module-load time, after the boot guard. This test
    pins that requirement.
    """
    resp = await client.get("/metrics")
    assert resp.status_code == 200, "GET /metrics should succeed; got %s %s" % (
        resp.status_code, resp.text
    )
    body = resp.text
    # Parse for the gauge line. Prometheus text format: one metric per
    # line; accept any whitespace between name and value.
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

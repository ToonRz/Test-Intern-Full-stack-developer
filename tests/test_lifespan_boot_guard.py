"""
Regression tests for PR-C (hardening #3): the boot guard moves from
module-load-time into the lifespan startup sequence. The intent:

  1. `import backend.main` succeeds even with a placeholder SECRET_KEY
     - observability and tooling that import the app (e.g. Alembic,
     OpenAPI generators) must not crash on misconfiguration.

  2. Lifespan startup, when invoked by a real ASGI server, refuses to
     come up with a placeholder secret. The first HTTP request gets a
     500, not a successful-but-compromised boot.

  3. Lifespan ordering is: setup_telemetry() -> boot guard ->
     init_db() -> seed_defaults(). The boot guard runs AFTER telemetry
     so observability is wired up before the refusal log is emitted
     (the alert reaches the operator's dashboard, not just stderr).

Why this is a separate test file from test_boot_guard_observability:
PR-A and PR-C are independent reviews. PR-C changes module-load
semantics; PR-A changes log shape. Pinning them in separate files keeps
the diff easy to revert if a single PR needs to be backed out.
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap

import pytest

# asgi-lifespan is an optional dev dependency. If it's not installed,
# the in-process LifespanManager tests skip with a clear message. The
# subprocess import test below works without it.
asgi_lifespan = pytest.importorskip("asgi_lifespan")


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _make_subprocess_env(secret_key: str) -> dict:
    """Build a clean env for a subprocess that exercises backend.main.

    Note: we DO NOT inherit the parent's SECRET_KEY (conftest setdefault
    runs at collection time). Each test owns the value.
    """
    return {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": REPO_ROOT,
        "HOME": os.environ.get("HOME", "/tmp"),
        "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
        "REDIS_URL": "redis://localhost:6379/0",
        "SECRET_KEY": secret_key,
        "SEED_DEMO_USERS": "false",
        "ADMIN_PASSWORD": "",
        "VIEWER_PASSWORD": "",
    }


# ── 1. Import with placeholder must not crash ──────────────────────────

def test_import_succeeds_with_placeholder_secret():
    """`import backend.main` must NOT raise even with a placeholder
    SECRET_KEY after PR-C moves the guard into lifespan.

    Before PR-C, the guard runs at module top-level and import fails.
    After PR-C, the guard is deferred to lifespan startup, so importing
    the module is always safe. This is the property that lets Alembic,
    OpenAPI codegen, and CI smoke tests import the app without setting
    a real secret.

    Tested in a subprocess because the parent process's import is
    cached and the parent already passed (or failed) the guard.
    """
    placeholder = "CHANGE_ME_MOVE_GUARD_TO_LIFESPAN_TEST_VALUE_1234567890"
    env = _make_subprocess_env(placeholder)
    # We expect import to succeed (exit 0). The script does NOT
    # exercise lifespan; only import.
    script = textwrap.dedent(
        """
        import sys
        try:
            import backend.main  # noqa: F401
            sys.exit(0)
        except Exception as e:
            print("IMPORT_RAISED:", type(e).__name__, str(e), file=sys.stderr)
            sys.exit(1)
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, (
        "After PR-C, `import backend.main` must succeed even with a "
        "placeholder SECRET_KEY - the guard has moved into lifespan. "
        "stderr=%s" % result.stderr
    )
    assert "IMPORT_RAISED" not in result.stderr


# ── 2. Lifespan refuses placeholder at startup ─────────────────────────

@pytest.mark.asyncio
async def test_lifespan_refuses_placeholder_secret(monkeypatch):
    """When lifespan startup runs with a placeholder SECRET_KEY, it
    must raise (the guard fires inside lifespan, after setup_telemetry).

    We use asgi_lifespan.LifespanManager to drive the lifespan context
    manager in-process. The __aenter__ corresponds to startup; if the
    guard raises, the manager propagates the exception.
    """
    from backend.config import get_settings

    # Override the SECRET_KEY on the cached settings instance BEFORE
    # we drive lifespan. pydantic-settings uses lru_cache on
    # get_settings; we need to bypass it.
    placeholder = "CHANGE_ME_LIFESPAN_REFUSAL_TEST_VALUE_1234567890abcdef"
    monkeypatch.setattr(get_settings(), "SECRET_KEY", placeholder)

    # Also clear the cached module-level settings reference if PR-C
    # re-reads it inside lifespan. We can't know for sure, but the
    # lifespan function takes the app instance and can access
    # backend.main.settings - we monkeypatch that name too if it
    # exists at this point.
    try:
        import backend.main as _bm
        monkeypatch.setattr(_bm, "settings", get_settings(), raising=False)
    except Exception:
        pass

    from backend.main import app

    # LifespanManager.__aenter__ runs startup. If the guard raises,
    # the exception propagates here.
    with pytest.raises(Exception) as exc_info:
        async with asgi_lifespan.LifespanManager(app):
            # Should never reach this line if the guard fires.
            pytest.fail(
                "Lifespan startup should have refused the placeholder "
                "secret; instead it yielded normally."
            )

    # The exception type is the implementer's choice (RuntimeError, a
    # custom SecurityError, etc.). We don't pin the type - but we DO
    # require that the message references the secret so an operator
    # staring at the uvicorn log can diagnose.
    msg = str(exc_info.value)
    assert "SECRET_KEY" in msg, (
        "Lifespan refusal must mention SECRET_KEY in its message so "
        "operators can diagnose. Got: %r" % msg
    )


# ── 3. Telemetry runs BEFORE the boot guard ────────────────────────────

@pytest.mark.asyncio
async def test_lifespan_runs_telemetry_before_guard(monkeypatch):
    """Lifespan ordering invariant: setup_telemetry() runs before the
    boot guard, so the guard's refusal log lands on a wired-up OTel
    pipeline.

    We can't read OTel spans from the log-management app's exporter
    in-process (it points at a remote OTLP endpoint), so we instead
    observe CALL ORDER via monkeypatched timestamps. We instrument
    setup_telemetry and the boot-guard function with a shared list;
    the order in the list pins the spec.
    """
    call_order: list = []

    # Find the boot guard function. After PR-C it lives inside the
    # lifespan function or as a helper called from lifespan. We try
    # several common names and monkeypatch the first one that exists.
    import backend.main as _bm

    # Probe for the guard function. PR-C may expose it under any of
    # these names; if none exists, we record a marker and let the
    # assertion fail with a helpful message.
    guard_attr_candidates = [
        "_check_secret_key",
        "_boot_guard",
        "_enforce_secret_key",
        "_secret_key_guard",
        "_verify_secret_key",
    ]
    guard_attr = next((a for a in guard_attr_candidates if hasattr(_bm, a)), None)

    # Always monkeypatch setup_telemetry to record its position.
    import backend.main as _bm2
    original_setup_telemetry = _bm2.setup_telemetry

    def _patched_setup_telemetry(*args, **kwargs):
        call_order.append("setup_telemetry")
        return original_setup_telemetry(*args, **kwargs)

    monkeypatch.setattr(_bm2, "setup_telemetry", _patched_setup_telemetry)

    if guard_attr is not None:
        original_guard = getattr(_bm2, guard_attr)

        def _patched_guard(*args, **kwargs):
            call_order.append(guard_attr)
            return original_guard(*args, **kwargs)

        monkeypatch.setattr(_bm2, guard_attr, _patched_guard)
    else:
        # No exposed guard function name - record a sentinel so the
        # assertion can name the gap. We still want the rest of the
        # test to run and observe that telemetry fires before the
        # guard REFUSAL exception is raised (which we'll catch via
        # LifespanManager).
        call_order.append("NO_GUARD_ATTR_FOUND")

    # Drive lifespan with a VALID secret. The guard passes (no refusal
    # exception), so we get to observe the call_order at the point
    # the guard finishes.
    from backend.config import get_settings
    valid = "a" * 32 + "_valid_for_telemetry_ordering_test"
    monkeypatch.setattr(get_settings(), "SECRET_KEY", valid)
    monkeypatch.setattr(_bm2, "settings", get_settings(), raising=False)

    from backend.main import app

    async with asgi_lifespan.LifespanManager(app):
        # Inside the context: telemetry has run, guard has run (and
        # passed). Inspect the order.
        pass

    assert call_order, "Expected at least one instrumentation call; got none"
    assert "setup_telemetry" in call_order, (
        "setup_telemetry was never called during lifespan startup. "
        "call_order=%r" % call_order
    )

    if "NO_GUARD_ATTR_FOUND" in call_order:
        # Fail with a constructive message: name the candidate names so
        # the implementer can pick one to expose.
        pytest.fail(
            "Could not locate the boot guard function on backend.main. "
            "Expose it under one of these names so the ordering can be "
            "tested: %r. call_order=%r"
            % (guard_attr_candidates, call_order)
        )

    # The ordering invariant: setup_telemetry must appear BEFORE the
    # guard in call_order. setup_telemetry may also appear AFTER (e.g.
    # if re-invoked at shutdown) - we only assert the relative order
    # of the first occurrences.
    first_telemetry_idx = call_order.index("setup_telemetry")
    first_guard_idx = call_order.index(guard_attr)
    assert first_telemetry_idx < first_guard_idx, (
        "setup_telemetry must run BEFORE the boot guard so the "
        "refusal log reaches a wired-up OTel pipeline. "
        "call_order=%r" % call_order
    )


# ── 4. Happy path with conftest secret ─────────────────────────────────

@pytest.mark.asyncio
async def test_lifespan_happy_path_unchanged():
    """With a valid SECRET_KEY (the conftest default), lifespan startup
    completes without error. This is the regression net: PR-C must
    not break the happy path.
    """
    from backend.main import app

    # The conftest setdefault has populated a valid SECRET_KEY in the
    # parent process. LifespanManager drives startup + shutdown.
    async with asgi_lifespan.LifespanManager(app):
        pass

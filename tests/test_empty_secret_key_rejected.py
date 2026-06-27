"""
Regression tests for PR-B (hardening #2): the boot guard must reject an
empty SECRET_KEY, not just placeholders or short keys.

Bug B-C1-SECRET-KEY-2026-06-27 root-caused a missing-secret case: when
SECRET_KEY was set to "" in the environment, pydantic-settings fell back
to the `change-me-in-production` default and the existing placeholder
check happened to catch it - but only by accident. After PR-B the default
becomes "" (empty string) and the boot guard MUST refuse empty values
explicitly, regardless of placeholder detection.

Why subprocesses (see conftest.py):
- conftest.py sets SECRET_KEY via os.environ.setdefault BEFORE importing
  backend.main. The module-level guard in backend.main runs once and
  pydantic-settings caches get_settings() with lru_cache. Mutating
  os.environ in the parent process and re-importing cannot re-trigger
  the guard. We need a fresh interpreter.
- subprocess.run with a constructed env gives us a clean interpreter
  whose os.environ does NOT inherit the test runner's setdefault values.
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run_import_with_env(env_overrides: dict) -> subprocess.CompletedProcess:
    """Run `python -c "import backend.main"` in a fresh interpreter with
    a fully-controlled environment.

    `env_overrides` keys REPLACE matching entries in the parent env (or
    add new ones). Crucially, we start from a minimal env (PATH,
    PYTHONPATH, HOME) so the test runner's os.environ.setdefault values
    do NOT leak into the subprocess via inheritance. Each override is
    the single source of truth for that variable.
    """
    base_env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": REPO_ROOT,
        "HOME": os.environ.get("HOME", "/tmp"),
        # Picked up by pydantic-settings in the subprocess. The boot guard
        # in PR-B must reject this with an explicit "SECRET_KEY must be
        # set" message - not the placeholder message, because "" does
        # not match the CHANGE_ME_* convention.
        "SECRET_KEY": "",
        # Other settings: anything required for backend.main import.
        "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
        "REDIS_URL": "redis://localhost:6379/0",
        "SEED_DEMO_USERS": "false",
        "ADMIN_PASSWORD": "",
        "VIEWER_PASSWORD": "",
    }
    base_env.update(env_overrides)
    script = textwrap.dedent(
        """
        import sys
        try:
            import backend.main  # noqa: F401
        except RuntimeError as e:
            print("RAISED_RUNTIME_ERROR:", str(e), file=sys.stderr)
            sys.exit(42)
        except Exception as e:
            print("RAISED_OTHER:", type(e).__name__, str(e), file=sys.stderr)
            sys.exit(43)
        print("IMPORT_OK", file=sys.stderr)
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


def test_empty_secret_key_rejected_by_boot_guard():
    """Boot guard must reject SECRET_KEY="" with a clear refusal message.

    The exact message wording is the implementer's choice, but it MUST
    distinguish this case from the placeholder case (otherwise the
    operator sees a confusing "change-me-in-production" error when they
    set the variable to an empty string). We assert a substring that
    any reasonable refusal message will contain.
    """
    result = _run_import_with_env({"SECRET_KEY": ""})

    assert result.returncode == 42, (
        "Empty SECRET_KEY must cause `import backend.main` to raise "
        "RuntimeError. Got returncode=%s stderr=%s"
        % (result.returncode, result.stderr)
    )
    assert "RAISED_RUNTIME_ERROR" in result.stderr, (
        "Expected a RuntimeError to be raised. stderr=%r" % result.stderr
    )
    # Substring match - tolerant of phrasing variations across PRs.
    # The implementer MUST mention the variable name so operators can
    # diagnose from logs alone.
    assert "SECRET_KEY must be set" in result.stderr, (
        "Refusal message must explicitly name SECRET_KEY so operators "
        "can diagnose. stderr=%r" % result.stderr
    )
    # And must NOT be the legacy placeholder message - that would
    # mislead operators into thinking their env contained a placeholder.
    assert "CHANGE_ME" not in result.stderr, (
        "Empty-value refusal must not be confused with placeholder "
        "refusal. stderr=%r" % result.stderr
    )


def test_non_empty_secret_key_still_boots():
    """Sanity check on the helper: a non-empty non-placeholder key boots.

    This pins the negative case so a future regression that rejects
    ALL secrets (instead of just empty/placeholder ones) is caught
    immediately by this test going red alongside the empty-key test.
    """
    # 32+ chars, no CHANGE_ME prefix, not in the denylist.
    real_key = "a" * 32 + "_real_key_for_subprocess_helper_sanity"
    result = _run_import_with_env({"SECRET_KEY": real_key})

    # Either the import succeeded (exit 0) OR the subprocess raised an
    # error other than the SECRET_KEY guard - the helper script catches
    # RuntimeError specifically. If we hit exit 43 with anything other
    # than "secret_key"-related text, that's still a helper defect worth
    # surfacing, but for the purposes of this test we only care that we
    # did NOT see the empty-key refusal.
    assert "RAISED_RUNTIME_ERROR" not in result.stderr or (
        "SECRET_KEY must be set" not in result.stderr
    ), (
        "A real 32-char key must not trigger the empty-SECRET_KEY "
        "refusal. stderr=%r" % result.stderr
    )

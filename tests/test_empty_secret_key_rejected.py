"""
Regression tests for PR-B (hardening #2): the boot guard must reject an
empty SECRET_KEY, not just placeholders or short keys.

Bug B-C1-SECRET-KEY-2026-06-27 root-caused a missing-secret case: when
SECRET_KEY was set to "" in the environment, pydantic-settings fell back
to the `change-me-in-production` default and the existing placeholder
check happened to catch it - but only by accident. After PR-B the default
becomes "" (empty string) and the boot guard MUST refuse empty values
explicitly, regardless of placeholder detection.

Why this is in-process (post PR-C):
- conftest.py sets SECRET_KEY via os.environ.setdefault BEFORE importing
  backend.main.
- After PR-C, the guard lives in `_check_secret_key()` (called from
  lifespan startup), not at module-load-time, so we can invoke it
  directly via monkeypatched settings instead of relying on import-time
  crash. This also lets the test assert against the same Settings
  instance the production code reads from.
"""
from __future__ import annotations

import pytest


def test_empty_secret_key_rejected_by_boot_guard(monkeypatch):
    """Boot guard must reject SECRET_KEY="" with a clear refusal message.

    The exact message wording is the implementer's choice, but it MUST
    distinguish this case from the placeholder case (otherwise the
    operator sees a confusing "change-me-in-production" error when they
    set the variable to an empty string). We assert a substring that
    any reasonable refusal message will contain.
    """
    import backend.main as _bm
    # Override the cached settings SECRET_KEY to empty. _check_secret_key
    # reads settings.SECRET_KEY at call time, so this propagates without
    # needing to bust the lru_cache.
    monkeypatch.setattr(_bm.settings, "SECRET_KEY", "")

    with pytest.raises(RuntimeError) as exc_info:
        _bm._check_secret_key()

    msg = str(exc_info.value)
    assert "SECRET_KEY must be set" in msg, (
        "Refusal message must explicitly name SECRET_KEY so operators "
        "can diagnose. Got: %r" % msg
    )
    # Must NOT be confused with the legacy placeholder message -
    # otherwise operators see a misleading "change-me-in-production" error
    # when their env actually contains an empty value.
    assert "CHANGE_ME" not in msg, (
        "Empty-value refusal must not be confused with placeholder "
        "refusal. Got: %r" % msg
    )


def test_non_empty_secret_key_still_boots(monkeypatch):
    """Sanity check: a non-empty non-placeholder key passes the guard.

    This pins the negative case so a future regression that rejects
    ALL secrets (instead of just empty/placeholder ones) is caught
    immediately by this test going red alongside the empty-key test.
    """
    import backend.main as _bm
    real_key = "a" * 32 + "_real_key_for_guard_sanity_check"
    monkeypatch.setattr(_bm.settings, "SECRET_KEY", real_key)

    # Must NOT raise.
    _bm._check_secret_key()

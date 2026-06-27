"""
Regression tests for the SECRET_KEY placeholder boot check.

Critical (2026-06-27): the previous equality check at backend/main.py only
rejected the literal "change-me-in-production" and keys shorter than 32 chars.
The .env.example placeholder `CHANGE_ME_GENERATE_WITH_OPENSSL_RAND_HEX_32`
is 44 chars and slipped past both checks. An operator copying .env.example
to .env could boot the backend with a publicly-known JWT signing key, and
anyone with the source code could forge admin tokens.

These tests pin the fix in place: `_is_placeholder_secret_key` must reject
both the denylist members and any value matching the `change_me`/`change-me`
convention used across .env.example.
"""
import pytest

from backend.main import _is_placeholder_secret_key, _SECRET_KEY_PLACEHOLDERS


# ── Denylist members ────────────────────────────────────────────────────

def test_old_placeholder_rejected():
    """The original placeholder literal must still be rejected (regression)."""
    assert _is_placeholder_secret_key("change-me-in-production") is True


def test_new_placeholder_rejected():
    """The .env.example placeholder must be rejected (the actual bug)."""
    assert _is_placeholder_secret_key("CHANGE_ME_GENERATE_WITH_OPENSSL_RAND_HEX_32") is True


# ── Anchored prefix convention ──────────────────────────────────────────

@pytest.mark.parametrize("value", [
    "CHANGE_ME",
    "change_me",
    "CHANGE_ME_LATER",
    "CHANGE-ME",
    "change-me-now",
    "CHANGE_ME_GENERATE_WITH_OPENSSL_RAND_HEX_32",  # the .env.example literal
])
def test_placeholder_prefix_rejected(value):
    """`.env.example` placeholders start with `CHANGE_ME_*` / `change-me-*`.
    The anchored prefix regex catches the convention without needing manual
    denylist updates when .env.example evolves."""
    assert _is_placeholder_secret_key(value) is True


@pytest.mark.parametrize("value", [
    # `change_me` letters in the middle, not at the start — a real passphrase
    # like this must boot, not get falsely rejected.
    "please_change_me_quarterly",
    "exchangeme123!",
    # The conftest test secret — must remain a non-placeholder.
    "test-secret-key-32-chars-long-for-tests-only-yes",
])
def test_change_me_in_middle_passes(value):
    """Substring match anywhere-in-string would over-reject; anchoring on
    the prefix lets legitimate passphrases through."""
    assert _is_placeholder_secret_key(value) is False


# ── Legitimate keys pass the helper ──────────────────────────────────────

def test_openssl_rand_hex_output_passes():
    """`openssl rand -hex 32` produces 64 hex chars — must not collide."""
    import secrets
    real_key = secrets.token_hex(32)
    assert len(real_key) == 64
    assert _is_placeholder_secret_key(real_key) is False


def test_conftest_test_secret_passes():
    """tests/conftest.py sets SECRET_KEY to a fixed test value — must
    not look like a placeholder, otherwise the test suite can't import
    backend.main."""
    assert _is_placeholder_secret_key(
        "test-secret-key-32-chars-long-for-tests-only-yes"
    ) is False


def test_short_non_placeholder_passes_helper():
    """A short key that doesn't match the placeholder pattern is the
    helper's concern only — length enforcement is the boot check's
    separate guard."""
    assert _is_placeholder_secret_key("short") is False


# ── Integration with the test environment ────────────────────────────────

def test_denylist_locks_legacy_literal():
    """The original placeholder literal must remain in the denylist —
    dropping it would let the documented fix regress silently. This pins
    the regression marker that's been in production since 2024."""
    assert "change-me-in-production" in _SECRET_KEY_PLACEHOLDERS, (
        "Legacy placeholder literal 'change-me-in-production' must remain "
        "in the denylist — see module docstring for incident context."
    )
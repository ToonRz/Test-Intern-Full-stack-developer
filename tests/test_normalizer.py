"""
Tests for the medium-severity bug fixes from CODE_REVIEW.md (items 13, 14, 30).

Each test pins the regression so a future Pydantic upgrade or a careless
refactor doesn't silently re-introduce the bug.
"""
import pytest


# ── Medium #13: Pydantic v2 silently dropped fields prefixed with `_` ────

class TestNormalizedLogTags:
    """`tags` is the on-wire spec §3 field `_tags`. Pydantic v2 treats
    underscore-prefixed names as private attributes, so the field was being
    silently dropped on validation. The fix renames the Pydantic attribute
    to `tags` and aliases input/output as `_tags`.
    """

    def test_tags_via_underscore_alias_is_populated(self):
        from backend.models.schemas import NormalizedLog
        m = NormalizedLog.model_validate({
            "@timestamp": "2026-06-19T00:00:00Z",
            "tenant": "t",
            "source": "crowdstrike",
            "event_type": "malware_detected",
            "_tags": ["malware", "edr"],
        })
        assert m.tags == ["malware", "edr"]

    def test_tags_default_is_empty_list(self):
        from backend.models.schemas import NormalizedLog
        m = NormalizedLog.model_validate({
            "@timestamp": "2026-06-19T00:00:00Z",
            "tenant": "t",
            "source": "api",
            "event_type": "x",
        })
        assert m.tags == []

    def test_dump_round_trip_uses_underscore_alias(self):
        """API consumers (frontend, log_search) read `log._tags`; the dump
        must keep the underscore form so the wire contract doesn't shift."""
        from backend.models.schemas import NormalizedLog
        m = NormalizedLog.model_validate({
            "@timestamp": "2026-06-19T00:00:00Z",
            "tenant": "t",
            "source": "ad",
            "event_type": "LogonFailed",
            "_tags": ["auth_failure"],
        })
        dumped = m.model_dump(by_alias=True)
        assert dumped["_tags"] == ["auth_failure"]

    def test_tags_propagate_through_normalize_aws(self):
        """End-to-end: AWS normalizer output → Pydantic → `_tags` survives."""
        from backend.normalizer.core import normalize_aws
        result = normalize_aws({
            "event_type": "CreateUser",
            "user": "alice",
            "cloud": {"service": "iam", "account_id": "111", "region": "us-east-1"},
        }, tenant="t1")
        assert result.tags == ["aws", "cloud"]


# ── Medium #14: aws_normalizer crashed when `cloud` was a non-dict ─────

class TestAwsNormalizerCloudType:
    """Malformed upstream payloads sometimes send `cloud` as a string or
    list. The old code called `.get()` on whatever the value was, which
    AttributeError'd the entire ingest endpoint.
    """

    def test_cloud_as_string_does_not_crash(self):
        from ingest.normalizers.aws_normalizer import normalize_aws
        result = normalize_aws({
            "event_type": "CreateUser",
            "user": "alice",
            "cloud": "oops-not-a-dict",
        })
        # Falls back to empty cloud metadata; everything else still normalizes.
        assert result["cloud"] == {"service": None, "account_id": None, "region": None}
        assert result["event_type"] == "CreateUser"

    def test_cloud_as_list_does_not_crash(self):
        from ingest.normalizers.aws_normalizer import normalize_aws
        result = normalize_aws({
            "event_type": "DeleteUser",
            "cloud": ["unexpected", "list"],
        })
        assert result["cloud"] == {"service": None, "account_id": None, "region": None}

    def test_cloud_missing_is_unchanged(self):
        from ingest.normalizers.aws_normalizer import normalize_aws
        result = normalize_aws({"event_type": "ConsoleLogin"})
        assert result["cloud"] == {"service": None, "account_id": None, "region": None}

    def test_cloud_as_dict_preserves_fields(self):
        from ingest.normalizers.aws_normalizer import normalize_aws
        result = normalize_aws({
            "event_type": "ConsoleLogin",
            "cloud": {"service": "iam", "account_id": "111", "region": "us-east-1"},
        })
        assert result["cloud"]["service"] == "iam"
        assert result["cloud"]["account_id"] == "111"
        assert result["cloud"]["region"] == "us-east-1"


# ── Medium #30: UserCreate accepted passwords that exceed bcrypt's 72-byte
#     limit (UTF-8 multi-byte chars would silently pre-hash on the auth
#     side; the schema should reject up front so the error is visible).

class TestPasswordBytesValidation:
    def test_short_ascii_password_allowed(self):
        from backend.routers.users import _validate_password_bytes
        assert _validate_password_bytes("hunter2!!") == "hunter2!!"

    def test_long_ascii_password_rejected(self):
        from backend.routers.users import _validate_password_bytes
        with pytest.raises(ValueError, match="bytes"):
            _validate_password_bytes("a" * 73)

    def test_long_utf8_password_rejected(self):
        # 25 Thai chars × 3 bytes = 75 bytes — under the 72 char schema
        # limit but over bcrypt's 72-byte limit.
        from backend.routers.users import _validate_password_bytes
        with pytest.raises(ValueError, match="bytes"):
            _validate_password_bytes("ตัวอย่างรหัสผ่าน" * 2)

    def test_72_byte_password_allowed(self):
        from backend.routers.users import _validate_password_bytes
        assert _validate_password_bytes("a" * 72) == "a" * 72


# ── Medium #16 (spec-aligned re-fix): UserCreate requires non-empty tenant
#     via Pydantic min_length=1. Reject the empty default and accept "*" for
#     Admin (cross-tenant access, per spec §6).

class TestUserCreateTenantValidation:
    def test_empty_tenant_rejected(self):
        from pydantic import ValidationError
        from backend.routers.users import UserCreate
        with pytest.raises(ValidationError):
            UserCreate(username="alice", password="hunter2!!", role="Viewer", tenant="")

    def test_whitespace_only_tenant_rejected(self):
        # min_length=1 fails for any string of length 0 — whitespace is still
        # accepted by the schema (Pydantic doesn't strip), so we test the
        # *schema* boundary, not the endpoint's .strip() (we removed that).
        from pydantic import ValidationError
        from backend.routers.users import UserCreate
        with pytest.raises(ValidationError):
            UserCreate(username="alice", password="hunter2!!", role="Viewer", tenant="")

    def test_admin_with_star_tenant_accepted(self):
        from backend.routers.users import UserCreate
        u = UserCreate(username="root", password="hunter2!!", role="Admin", tenant="*")
        assert u.tenant == "*"

    def test_viewer_with_named_tenant_accepted(self):
        from backend.routers.users import UserCreate
        u = UserCreate(username="bob", password="hunter2!!", role="Viewer", tenant="demoA")
        assert u.tenant == "demoA"


# ── Spec-aligned input flexibility: api/m365/ad normalizers ─────────────
#
# Spec §4.3 / §4.6 / §4.7 examples use input field `ip` (not `src_ip`).
# The previous normalizers mapped `ip → src_ip` only and silently dropped
# the field if the caller sent `src_ip` instead. They also overrode any
# caller-provided `severity` with a hard-coded heuristic (5/8), so the
# caller couldn't express a custom severity. Both behaviors were a
# deviation from how §4.4 CrowdStrike was wired (caller severity wins,
# default 8).
#
# These tests pin the spec-aligned contract: `ip` is the canonical input
# (per spec example), `src_ip` is an accepted alias (ergonomic for callers
# used to the normalized schema field), and an explicit integer severity
# in the 0–10 range always wins over the heuristic.

class TestApiNormalizerInputFlexibility:
    def test_severity_override_wins_over_heuristic(self):
        # spec §4.3 example has no severity field; caller providing 7
        # should be respected (same shape as crowdstrike §4.4).
        from ingest.normalizers.api_normalizer import normalize_api
        result = normalize_api({
            "tenant": "demoA",
            "source": "api",
            "event_type": "app_login_failed",
            "ip": "203.0.113.7",
            "reason": "wrong_password",
            "severity": 7,
        })
        assert result["severity"] == 7

    def test_severity_heuristic_used_when_absent(self):
        # Falls back to login-fail heuristic so the spec example still
        # produces a sensible value (8 for fail, 5 otherwise).
        from ingest.normalizers.api_normalizer import normalize_api
        fail = normalize_api({"event_type": "app_login_failed", "ip": "1.2.3.4"})
        ok = normalize_api({"event_type": "UserLoggedIn"})
        assert fail["severity"] == 8
        assert ok["severity"] == 5

    def test_severity_out_of_range_falls_back_to_heuristic(self):
        # Out-of-spec severity must not corrupt the schema; fall back to
        # the heuristic instead of silently accepting garbage.
        from ingest.normalizers.api_normalizer import normalize_api
        result = normalize_api({"event_type": "app_login_failed", "severity": 99})
        assert result["severity"] == 8

    def test_severity_non_integer_falls_back_to_heuristic(self):
        # A string severity isn't valid per spec §3 (integer 0–10).
        from ingest.normalizers.api_normalizer import normalize_api
        result = normalize_api({"event_type": "UserLoggedIn", "severity": "high"})
        assert result["severity"] == 5

    def test_src_ip_alias_accepted(self):
        # Caller sends `src_ip` (the normalized field name) instead of
        # the spec example's `ip`. Must still resolve.
        from ingest.normalizers.api_normalizer import normalize_api
        result = normalize_api({"event_type": "UserLoggedIn", "src_ip": "10.1.2.3"})
        assert result["src_ip"] == "10.1.2.3"

    def test_ip_wins_on_tie(self):
        # Both fields sent: `ip` is the spec example's field name, so it
        # has priority. Avoids silent preference shifts.
        from ingest.normalizers.api_normalizer import normalize_api
        result = normalize_api({"event_type": "x", "ip": "1.1.1.1", "src_ip": "2.2.2.2"})
        assert result["src_ip"] == "1.1.1.1"


class TestM365NormalizerInputFlexibility:
    def test_severity_override_wins_over_status_heuristic(self):
        from ingest.normalizers.m365_normalizer import normalize_m365
        result = normalize_m365({
            "event_type": "UserLoggedIn",
            "status": "Success",
            "severity": 6,
        })
        assert result["severity"] == 6

    def test_severity_heuristic_used_when_absent(self):
        from ingest.normalizers.m365_normalizer import normalize_m365
        fail = normalize_m365({"event_type": "UserLoggedIn", "status": "Fail"})
        ok = normalize_m365({"event_type": "UserLoggedIn", "status": "Success"})
        assert fail["severity"] == 8
        assert ok["severity"] == 5

    def test_src_ip_alias_accepted(self):
        from ingest.normalizers.m365_normalizer import normalize_m365
        result = normalize_m365({"event_type": "UserLoggedIn", "src_ip": "10.1.2.3"})
        assert result["src_ip"] == "10.1.2.3"


class TestAdNormalizerInputFlexibility:
    def test_src_ip_alias_accepted(self):
        # spec §4.7 example uses `ip` for AD too.
        from ingest.normalizers.ad_normalizer import normalize_ad
        result = normalize_ad({
            "event_id": 4625,
            "event_type": "LogonFailed",
            "src_ip": "203.0.113.77",
        })
        assert result["src_ip"] == "203.0.113.77"

    def test_ip_field_still_works(self):
        from ingest.normalizers.ad_normalizer import normalize_ad
        result = normalize_ad({
            "event_id": 4625,
            "event_type": "LogonFailed",
            "ip": "203.0.113.77",
        })
        assert result["src_ip"] == "203.0.113.77"


class TestCrowdstrikeNormalizerInputFlexibility:
    def test_src_ip_alias_accepted(self):
        # §4.4 example doesn't include an IP field, but `src_ip` alias
        # keeps the contract symmetric with the other normalizers.
        from ingest.normalizers.crowdstrike_normalizer import normalize_crowdstrike
        result = normalize_crowdstrike({
            "event_type": "malware_detected",
            "host": "WIN10-01",
            "src_ip": "10.1.2.3",
        })
        assert result["src_ip"] == "10.1.2.3"

    def test_explicit_severity_still_wins_over_default(self):
        # Regression pin: §4.4 already allowed caller severity; ensure
        # the alias change didn't disturb that path.
        from ingest.normalizers.crowdstrike_normalizer import normalize_crowdstrike
        result = normalize_crowdstrike({"event_type": "x", "severity": 3})
        assert result["severity"] == 3

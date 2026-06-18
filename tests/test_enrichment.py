"""
Tests for the enrichment service — GeoIP + reverse DNS.

These are pure-Python unit tests; no Redis or GeoIP DB is required because
the service gracefully returns None when its dependencies are missing.
"""
import pytest
import sys
import os

# Ensure the project root is on path so `from backend...` resolves when this
# file is run in isolation (e.g. `pytest tests/test_enrichment.py`).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.services.enrichment import (
    GeoIPService, ReverseDNSService, EnrichmentService,
    GeoIPResult, EnrichmentResult,
)


class TestGeoIPService:
    """Test GeoIP lookups (gracefully no-ops when DB is unavailable)."""

    def test_invalid_ip_returns_none(self):
        assert GeoIPService.lookup("not-an-ip") is None

    def test_localhost_returns_none(self):
        assert GeoIPService.lookup("127.0.0.1") is None

    def test_private_ip_returns_none(self):
        assert GeoIPService.lookup("192.168.1.1") is None

    def test_valid_ip_returns_georesult_or_none(self):
        # May be None if GeoLite2 DB is not installed; either is acceptable.
        result = GeoIPService.lookup("8.8.8.8")
        assert result is None or isinstance(result, GeoIPResult)


class TestReverseDNSService:
    """Test reverse DNS lookups."""

    async def test_private_ip_returns_none(self):
        assert await ReverseDNSService.lookup("192.168.1.1") is None

    async def test_invalid_ip_returns_none(self):
        assert await ReverseDNSService.lookup("not-an-ip") is None


class TestEnrichmentService:
    """Test enrichment orchestration."""

    async def test_empty_ip_returns_empty_result(self):
        result = await EnrichmentService.enrich("")
        assert isinstance(result, EnrichmentResult)
        assert result.geo_country is None
        assert result.rdns_hostname is None
        assert result._tags == []

    async def test_none_ip_returns_empty_result(self):
        result = await EnrichmentService.enrich(None)
        assert isinstance(result, EnrichmentResult)
        assert result.geo_country is None

    async def test_enrichment_returns_enrichment_result(self):
        result = await EnrichmentService.enrich("8.8.8.8")
        assert isinstance(result, EnrichmentResult)
        assert isinstance(result._tags, list)

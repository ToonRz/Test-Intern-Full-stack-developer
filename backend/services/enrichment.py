"""
Enrichment Service — GeoIP + Reverse DNS lookup.
Caches results in Redis with 1-hour TTL.
"""
import asyncio
import ipaddress
import socket
import threading
from typing import Optional
from dataclasses import dataclass
from functools import lru_cache

import redis.asyncio as redis
import geoip2.database as geoip2

from backend.config import get_settings

settings = get_settings()

# Suspicious countries for auto-tagging
SUSPICIOUS_COUNTRIES = {"CN", "RU", "KP", "IR", "BY", "UA"}
GEOLITE2_URL = "https://github.com/P3TERX/GeoLite2/releases/download/v2.1.0/GeoLite2-City.mmdb"

# Critical B-C11: hard cap on the blocking DNS call so a slow upstream
# resolver can't stall the ingest pipeline indefinitely.
_RDNS_TIMEOUT_SECONDS = 2.0


@dataclass
class GeoIPResult:
    country: Optional[str] = None
    city: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    timezone: Optional[str] = None


@dataclass
class EnrichmentResult:
    geo_country: Optional[str] = None
    geo_city: Optional[str] = None
    geo_lat: Optional[float] = None
    geo_lon: Optional[float] = None
    rdns_hostname: Optional[str] = None
    _tags: list[str] = None

    def __post_init__(self):
        if self._tags is None:
            self._tags = []


class RedisCache:
    _instance: Optional[redis.Redis] = None
    # Critical B-C12: a class-level mutable singleton needs a lock, otherwise
    # two coroutines racing on the first call can both pass the None-check
    # and create two different clients. The second write wins, the first
    # client is leaked, and Redis ConnectionPool accounting drifts.
    _lock = threading.Lock()

    @classmethod
    async def get(cls) -> redis.Redis:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = redis.from_url(
                        settings.REDIS_URL,
                        encoding="utf-8",
                        decode_responses=True,
                    )
        return cls._instance


class GeoIPService:
    _db = None

    @classmethod
    def get_db(cls):
        if cls._db is None:
            # Path configurable via GEOIP_DB_PATH
            db_path = getattr(settings, 'GEOIP_DB_PATH', '/var/lib/geoip/GeoLite2-City.mmdb')
            try:
                cls._db = geoip2.Reader(db_path)
            except Exception:
                # GeoIP database not available — enrichment will be skipped
                cls._db = None
        return cls._db

    @classmethod
    def lookup(cls, ip: str) -> Optional[GeoIPResult]:
        db = cls.get_db()
        if db is None:
            return None

        # Skip private/RFC1918/loopback/link-local addresses. The previous
        # implementation used `socket.inet_aton` which only accepts IPv4
        # dotted-quad — any IPv6 address raised and silently returned None.
        try:
            ip_obj = ipaddress.ip_address(ip)
        except ValueError:
            return None
        if (
            ip_obj.is_private
            or ip_obj.is_loopback
            or ip_obj.is_link_local
            or ip_obj.is_multicast
            or ip_obj.is_reserved
            or ip_obj.is_unspecified
        ):
            return None

        try:
            response = db.city(ip)
            return GeoIPResult(
                country=response.country.iso_code,
                city=response.city.name,
                latitude=response.location.latitude,
                longitude=response.location.longitude,
                timezone=response.location.time_zone,
            )
        except Exception:
            return None


class ReverseDNSService:
    @classmethod
    async def lookup(cls, ip: str) -> Optional[str]:
        # Critical B-C11: validate the IP with the stdlib `ipaddress` module
        # so IPv6 and link-local addresses don't fall through the (IPv4-only)
        # `socket.inet_aton` check. Also bound the blocking gethostbyaddr
        # call with a timeout — a slow upstream resolver would otherwise stall
        # the entire ingest coroutine.
        try:
            ip_obj = ipaddress.ip_address(ip)
        except ValueError:
            return None
        if (
            ip_obj.is_private
            or ip_obj.is_loopback
            or ip_obj.is_link_local
            or ip_obj.is_multicast
            or ip_obj.is_reserved
            or ip_obj.is_unspecified
        ):
            return None

        loop = asyncio.get_running_loop()
        try:
            hostname, _, _ = await asyncio.wait_for(
                loop.run_in_executor(None, socket.gethostbyaddr, ip),
                timeout=_RDNS_TIMEOUT_SECONDS,
            )
            return hostname
        except (asyncio.TimeoutError, socket.herror, socket.gaierror, OSError):
            return None


class EnrichmentService:
    """
    Orchestrates GeoIP + RDNS enrichment with Redis caching.
    Called during ingest pipeline for each log with a src_ip.
    """

    CACHE_TTL = 3600  # 1 hour

    @classmethod
    async def enrich(cls, src_ip: str) -> EnrichmentResult:
        if not src_ip:
            return EnrichmentResult()

        cache_key_geo = f"geoip:{src_ip}"
        cache_key_rdns = f"rdns:{src_ip}"

        try:
            cache = await RedisCache.get()
        except Exception:
            cache = None

        geo: Optional[GeoIPResult] = None
        rdns_hostname: Optional[str] = None
        tags: list[str] = []

        # Try cache first — High #8: on connection failure, drop the cached
        # singleton so the next call recreates it instead of reusing a
        # broken connection for the rest of the process lifetime.
        if cache:
            try:
                cached_geo = await cache.hgetall(cache_key_geo)
                if cached_geo:
                    geo = GeoIPResult(
                        country=cached_geo.get('country'),
                        city=cached_geo.get('city'),
                        latitude=float(cached_geo['lat']) if cached_geo.get('lat') else None,
                        longitude=float(cached_geo['lon']) if cached_geo.get('lon') else None,
                        timezone=cached_geo.get('timezone'),
                    )
                rdns_hostname = await cache.get(cache_key_rdns)
            except (redis.ConnectionError, redis.TimeoutError, OSError):
                # Reset singleton so the next request reconnects.
                RedisCache._instance = None
                cache = None

        # Cache miss — do actual lookups
        if geo is None:
            geo = GeoIPService.lookup(src_ip)

        if rdns_hostname is None:
            rdns_hostname = await ReverseDNSService.lookup(src_ip)

        # Update cache
        if cache and src_ip:
            try:
                if geo:
                    await cache.hset(cache_key_geo, mapping={
                        'country': geo.country or '',
                        'city': geo.city or '',
                        'lat': str(geo.latitude) if geo.latitude else '',
                        'lon': str(geo.longitude) if geo.longitude else '',
                        'timezone': geo.timezone or '',
                    })
                    await cache.expire(cache_key_geo, cls.CACHE_TTL)

                if rdns_hostname:
                    await cache.set(cache_key_rdns, rdns_hostname, ex=cls.CACHE_TTL)
            except (redis.ConnectionError, redis.TimeoutError, OSError):
                RedisCache._instance = None

        # Auto-tag suspicious countries
        if geo and geo.country in SUSPICIOUS_COUNTRIES:
            tags.append(f"suspicious_country:{geo.country}")

        return EnrichmentResult(
            geo_country=geo.country if geo else None,
            geo_city=geo.city if geo else None,
            geo_lat=geo.latitude if geo else None,
            geo_lon=geo.longitude if geo else None,
            rdns_hostname=rdns_hostname,
            _tags=tags,
        )

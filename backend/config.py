from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # App
    APP_NAME: str = "Log Management System"
    DEBUG: bool = False
    API_PREFIX: str = "/api/v1"

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@postgres:5432/logs"

    # Redis (for caching enrichment)
    REDIS_URL: str = "redis://redis:6379/0"

    # JWT
    SECRET_KEY: str = "change-me-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # Low #27: HttpOnly cookie for browser auth — XSS can't read
    # `document.cookie` for this cookie, so a stolen-token-via-injected-script
    # attack is mitigated. `Secure` is auto-disabled for HTTP development
    # origins (localhost) so local dev still works; production CORS origins
    # are HTTPS-only. `SameSite=Lax` blocks cross-origin POST/PUT/DELETE that
    # would otherwise be eligible for CSRF, while still allowing top-level
    # navigation (so the SPA can deep-link to /logs etc.).
    AUTH_COOKIE_NAME: str = "access_token"
    AUTH_COOKIE_PATH: str = "/api/v1"
    AUTH_COOKIE_SAMESITE: str = "lax"

    # Syslog
    SYSLOG_HOST: str = "0.0.0.0"
    SYSLOG_PORT: int = 514

    # Retention
    DATA_RETENTION_DAYS: int = 7

    # GeoIP
    GEOIP_DB_PATH: str = "/var/lib/geoip/GeoLite2-City.mmdb"

    # CORS
    ALLOWED_ORIGINS: str = "http://localhost:3000,http://frontend:3000"

    # Rate limiting
    RATE_LIMIT_PER_MINUTE: int = 100

    # Demo user seeding — only used in dev/CI; production sets this to "false".
    # Declared here so pydantic-settings (v2.1+) doesn't reject it as an
    # unknown field when conftest.py or docker-compose exports it.
    SEED_DEMO_USERS: str = "false"

    # OpenTelemetry
    OTEL_SERVICE_NAME: str = "log-management"
    OTEL_EXPORTER_OTLP_ENDPOINT: str = ""  # empty → setup_telemetry() short-circuits

    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    return Settings()

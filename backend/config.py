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

    # OpenTelemetry
    OTEL_SERVICE_NAME: str = "log-management"
    OTEL_EXPORTER_OTLP_ENDPOINT: str = "http://localhost:4317"

    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    return Settings()

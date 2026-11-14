"""Konfigurasi runtime dari environment (12-factor)."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "postgresql+asyncpg://rani:rani@localhost:5432/rani"
    REDIS_URL: str = "redis://localhost:6379/0"

    RANI_ADMIN_USER: str = "admin"
    RANI_ADMIN_PASSWORD: str = ""
    RANI_INGEST_PEPPER: str = "dev-pepper-change-me"

    RANI_DEFAULT_INTERVAL_S: int = 3600
    RANI_TS_SKEW_S: int = 300
    RANI_OFFLINE_AFTER_S: int = 3 * 3600
    RANI_RATE_LIMIT_PER_MIN: int = 30
    RANI_SESSION_TTL_H: int = 12

    # Push tanpa enroll/HMAC (agent dikenali dari machine_id/hostname payload).
    # Matikan (0) untuk mewajibkan signature semua agent.
    RANI_TOKENLESS_PUSH: bool = True
    # Custom report SQL: eksekusi lewat role DB read-only terpisah.
    RANI_REPORT_DB_USER: str = "rani_report"
    RANI_REPORT_DB_PASSWORD: str = ""
    RANI_REPORT_MAX_ROWS: int = 1000
    RANI_REPORT_TIMEOUT_MS: int = 8000

    # Direktori artefak agent yang bisa diunduh dari halaman /agents (mount read-only).
    RANI_AGENT_DIR: str = "/srv/release"
    RANI_AGENT_SCRIPTS_DIR: str = "/srv/scripts"

    RANI_ENV: str = "dev"
    RANI_LOG_LEVEL: str = "info"

    @property
    def database_url_sync(self) -> str:
        return self.DATABASE_URL.replace("+asyncpg", "+psycopg2")


@lru_cache
def get_settings() -> Settings:
    return Settings()
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

    RANI_ENV: str = "dev"
    RANI_LOG_LEVEL: str = "info"

    @property
    def database_url_sync(self) -> str:
        return self.DATABASE_URL.replace("+asyncpg", "+psycopg2")


@lru_cache
def get_settings() -> Settings:
    return Settings()
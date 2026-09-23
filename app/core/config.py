"""Application settings loaded from environment variables / .env.

Settings are fail-fast: pydantic-settings raises ValidationError at import/startup time
if a required field is missing, so a misconfigured deployment never serves traffic.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Typed application configuration.

    Required fields have no default and will cause startup to fail with a clear
    pydantic validation error if unset, per CLAUDE.md §3/§13 (fail fast).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    APP_ENV: Literal["dev", "test", "prod"] = "dev"
    LOG_LEVEL: str = "INFO"
    LOG_PII: bool = False

    # Neon pooled endpoint (PgBouncer transaction mode) — used by the app at runtime.
    DATABASE_URL: str
    # Neon direct (non-pooled) endpoint — used by Alembic migrations only.
    DATABASE_URL_DIRECT: str

    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10

    API_KEY: SecretStr
    VAPI_WEBHOOK_SECRET: SecretStr
    VAPI_API_KEY: SecretStr | None = None

    DASHBOARD_USERNAME: str
    DASHBOARD_PASSWORD: SecretStr

    CORS_ORIGINS: Annotated[list[str], NoDecode] = Field(default_factory=list)
    RATE_LIMIT_DEFAULT: str = "60/minute"

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _split_cors_origins(cls, value: object) -> object:
        """The env var is a comma-separated string, e.g. 'https://a.com,https://b.com'."""
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    """Return the cached, process-wide Settings instance."""
    return Settings()

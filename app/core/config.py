"""Application settings loaded from environment variables / .env.

Settings are fail-fast: pydantic-settings raises ValidationError at import/startup time
if a required field is missing, so a misconfigured deployment never serves traffic.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Any, Literal

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
    # Local Docker Compose Postgres, used only by integration tests. Not required outside
    # of running `pytest tests/integration`.
    TEST_DATABASE_URL: str | None = None

    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    # Neon always requires SSL. The local Docker Postgres used by integration tests does
    # not support it, so this is off in the test env only (see .env.example).
    DB_SSL_REQUIRE: bool = True

    API_KEY: SecretStr
    VAPI_WEBHOOK_SECRET: SecretStr
    VAPI_API_KEY: SecretStr | None = None

    DASHBOARD_USERNAME: str
    DASHBOARD_PASSWORD: SecretStr

    CORS_ORIGINS: Annotated[list[str], NoDecode] = Field(default_factory=list)
    RATE_LIMIT_DEFAULT: str = "60/minute"

    # Swagger UI / ReDoc / openapi.json. Handy for reviewers; set false to hide the API
    # surface in production.
    ENABLE_API_DOCS: bool = True
    # Only enable when every request reaches the app over HTTPS (e.g. behind a TLS
    # terminating proxy) — browsers cache HSTS, so enabling it on plain HTTP is harmful.
    ENABLE_HSTS: bool = False
    # Largest accepted request body. End-of-call reports carry full transcripts, so this
    # is generous; anything bigger is rejected with 413 before it reaches a handler.
    MAX_REQUEST_BODY_BYTES: int = 2_000_000

    # Voice tool handlers must never hang a live call; each is wrapped in a timeout.
    VAPI_TOOL_TIMEOUT_SECONDS: float = 8.0
    # DB sessions used to serve the Vapi webhook get a tighter statement_timeout than the
    # rest of the app, so a slow query can't hang a live call either.
    VAPI_WEBHOOK_DB_STATEMENT_TIMEOUT_MS: int = 5000

    # Only needed to run `scripts/sync_vapi.py`, not to serve traffic.
    PUBLIC_BASE_URL: str | None = None
    VAPI_PHONE_NUMBER_ID: str | None = None
    # Rollback knobs for the voice stack in vapi/assistant.json, as JSON objects. Transcriber
    # and voice are *replaced* wholesale (field names differ per provider, e.g. Deepgram
    # `keyterm` vs AssemblyAI `keytermsPrompt`); model is *merged* so the prompt, tools and
    # temperature are kept. Unset = use vapi/assistant.json as committed.
    VAPI_TRANSCRIBER_OVERRIDE: dict[str, Any] | None = None
    VAPI_MODEL_OVERRIDE: dict[str, Any] | None = None
    VAPI_VOICE_OVERRIDE: dict[str, Any] | None = None

    # Mock appointment availability is computed in this timezone (business hours,
    # spoken-back times). IANA name, resolved via zoneinfo.
    CLINIC_TIMEZONE: str = "America/New_York"

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

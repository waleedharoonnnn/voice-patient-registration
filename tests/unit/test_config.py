"""Unit tests for fail-fast settings validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError


def test_settings_raises_when_required_vars_missing(unset_env: None) -> None:
    from app.core.config import Settings

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)  # type: ignore[call-arg]

    missing_fields = {error["loc"][0] for error in exc_info.value.errors()}
    assert "DATABASE_URL" in missing_fields
    assert "API_KEY" in missing_fields


def test_settings_loads_when_required_vars_present(_env: None) -> None:
    from app.core.config import Settings

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.API_KEY.get_secret_value() == "test-api-key"
    assert settings.APP_ENV == "test"


def test_cors_origins_accepts_comma_separated_string(
    _env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("CORS_ORIGINS", "http://a.com, http://b.com")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.CORS_ORIGINS == ["http://a.com", "http://b.com"]

"""Shared pytest fixtures: env setup, app factory, and an httpx AsyncClient."""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

_REQUIRED_ENV: dict[str, str] = {
    "APP_ENV": "test",
    "DATABASE_URL": "postgresql+asyncpg://voiceai:voiceai@localhost:5544/voiceai_test",
    "DATABASE_URL_DIRECT": "postgresql+asyncpg://voiceai:voiceai@localhost:5544/voiceai_test",
    "TEST_DATABASE_URL": "postgresql+asyncpg://voiceai:voiceai@localhost:5544/voiceai_test",
    "API_KEY": "test-api-key",
    "VAPI_WEBHOOK_SECRET": "test-webhook-secret",
    "DASHBOARD_USERNAME": "test-dashboard-user",
    "DASHBOARD_PASSWORD": "test-dashboard-password",
}


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure required settings are present for every test unless a test removes them."""
    for key, value in _REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)


@pytest.fixture
def app(_env: None) -> FastAPI:
    # Import (and therefore Settings()) happens after env vars are set by the _env fixture.
    from app.core.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    return create_app()


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest.fixture
def clear_settings_cache() -> Any:
    from app.core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def unset_env(_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove all required env vars, for testing fail-fast config validation."""
    for key in _REQUIRED_ENV:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("VAPI_API_KEY", raising=False)
    for key in list(os.environ):
        if key.startswith(("API_KEY", "DATABASE_URL", "DASHBOARD_", "VAPI_")):
            monkeypatch.delenv(key, raising=False)

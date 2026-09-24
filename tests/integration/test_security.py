"""Security controls: body-size limit, rate limiting, docs toggle, HSTS, input length
limits, and log hygiene (PII masking, no secrets in logs)."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from httpx import AsyncClient

from app.core.rate_limit import limiter
from tests.integration.conftest import AppFactory

API_KEY = {"X-API-Key": "test-api-key"}
SECRET = {"X-Vapi-Secret": "test-webhook-secret"}

VALID_PATIENT: dict[str, Any] = {
    "first_name": "Log",
    "last_name": "Check",
    "date_of_birth": "06/15/1985",
    "sex": "Female",
    "phone_number": "(212) 555-0144",
    "address_line_1": "1 Test St",
    "city": "Springfield",
    "state": "IL",
    "zip_code": "62704",
}

# --- Request body size -------------------------------------------------------------------


async def test_oversized_body_rejected_with_413(custom_client: AppFactory) -> None:
    async with custom_client(MAX_REQUEST_BODY_BYTES="1000") as client:
        response = await client.post("/patients", content=b"x" * 5000, headers=API_KEY)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


async def test_oversized_chunked_body_rejected_with_413(custom_client: AppFactory) -> None:
    async def chunks() -> AsyncGenerator[bytes]:
        for _ in range(10):
            yield b"x" * 500

    async with custom_client(MAX_REQUEST_BODY_BYTES="1000") as client:
        response = await client.post("/patients", content=chunks(), headers=API_KEY)
    assert response.status_code == 413


async def test_normal_body_is_accepted_under_limit(custom_client: AppFactory) -> None:
    async with custom_client(MAX_REQUEST_BODY_BYTES="1000") as client:
        response = await client.post(
            "/vapi/webhook", json={"message": {"type": "x"}}, headers=SECRET
        )
    assert response.status_code == 200


# --- Rate limiting ------------------------------------------------------------------------


async def test_rate_limit_returns_enveloped_429_with_retry_after(custom_client: AppFactory) -> None:
    limiter.reset()
    async with custom_client(RATE_LIMIT_DEFAULT="3/minute") as client:
        codes = [(await client.get("/providers")).status_code for _ in range(3)]
        blocked = await client.get("/providers")
    limiter.reset()

    assert 429 not in codes
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limited"
    assert int(blocked.headers["retry-after"]) >= 1
    assert blocked.headers["x-content-type-options"] == "nosniff"  # still gets headers


async def test_rate_limit_applies_to_dashboard_but_not_webhook_or_health(
    custom_client: AppFactory,
) -> None:
    limiter.reset()
    async with custom_client(RATE_LIMIT_DEFAULT="2/minute") as client:
        for _ in range(5):
            assert (await client.get("/health")).status_code == 200
            webhook = await client.post(
                "/vapi/webhook", json={"message": {"type": "status-update"}}, headers=SECRET
            )
            assert webhook.status_code == 200
        dashboard = [(await client.get("/dashboard")).status_code for _ in range(3)]
    limiter.reset()
    assert dashboard[-1] == 429


# --- Docs toggle + HSTS ---------------------------------------------------------------


async def test_api_docs_can_be_disabled(custom_client: AppFactory) -> None:
    async with custom_client(ENABLE_API_DOCS="false") as client:
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert (await client.get(path)).status_code == 404, path


async def test_api_docs_enabled_by_default(client: AsyncClient) -> None:
    assert (await client.get("/docs")).status_code == 200


async def test_hsts_off_by_default(client: AsyncClient) -> None:
    assert "strict-transport-security" not in (await client.get("/health")).headers


async def test_hsts_when_enabled(custom_client: AppFactory) -> None:
    async with custom_client(ENABLE_HSTS="true") as client:
        response = await client.get("/health")
    assert response.headers["strict-transport-security"].startswith("max-age=31536000")


# --- Input length limits ------------------------------------------------------------------


@pytest.mark.usefixtures("clean_patients_table")
async def test_overlong_field_is_422_not_500(client: AsyncClient) -> None:
    body = {**VALID_PATIENT, "address_line_1": "x" * 150}
    response = await client.post("/patients", json=body, headers=API_KEY)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


@pytest.mark.usefixtures("clean_patients_table")
async def test_overlong_field_via_voice_is_invalid_not_save_failed(client: AsyncClient) -> None:
    arguments = {**VALID_PATIENT, "insurance_provider": "y" * 500}
    body = {
        "message": {
            "type": "tool-calls",
            "call": {"id": "call-long-field"},
            "toolCallList": [
                {"id": "t1", "function": {"name": "create_patient", "arguments": arguments}}
            ],
        }
    }
    result = (await client.post("/vapi/webhook", json=body, headers=SECRET)).json()
    assert result["results"][0]["result"].startswith("INVALID: insurance_provider")


# --- Logs ---------------------------------------------------------------------------------


@pytest.mark.usefixtures("clean_patients_table")
async def test_logs_mask_pii_and_never_contain_secrets(
    client: AsyncClient, capsys: pytest.CaptureFixture[str]
) -> None:
    from app.core.logging import configure_logging

    # Re-bind the JSON handler to the stdout pytest is capturing *now*; the app fixture
    # configured logging before this test's capture began.
    configure_logging("INFO")
    response = await client.post("/patients", json=VALID_PATIENT, headers=API_KEY)
    assert response.status_code == 201
    await client.post("/vapi/webhook", json={"message": {"type": "status-update"}}, headers=SECRET)

    out = capsys.readouterr().out
    records = [json.loads(line) for line in out.splitlines() if line.startswith("{")]
    created = next((r for r in records if r.get("message") == "patient created"), None)
    assert created is not None, "expected a 'patient created' log line"

    assert created["phone_number"] == "***-***-0144"
    assert created["first_name"] == "L***"
    assert created["last_name"] == "C***"
    assert "2125550144" not in out
    assert "test-api-key" not in out
    assert "test-webhook-secret" not in out
    assert "x-api-key" not in out.lower()

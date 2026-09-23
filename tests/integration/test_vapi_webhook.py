"""Integration tests for POST /vapi/webhook, against the local Docker Postgres."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient

from app.services.patient_service import PatientService
from app.voice import tools as tools_module

pytestmark = pytest.mark.usefixtures("clean_patients_table")

SECRET_HEADER = {"X-Vapi-Secret": "test-webhook-secret"}
FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "vapi"


def _load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES_DIR / name).read_text())


# --- Auth -------------------------------------------------------------------------------


async def test_webhook_requires_secret(client: AsyncClient) -> None:
    response = await client.post("/vapi/webhook", json=_load("status_update.json"))
    assert response.status_code == 401


async def test_webhook_rejects_wrong_secret(client: AsyncClient) -> None:
    response = await client.post(
        "/vapi/webhook", json=_load("status_update.json"), headers={"X-Vapi-Secret": "wrong"}
    )
    assert response.status_code == 401


async def test_webhook_accepts_bearer_auth(client: AsyncClient) -> None:
    response = await client.post(
        "/vapi/webhook",
        json=_load("status_update.json"),
        headers={"Authorization": "Bearer test-webhook-secret"},
    )
    assert response.status_code == 200


# --- Non-tool-call messages --------------------------------------------------------------


async def test_status_update_message_returns_200_empty(client: AsyncClient) -> None:
    response = await client.post(
        "/vapi/webhook", json=_load("status_update.json"), headers=SECRET_HEADER
    )
    assert response.status_code == 200
    assert response.json() == {}


# --- find_patient_by_phone: arguments as object AND as JSON string -----------------------


async def test_find_patient_by_phone_no_match(client: AsyncClient) -> None:
    response = await client.post(
        "/vapi/webhook", json=_load("find_patient_by_phone_object_args.json"), headers=SECRET_HEADER
    )
    assert response.status_code == 200
    result = response.json()["results"][0]["result"]
    assert result == "NO_MATCH"


async def test_find_patient_by_phone_with_string_arguments(client: AsyncClient) -> None:
    """Vapi may send `arguments` as a JSON-encoded string instead of an object."""
    response = await client.post(
        "/vapi/webhook", json=_load("find_patient_by_phone_string_args.json"), headers=SECRET_HEADER
    )
    assert response.status_code == 200
    result = response.json()["results"][0]["result"]
    assert result == "NO_MATCH"


async def test_find_patient_by_phone_invalid_phone(client: AsyncClient) -> None:
    response = await client.post(
        "/vapi/webhook", json=_load("find_patient_by_phone_invalid.json"), headers=SECRET_HEADER
    )
    assert response.status_code == 200
    result = response.json()["results"][0]["result"]
    assert result.startswith("INVALID: phone_number:")


# --- validate_fields ----------------------------------------------------------------------


async def test_validate_fields_invalid_phone(client: AsyncClient) -> None:
    response = await client.post(
        "/vapi/webhook", json=_load("validate_fields_string_args.json"), headers=SECRET_HEADER
    )
    assert response.status_code == 200
    result = response.json()["results"][0]["result"]
    assert result.startswith("INVALID: phone_number:")


# --- create_patient: idempotency -----------------------------------------------------------


async def test_create_patient_then_retry_same_call_id_is_idempotent(client: AsyncClient) -> None:
    payload = _load("create_patient.json")

    first = await client.post("/vapi/webhook", json=payload, headers=SECRET_HEADER)
    assert first.status_code == 200
    first_result = first.json()["results"][0]["result"]
    assert first_result.startswith("SAVED:")

    second = await client.post("/vapi/webhook", json=payload, headers=SECRET_HEADER)
    assert second.status_code == 200
    second_result = second.json()["results"][0]["result"]
    assert second_result.startswith("ALREADY_SAVED:")

    assert first_result.split("patient_id=")[1] == second_result.split("patient_id=")[1]

    list_response = await client.get("/patients", headers={"X-API-Key": "test-api-key"})
    assert list_response.json()["data"]["total"] == 1


async def test_create_patient_invalid_returns_invalid_result(client: AsyncClient) -> None:
    response = await client.post(
        "/vapi/webhook", json=_load("create_patient_invalid.json"), headers=SECRET_HEADER
    )
    assert response.status_code == 200
    result = response.json()["results"][0]["result"]
    assert result.startswith("INVALID:")
    assert "date_of_birth" in result


# --- update_patient: identity check --------------------------------------------------------


async def test_update_patient_identity_mismatch(client: AsyncClient) -> None:
    create_response = await client.post(
        "/vapi/webhook", json=_load("create_patient.json"), headers=SECRET_HEADER
    )
    patient_id = (
        create_response.json()["results"][0]["result"].split("patient_id=")[1].split(";")[0]
    )

    update_payload = _load("update_patient.json")
    update_payload["message"]["toolCallList"][0]["function"]["arguments"]["patient_id"] = patient_id
    update_payload["message"]["toolCallList"][0]["function"]["arguments"]["date_of_birth"] = (
        "01/01/1991"  # wrong DOB
    )

    response = await client.post("/vapi/webhook", json=update_payload, headers=SECRET_HEADER)
    assert response.status_code == 200
    assert response.json()["results"][0]["result"] == "IDENTITY_MISMATCH"


async def test_update_patient_malformed_patient_id_returns_not_found(client: AsyncClient) -> None:
    update_payload = _load("update_patient.json")
    update_payload["message"]["toolCallList"][0]["function"]["arguments"]["patient_id"] = (
        "not-a-uuid"
    )

    response = await client.post("/vapi/webhook", json=update_payload, headers=SECRET_HEADER)
    assert response.status_code == 200
    assert response.json()["results"][0]["result"] == "NOT_FOUND"


async def test_update_patient_invalid_date_of_birth_format(client: AsyncClient) -> None:
    create_response = await client.post(
        "/vapi/webhook", json=_load("create_patient.json"), headers=SECRET_HEADER
    )
    patient_id = (
        create_response.json()["results"][0]["result"].split("patient_id=")[1].split(";")[0]
    )

    update_payload = _load("update_patient.json")
    update_payload["message"]["toolCallList"][0]["function"]["arguments"]["patient_id"] = patient_id
    update_payload["message"]["toolCallList"][0]["function"]["arguments"]["date_of_birth"] = (
        "not-a-date"
    )

    response = await client.post("/vapi/webhook", json=update_payload, headers=SECRET_HEADER)
    assert response.status_code == 200
    assert response.json()["results"][0]["result"].startswith("INVALID: date_of_birth:")


async def test_update_patient_not_found(client: AsyncClient) -> None:
    update_payload = _load("update_patient.json")
    update_payload["message"]["toolCallList"][0]["function"]["arguments"]["patient_id"] = (
        "00000000-0000-0000-0000-000000000099"
    )

    response = await client.post("/vapi/webhook", json=update_payload, headers=SECRET_HEADER)
    assert response.status_code == 200
    assert response.json()["results"][0]["result"] == "NOT_FOUND"


async def test_update_patient_succeeds_with_correct_identity(client: AsyncClient) -> None:
    create_response = await client.post(
        "/vapi/webhook", json=_load("create_patient.json"), headers=SECRET_HEADER
    )
    patient_id = (
        create_response.json()["results"][0]["result"].split("patient_id=")[1].split(";")[0]
    )

    update_payload = _load("update_patient.json")
    update_payload["message"]["toolCallList"][0]["function"]["arguments"]["patient_id"] = patient_id

    response = await client.post("/vapi/webhook", json=update_payload, headers=SECRET_HEADER)
    assert response.status_code == 200
    assert response.json()["results"][0]["result"].startswith("UPDATED:")


# --- Resilience: DB failure, timeout, unknown tool must never 500/raise --------------------


async def test_tool_handler_db_failure_returns_save_failed_with_200(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _raise(*args: object, **kwargs: object) -> tuple[Any, bool]:
        raise RuntimeError("simulated DB failure")

    monkeypatch.setattr(PatientService, "create_patient", _raise)

    response = await client.post(
        "/vapi/webhook", json=_load("create_patient.json"), headers=SECRET_HEADER
    )
    assert response.status_code == 200
    result = response.json()["results"][0]["result"]
    assert result.startswith("SAVE_FAILED:")


async def test_tool_handler_timeout_returns_friendly_result(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _slow_handler(arguments: dict[str, Any], ctx: object) -> str:
        await asyncio.sleep(10)
        return "NO_MATCH"

    monkeypatch.setitem(tools_module.TOOL_HANDLERS, "find_patient_by_phone", _slow_handler)
    monkeypatch.setenv("VAPI_TOOL_TIMEOUT_SECONDS", "0.05")
    from app.core.config import get_settings

    get_settings.cache_clear()

    response = await client.post(
        "/vapi/webhook", json=_load("find_patient_by_phone_object_args.json"), headers=SECRET_HEADER
    )
    assert response.status_code == 200
    result = response.json()["results"][0]["result"]
    assert result.startswith("SAVE_FAILED:")

    get_settings.cache_clear()


async def test_unknown_tool_name_returns_friendly_result(client: AsyncClient) -> None:
    response = await client.post(
        "/vapi/webhook", json=_load("unknown_tool.json"), headers=SECRET_HEADER
    )
    assert response.status_code == 200
    result = response.json()["results"][0]["result"]
    assert result.startswith("SAVE_FAILED:")

"""Resilience: the app degrades to spoken errors, never silence or a crash.

Other resilience cases live next to the feature they protect:
- Vapi retrying the same tool call:
  test_vapi_webhook.py::test_create_patient_then_retry_same_call_id_is_idempotent,
  test_appointments.py::test_booking_is_idempotent_per_call
- duplicate end-of-call-report:
  test_call_logs.py::test_duplicate_end_of_call_delivery_is_idempotent
- malformed webhook payloads:
  test_call_logs.py::test_malformed_end_of_call_report_returns_200
- concurrent bookings:
  test_appointments.py::test_concurrent_booking_of_same_slot_exactly_one_wins
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from tests.integration.conftest import AppFactory

SECRET = {"X-Vapi-Secret": "test-webhook-secret"}
API_KEY = {"X-API-Key": "test-api-key"}
FIXTURES = Path(__file__).parent.parent / "fixtures" / "vapi"
# Nothing listens on port 1: connections are refused immediately.
UNREACHABLE_DB = "postgresql+asyncpg://nobody:nothing@127.0.0.1:1/nowhere"


def _tool_call(call_id: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "message": {
            "type": "tool-calls",
            "call": {"id": call_id},
            "toolCallList": [{"id": "tc-1", "function": {"name": name, "arguments": arguments}}],
        }
    }


# --- Database unreachable ------------------------------------------------------------------


async def test_app_starts_and_degrades_when_db_is_unreachable(
    custom_client: AppFactory,
) -> None:
    async with custom_client(DATABASE_URL=UNREACHABLE_DB) as client:
        # Liveness is independent of the DB; readiness reports it honestly.
        assert (await client.get("/health")).status_code == 200
        ready = await client.get("/health/ready")
        assert ready.status_code == 503
        assert ready.json()["error"]["code"] == "not_ready"

        # Every tool call still gets a speakable answer — never a 500 / silence.
        create = json.loads((FIXTURES / "create_patient.json").read_text())
        for body in (
            create,
            _tool_call("c", "find_patient_by_phone", {"phone_number": "2125550100"}),
            _tool_call("c", "get_available_slots", {}),
        ):
            response = await client.post("/vapi/webhook", json=body, headers=SECRET)
            assert response.status_code == 200
            assert response.json()["results"][0]["result"].startswith("SAVE_FAILED:")

        eoc = {"message": {"type": "end-of-call-report", "call": {"id": "c"}}}
        response = await client.post("/vapi/webhook", json=eoc, headers=SECRET)
        assert response.status_code == 200

        # REST reports it as a generic 500 envelope, with no internals leaked.
        rest = await client.get("/patients", headers=API_KEY)
        assert rest.status_code == 500
        assert rest.json()["error"]["message"] == "An unexpected error occurred."
        assert "nowhere" not in rest.text and "asyncpg" not in rest.text


async def test_validation_still_works_when_db_is_unreachable(custom_client: AppFactory) -> None:
    """validate_fields needs no DB — the agent can keep collecting fields."""
    async with custom_client(DATABASE_URL=UNREACHABLE_DB) as client:
        body = _tool_call("c", "validate_fields", {"fields": {"zip_code": "1234"}})
        result = (await client.post("/vapi/webhook", json=body, headers=SECRET)).json()
    # The session can't open, so even DB-free tools get the safe fallback — the point is
    # the caller always hears something.
    assert result["results"][0]["result"].split(":")[0] in {"INVALID", "SAVE_FAILED"}


# --- Database slow: statement timeout mid-tool-call -------------------------------------


@pytest.mark.usefixtures("clean_patients_table")
async def test_db_statement_timeout_during_tool_call_returns_save_failed(
    custom_client: AppFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.patient_service import PatientService

    async def _slow_lookup(self: PatientService, phone_number: str) -> list[Any]:
        # A real query that outlives the webhook's statement_timeout.
        await self._repository._session.execute(text("SELECT pg_sleep(2)"))
        return []

    monkeypatch.setattr(PatientService, "find_by_phone", _slow_lookup)

    async with custom_client(VAPI_WEBHOOK_DB_STATEMENT_TIMEOUT_MS="100") as client:
        body = _tool_call("c-slow", "find_patient_by_phone", {"phone_number": "2125550100"})
        response = await client.post("/vapi/webhook", json=body, headers=SECRET)

    assert response.status_code == 200
    assert response.json()["results"][0]["result"].startswith("SAVE_FAILED:")


# --- Very long transcripts ---------------------------------------------------------------


@pytest.mark.usefixtures("clean_patients_table")
async def test_very_long_transcript_is_stored_intact(client: AsyncClient) -> None:
    create = json.loads((FIXTURES / "create_patient.json").read_text())
    create["message"]["call"]["id"] = "c-long"
    saved = (await client.post("/vapi/webhook", json=create, headers=SECRET)).json()
    patient_id = saved["results"][0]["result"].split("patient_id=")[1].split(";")[0]

    transcript = ("AI: Could you repeat that?\nUser: " + "blah " * 40 + "\n") * 5000  # ~1.3 MB
    eoc = {
        "message": {
            "type": "end-of-call-report",
            "call": {"id": "c-long"},
            "artifact": {"transcript": transcript},
        }
    }
    response = await client.post("/vapi/webhook", json=eoc, headers=SECRET)
    assert response.status_code == 200

    calls = (await client.get(f"/patients/{patient_id}/calls", headers=API_KEY)).json()["data"]
    assert calls[0]["transcript"] == transcript


async def test_transcript_beyond_body_limit_is_rejected_413(custom_client: AppFactory) -> None:
    async with custom_client(MAX_REQUEST_BODY_BYTES="100000") as client:
        eoc = {
            "message": {
                "type": "end-of-call-report",
                "call": {"id": "c-huge"},
                "artifact": {"transcript": "x" * 200_000},
            }
        }
        response = await client.post("/vapi/webhook", json=eoc, headers=SECRET)
    assert response.status_code == 413


# --- Graceful shutdown -----------------------------------------------------------------------


async def test_shutdown_disposes_the_db_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.main as main_module

    disposed: list[bool] = []

    async def _spy() -> None:
        disposed.append(True)

    monkeypatch.setattr(main_module, "dispose_engine", _spy)
    application = main_module.create_app()
    async with application.router.lifespan_context(application):
        assert disposed == []
    assert disposed == [True]

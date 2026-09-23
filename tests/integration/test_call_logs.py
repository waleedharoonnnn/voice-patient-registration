"""end-of-call-report handling and call-log linkage, through the real webhook."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.usefixtures("clean_patients_table")

SECRET = {"X-Vapi-Secret": "test-webhook-secret"}
API_KEY = {"X-API-Key": "test-api-key"}
FIXTURES = Path(__file__).parent.parent / "fixtures" / "vapi"


def _end_of_call(call_id: str, **overrides: Any) -> dict[str, Any]:
    message: dict[str, Any] = {
        "type": "end-of-call-report",
        "call": {"id": call_id},
        "endedReason": "customer-ended-call",
        "startedAt": "2026-09-24T14:00:00.000Z",
        "endedAt": "2026-09-24T14:03:15.000Z",
        "artifact": {
            "transcript": "AI: Hi, this is Sarah.\nUser: Hi.",
            "recordingUrl": "https://example.com/r.wav",
        },
        "analysis": {"summary": "Caller registered as a new patient."},
    }
    message.update(overrides)
    return {"message": message}


async def _create_patient_in_call(client: AsyncClient, call_id: str) -> str:
    payload = json.loads((FIXTURES / "create_patient.json").read_text())
    payload["message"]["call"]["id"] = call_id
    response = await client.post("/vapi/webhook", json=payload, headers=SECRET)
    result = response.json()["results"][0]["result"]
    assert result.startswith("SAVED:"), result
    return result.split("patient_id=")[1].split(";")[0]


async def _calls_for(client: AsyncClient, patient_id: str) -> list[dict[str, Any]]:
    response = await client.get(f"/patients/{patient_id}/calls", headers=API_KEY)
    assert response.status_code == 200
    return response.json()["data"]


async def test_end_of_call_links_to_patient_created_in_same_call(client: AsyncClient) -> None:
    patient_id = await _create_patient_in_call(client, "call-eoc-1")

    response = await client.post("/vapi/webhook", json=_end_of_call("call-eoc-1"), headers=SECRET)
    assert response.status_code == 200

    calls = await _calls_for(client, patient_id)
    assert len(calls) == 1
    log = calls[0]
    assert log["outcome"] == "registered"
    assert log["summary"] == "Caller registered as a new patient."
    assert "Sarah" in log["transcript"]
    assert log["duration_seconds"] == 195
    assert log["ended_reason"] == "customer-ended-call"
    assert log["recording_url"] == "https://example.com/r.wav"


async def test_duplicate_end_of_call_delivery_is_idempotent(client: AsyncClient) -> None:
    patient_id = await _create_patient_in_call(client, "call-eoc-2")
    for _ in range(2):
        response = await client.post(
            "/vapi/webhook", json=_end_of_call("call-eoc-2"), headers=SECRET
        )
        assert response.status_code == 200

    calls = await _calls_for(client, patient_id)
    assert len(calls) == 1
    assert calls[0]["outcome"] == "registered"


async def test_call_with_no_patient_is_marked_abandoned(client: AsyncClient) -> None:
    response = await client.post(
        "/vapi/webhook",
        json=_end_of_call("call-eoc-3", endedReason="customer-ended-call"),
        headers=SECRET,
    )
    assert response.status_code == 200

    # No patient to look it up by — check through the dashboard's follow-up queue.
    page = await client.get(
        "/dashboard/calls?outcome=abandoned",
        auth=("test-dashboard-user", "test-dashboard-password"),
    )
    assert page.status_code == 200
    assert "No patient record" in page.text
    assert "Needs follow-up" in page.text


async def test_save_failure_is_recorded_as_failed_not_abandoned(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.patient_service import PatientService

    async def _boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("simulated DB outage")

    monkeypatch.setattr(PatientService, "create_patient", _boom)
    payload = json.loads((FIXTURES / "create_patient.json").read_text())
    payload["message"]["call"]["id"] = "call-eoc-4"
    await client.post("/vapi/webhook", json=payload, headers=SECRET)
    await client.post("/vapi/webhook", json=_end_of_call("call-eoc-4"), headers=SECRET)

    page = await client.get(
        "/dashboard/calls?outcome=failed",
        auth=("test-dashboard-user", "test-dashboard-password"),
    )
    assert "Save failed" in page.text
    assert "Caller registered as a new patient." in page.text  # the summary is kept


@pytest.mark.parametrize(
    "body",
    [
        {"message": {"type": "end-of-call-report"}},  # no call at all
        {"message": {"type": "end-of-call-report", "call": {"id": "x"}, "startedAt": "garbage"}},
        {"message": {"type": "end-of-call-report", "call": {"id": "y"}, "artifact": "oops"}},
        {"not": "a vapi payload"},
    ],
)
async def test_malformed_end_of_call_report_returns_200(
    client: AsyncClient, body: dict[str, Any]
) -> None:
    response = await client.post("/vapi/webhook", json=body, headers=SECRET)
    assert response.status_code == 200

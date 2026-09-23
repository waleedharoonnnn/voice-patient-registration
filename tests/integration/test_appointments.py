"""Mock scheduling: availability rules, tamper protection, and the double-booking guard."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.repositories.appointment_repository import AppointmentRepository
from app.repositories.provider_repository import ProviderRepository
from app.services.appointment_service import AppointmentService

pytestmark = pytest.mark.usefixtures("clean_patients_table")

SECRET = {"X-Vapi-Secret": "test-webhook-secret"}
API_KEY = {"X-API-Key": "test-api-key"}
FIXTURES = Path(__file__).parent.parent / "fixtures" / "vapi"
ET = ZoneInfo("America/New_York")


def _tool_call(call_id: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "message": {
            "type": "tool-calls",
            "call": {"id": call_id},
            "toolCallList": [{"id": "tc-1", "function": {"name": name, "arguments": arguments}}],
        }
    }


async def _result(client: AsyncClient, body: dict[str, Any]) -> str:
    response = await client.post("/vapi/webhook", json=body, headers=SECRET)
    assert response.status_code == 200
    result: str = response.json()["results"][0]["result"]
    return result


async def _new_patient(client: AsyncClient, call_id: str) -> str:
    payload = json.loads((FIXTURES / "create_patient.json").read_text())
    payload["message"]["call"]["id"] = call_id
    result = await _result(client, payload)
    return result.split("patient_id=")[1].split(";")[0]


def _first_slot_id(slots_result: str) -> str:
    assert slots_result.startswith("SLOTS:"), slots_result
    return slots_result.split("1) ")[1].split(" | ")[0]


async def _service(test_database_url: str) -> tuple[AppointmentService, Any]:
    engine = create_async_engine(test_database_url)
    session = AsyncSession(engine, expire_on_commit=False)
    return AppointmentService(AppointmentRepository(session), ProviderRepository(session)), (
        engine,
        session,
    )


# --- Availability -----------------------------------------------------------------------


async def test_slots_are_weekday_business_hours_from_tomorrow(test_database_url: str) -> None:
    service, (engine, session) = await _service(test_database_url)
    try:
        slots = await service.get_available_slots(limit=10_000)
    finally:
        await session.close()
        await engine.dispose()

    tomorrow = (datetime.now(ET) + timedelta(days=1)).date()
    assert slots, "expected availability"
    for slot in slots:
        local = slot.start_time.astimezone(ET)
        assert local.weekday() < 5, local
        assert 9 <= local.hour < 17, local
        assert local.minute in (0, 30), local
        assert local.date() >= tomorrow, local
        assert local.date() < tomorrow + timedelta(days=14), local
    assert slots == sorted(slots, key=lambda s: s.start_time)


async def test_time_of_day_filter(test_database_url: str) -> None:
    service, (engine, session) = await _service(test_database_url)
    try:
        mornings = await service.get_available_slots(time_of_day="morning", limit=50)
        afternoons = await service.get_available_slots(time_of_day="afternoon", limit=50)
    finally:
        await session.close()
        await engine.dispose()
    assert all(s.start_time.astimezone(ET).hour < 12 for s in mornings)
    assert all(s.start_time.astimezone(ET).hour >= 12 for s in afternoons)


async def test_booked_slot_is_excluded(client: AsyncClient, test_database_url: str) -> None:
    patient_id = await _new_patient(client, "call-appt-1")
    slot_id = _first_slot_id(
        await _result(client, _tool_call("call-appt-1", "get_available_slots", {}))
    )
    booked = await _result(
        client,
        _tool_call(
            "call-appt-1", "book_appointment", {"patient_id": patient_id, "slot_id": slot_id}
        ),
    )
    assert booked.startswith("BOOKED:"), booked

    service, (engine, session) = await _service(test_database_url)
    try:
        remaining = await service.get_available_slots(limit=10_000)
    finally:
        await session.close()
        await engine.dispose()
    assert slot_id not in {s.slot_id for s in remaining}


async def test_weekend_preferred_date_returns_no_slots(client: AsyncClient) -> None:
    day = datetime.now(ET).date() + timedelta(days=1)
    while day.weekday() != 5:  # next Saturday
        day += timedelta(days=1)
    result = await _result(
        client,
        _tool_call(
            "call-appt-2", "get_available_slots", {"preferred_date": day.strftime("%m/%d/%Y")}
        ),
    )
    assert result == "NO_SLOTS"


async def test_slots_result_is_speakable(client: AsyncClient) -> None:
    result = await _result(client, _tool_call("call-appt-3", "get_available_slots", {}))
    assert result.startswith("SLOTS: 1) ")
    assert " Eastern with Dr. " in result
    assert result.count(") ") <= 3


# --- Booking ---------------------------------------------------------------------------


async def test_tampered_slot_id_is_rejected(client: AsyncClient) -> None:
    patient_id = await _new_patient(client, "call-appt-4")
    slot_id = _first_slot_id(
        await _result(client, _tool_call("call-appt-4", "get_available_slots", {}))
    )
    tampered = slot_id[:-3] + ("AAA" if not slot_id.endswith("AAA") else "BBB")

    result = await _result(
        client,
        _tool_call(
            "call-appt-4", "book_appointment", {"patient_id": patient_id, "slot_id": tampered}
        ),
    )
    assert result.startswith("INVALID: slot_id"), result


async def test_booking_is_idempotent_per_call(client: AsyncClient) -> None:
    patient_id = await _new_patient(client, "call-appt-5")
    slot_id = _first_slot_id(
        await _result(client, _tool_call("call-appt-5", "get_available_slots", {}))
    )
    args = {"patient_id": patient_id, "slot_id": slot_id, "reason": "annual checkup"}

    first = await _result(client, _tool_call("call-appt-5", "book_appointment", args))
    second = await _result(client, _tool_call("call-appt-5", "book_appointment", args))
    assert first.startswith("BOOKED:") and first == second

    listing = await client.get(f"/patients/{patient_id}/appointments", headers=API_KEY)
    rows = listing.json()["data"]
    assert len(rows) == 1
    assert rows[0]["reason"] == "annual checkup"
    assert rows[0]["status"] == "booked"


async def test_concurrent_booking_of_same_slot_exactly_one_wins(client: AsyncClient) -> None:
    """Two calls race for the same slot: the DB's partial unique index decides."""
    patient_a = await _new_patient(client, "call-race-a")
    patient_b = await _new_patient(client, "call-race-b")
    slot_id = _first_slot_id(
        await _result(client, _tool_call("call-race-a", "get_available_slots", {}))
    )

    results = await asyncio.gather(
        _result(
            client,
            _tool_call(
                "call-race-a", "book_appointment", {"patient_id": patient_a, "slot_id": slot_id}
            ),
        ),
        _result(
            client,
            _tool_call(
                "call-race-b", "book_appointment", {"patient_id": patient_b, "slot_id": slot_id}
            ),
        ),
    )

    assert sorted(r.split(":")[0] for r in results) == ["BOOKED", "SLOT_TAKEN"], results


async def test_book_with_unknown_patient_never_raises(client: AsyncClient) -> None:
    slot_id = _first_slot_id(
        await _result(client, _tool_call("call-appt-6", "get_available_slots", {}))
    )
    result = await _result(
        client,
        _tool_call(
            "call-appt-6",
            "book_appointment",
            {"patient_id": "00000000-0000-0000-0000-000000000999", "slot_id": slot_id},
        ),
    )
    assert result.startswith("BOOK_FAILED:"), result


# --- REST -------------------------------------------------------------------------------


async def test_providers_endpoint(client: AsyncClient) -> None:
    response = await client.get("/providers", headers=API_KEY)
    assert response.status_code == 200
    body = response.json()
    assert body["error"] is None
    assert len(body["data"]) == 3
    assert all(p["active"] for p in body["data"])


async def test_providers_requires_api_key(client: AsyncClient) -> None:
    assert (await client.get("/providers")).status_code == 401


@pytest.mark.parametrize("sub", ["appointments", "calls"])
async def test_patient_subresources_404_and_401(client: AsyncClient, sub: str) -> None:
    missing = "00000000-0000-0000-0000-000000000999"
    response = await client.get(f"/patients/{missing}/{sub}", headers=API_KEY)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert (await client.get(f"/patients/not-a-uuid/{sub}", headers=API_KEY)).status_code == 404
    assert (await client.get(f"/patients/{missing}/{sub}")).status_code == 401


async def test_patient_subresources_empty_lists(client: AsyncClient) -> None:
    patient_id = await _new_patient(client, "call-appt-7")
    appts = await client.get(f"/patients/{patient_id}/appointments", headers=API_KEY)
    assert appts.status_code == 200 and appts.json() == {"data": [], "error": None}

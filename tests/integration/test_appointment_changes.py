"""cancel_appointment / reschedule_appointment over the real webhook + Postgres.

Identity is phone (caller ID, or a stated number) + DOB, and only the verified caller's
own upcoming appointments can be touched.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.usefixtures("clean_patients_table")

SECRET = {"X-Vapi-Secret": "test-webhook-secret"}
API_KEY = {"X-API-Key": "test-api-key"}
CALLER = "+12125550142"
DOB = "04/12/1979"


def _tool_call(
    name: str,
    arguments: dict[str, Any] | None = None,
    *,
    caller: str | None = CALLER,
    call_id: str = "call-change-1",
) -> dict[str, Any]:
    """Recorded-shape Vapi tool-calls message, caller ID in message.customer."""
    message: dict[str, Any] = {
        "type": "tool-calls",
        "call": {"id": call_id},
        "toolCallList": [{"id": "tc-1", "function": {"name": name, "arguments": arguments or {}}}],
    }
    if caller is not None:
        message["customer"] = {"number": caller}
    return {"message": message}


async def _result(client: AsyncClient, body: dict[str, Any]) -> str:
    response = await client.post("/vapi/webhook", json=body, headers=SECRET)
    assert response.status_code == 200
    result: str = response.json()["results"][0]["result"]
    return result


async def _create(client: AsyncClient, **overrides: str) -> str:
    payload = {
        "first_name": "Rosa",
        "last_name": "Callerton",
        "date_of_birth": DOB,
        "sex": "Female",
        "phone_number": "(212) 555-0142",
        "address_line_1": "5 Test Ave",
        "city": "Testville",
        "state": "NY",
        "zip_code": "10001",
        **overrides,
    }
    response = await client.post("/patients", json=payload, headers=API_KEY)
    assert response.status_code == 201
    patient_id: str = response.json()["data"]["patient_id"]
    return patient_id


async def _slot_ids(client: AsyncClient) -> list[str]:
    slots = await _result(client, _tool_call("get_available_slots", {"time_of_day": "any"}))
    assert slots.startswith("SLOTS:"), slots
    return [part.split(") ", 1)[1].split(" | ")[0] for part in slots.split("; ")]


async def _book(client: AsyncClient, patient_id: str, slot_id: str, call_id: str) -> str:
    booked = await _result(
        client,
        _tool_call(
            "book_appointment", {"patient_id": patient_id, "slot_id": slot_id}, call_id=call_id
        ),
    )
    assert booked.startswith("BOOKED:"), booked
    return booked.split("appointment_id=")[1].split(";")[0]


async def _appointments(client: AsyncClient, patient_id: str) -> list[dict[str, Any]]:
    response = await client.get(f"/patients/{patient_id}/appointments", headers=API_KEY)
    rows: list[dict[str, Any]] = response.json()["data"]
    return rows


# --- cancel_appointment ---------------------------------------------------------------------


async def test_cancel_own_appointment(client: AsyncClient) -> None:
    patient_id = await _create(client)
    appointment_id = await _book(client, patient_id, (await _slot_ids(client))[0], "call-b1")

    result = await _result(
        client,
        _tool_call("cancel_appointment", {"appointment_id": appointment_id, "date_of_birth": DOB}),
    )

    assert result.startswith(f"CANCELLED: appointment_id={appointment_id}; time=")
    assert " Eastern with Doctor " in result
    assert (await _appointments(client, patient_id))[0]["status"] == "cancelled"
    verified = await _result(client, _tool_call("verify_caller", {"date_of_birth": DOB}))
    assert verified.endswith("upcoming_appointments=none")


async def test_cancel_retry_is_idempotent(client: AsyncClient) -> None:
    patient_id = await _create(client)
    appointment_id = await _book(client, patient_id, (await _slot_ids(client))[0], "call-b2")
    args = {"appointment_id": appointment_id, "date_of_birth": DOB}

    first = await _result(client, _tool_call("cancel_appointment", args))
    second = await _result(client, _tool_call("cancel_appointment", args))

    assert first.startswith("CANCELLED:") and first == second


async def test_cancel_with_wrong_dob_is_mismatch_and_keeps_booking(client: AsyncClient) -> None:
    patient_id = await _create(client)
    appointment_id = await _book(client, patient_id, (await _slot_ids(client))[0], "call-b3")

    result = await _result(
        client,
        _tool_call(
            "cancel_appointment", {"appointment_id": appointment_id, "date_of_birth": "01/01/1980"}
        ),
    )

    assert result == "IDENTITY_MISMATCH"
    assert (await _appointments(client, patient_id))[0]["status"] == "booked"


async def test_cannot_cancel_someone_elses_appointment(client: AsyncClient) -> None:
    await _create(client)
    other_id = await _create(client, first_name="Otto", phone_number="3125550199")
    appointment_id = await _book(client, other_id, (await _slot_ids(client))[0], "call-b4")

    result = await _result(
        client,
        _tool_call("cancel_appointment", {"appointment_id": appointment_id, "date_of_birth": DOB}),
    )

    assert result == "NOT_FOUND"
    assert (await _appointments(client, other_id))[0]["status"] == "booked"


async def test_cancel_malformed_appointment_id_is_not_found(client: AsyncClient) -> None:
    await _create(client)
    result = await _result(
        client,
        _tool_call("cancel_appointment", {"appointment_id": "not-a-uuid", "date_of_birth": DOB}),
    )
    assert result == "NOT_FOUND"


async def test_cancel_without_caller_id_needs_a_stated_phone(client: AsyncClient) -> None:
    patient_id = await _create(client)
    appointment_id = await _book(client, patient_id, (await _slot_ids(client))[0], "call-b5")
    args: dict[str, Any] = {"appointment_id": appointment_id, "date_of_birth": DOB}

    assert await _result(client, _tool_call("cancel_appointment", args, caller=None)) == (
        "NO_CALLER_ID"
    )

    args["phone_number"] = "212-555-0142"
    result = await _result(client, _tool_call("cancel_appointment", args, caller=None))
    assert result.startswith("CANCELLED:")


async def test_verify_with_stated_phone_lists_appointment_ids(client: AsyncClient) -> None:
    patient_id = await _create(client)
    appointment_id = await _book(client, patient_id, (await _slot_ids(client))[0], "call-b6")

    result = await _result(
        client,
        _tool_call(
            "verify_caller", {"date_of_birth": DOB, "phone_number": "2125550142"}, caller=None
        ),
    )

    assert result.startswith(f"VERIFIED: patient_id={patient_id};")
    assert f"appointment_id={appointment_id}, " in result


# --- reschedule_appointment -----------------------------------------------------------------


async def test_reschedule_moves_appointment_in_place(client: AsyncClient) -> None:
    patient_id = await _create(client)
    first_slot, second_slot = (await _slot_ids(client))[:2]
    appointment_id = await _book(client, patient_id, first_slot, "call-r1")
    before = (await _appointments(client, patient_id))[0]

    result = await _result(
        client,
        _tool_call(
            "reschedule_appointment",
            {"appointment_id": appointment_id, "slot_id": second_slot, "date_of_birth": DOB},
        ),
    )

    assert result.startswith(f"RESCHEDULED: appointment_id={appointment_id}; time=")
    assert " Eastern with Doctor " in result
    rows = await _appointments(client, patient_id)
    assert len(rows) == 1
    assert rows[0]["status"] == "booked"
    assert (rows[0]["start_time"], rows[0]["provider_id"]) != (
        before["start_time"],
        before["provider_id"],
    )
    # The old time is free again.
    assert first_slot in await _slot_ids(client)


async def test_reschedule_onto_a_taken_slot_is_slot_taken(client: AsyncClient) -> None:
    patient_id = await _create(client)
    other_id = await _create(client, first_name="Otto", phone_number="3125550199")
    first_slot, second_slot = (await _slot_ids(client))[:2]
    appointment_id = await _book(client, patient_id, first_slot, "call-r2a")
    await _book(client, other_id, second_slot, "call-r2b")

    result = await _result(
        client,
        _tool_call(
            "reschedule_appointment",
            {"appointment_id": appointment_id, "slot_id": second_slot, "date_of_birth": DOB},
        ),
    )

    assert result == "SLOT_TAKEN"
    assert (await _appointments(client, patient_id))[0]["status"] == "booked"


async def test_reschedule_rejects_tampered_slot(client: AsyncClient) -> None:
    patient_id = await _create(client)
    slot_id = (await _slot_ids(client))[0]
    appointment_id = await _book(client, patient_id, slot_id, "call-r3")
    tampered = slot_id[:-3] + ("AAA" if not slot_id.endswith("AAA") else "BBB")

    result = await _result(
        client,
        _tool_call(
            "reschedule_appointment",
            {"appointment_id": appointment_id, "slot_id": tampered, "date_of_birth": DOB},
        ),
    )

    assert result.startswith("INVALID: slot_id"), result


async def test_cannot_reschedule_a_cancelled_appointment(client: AsyncClient) -> None:
    patient_id = await _create(client)
    first_slot, second_slot = (await _slot_ids(client))[:2]
    appointment_id = await _book(client, patient_id, first_slot, "call-r4")
    await _result(
        client,
        _tool_call("cancel_appointment", {"appointment_id": appointment_id, "date_of_birth": DOB}),
    )

    result = await _result(
        client,
        _tool_call(
            "reschedule_appointment",
            {"appointment_id": appointment_id, "slot_id": second_slot, "date_of_birth": DOB},
        ),
    )

    assert result == "NOT_FOUND"


async def test_cannot_reschedule_someone_elses_appointment(client: AsyncClient) -> None:
    await _create(client)
    other_id = await _create(client, first_name="Otto", phone_number="3125550199")
    first_slot, second_slot = (await _slot_ids(client))[:2]
    appointment_id = await _book(client, other_id, first_slot, "call-r5")

    result = await _result(
        client,
        _tool_call(
            "reschedule_appointment",
            {"appointment_id": appointment_id, "slot_id": second_slot, "date_of_birth": DOB},
        ),
    )

    assert result == "NOT_FOUND"


async def test_cancel_then_rebook_in_same_call_creates_a_new_booking(client: AsyncClient) -> None:
    """A cancelled booking must not satisfy book_appointment's per-call idempotency."""
    patient_id = await _create(client)
    first_slot, second_slot = (await _slot_ids(client))[:2]
    appointment_id = await _book(client, patient_id, first_slot, "call-r6")
    await _result(
        client,
        _tool_call("cancel_appointment", {"appointment_id": appointment_id, "date_of_birth": DOB}),
    )

    new_id = await _book(client, patient_id, second_slot, "call-r6")

    assert new_id != appointment_id
    statuses = sorted(row["status"] for row in await _appointments(client, patient_id))
    assert statuses == ["booked", "cancelled"]

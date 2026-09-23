"""Unit tests for opaque slot IDs: round trip, tamper rejection, past-slot rejection."""

from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.services.slots import decode_slot_id, encode_slot_id

PROVIDER = uuid.UUID("10000000-0000-0000-0000-000000000001")


def _future() -> datetime:
    return (datetime.now(UTC) + timedelta(days=3)).replace(microsecond=0)


def test_round_trip() -> None:
    start = _future()
    provider_id, decoded = decode_slot_id(encode_slot_id(PROVIDER, start))
    assert provider_id == PROVIDER
    assert decoded == start


def test_tampered_start_time_is_rejected() -> None:
    slot_id = encode_slot_id(PROVIDER, _future())
    raw = base64.urlsafe_b64decode(slot_id + "=" * (-len(slot_id) % 4)).decode()
    provider, start, sig = raw.rsplit("|", 2)
    moved = (datetime.fromisoformat(start) + timedelta(hours=1)).isoformat()
    forged = base64.urlsafe_b64encode(f"{provider}|{moved}|{sig}".encode()).decode().rstrip("=")

    with pytest.raises(ValueError, match="signature"):
        decode_slot_id(forged)


def test_garbage_is_rejected() -> None:
    with pytest.raises(ValueError):
        decode_slot_id("not-a-slot")


def test_past_slot_is_rejected() -> None:
    past = datetime.now(UTC) - timedelta(hours=1)
    with pytest.raises(ValueError, match="no longer available"):
        decode_slot_id(encode_slot_id(PROVIDER, past))

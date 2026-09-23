"""Opaque, tamper-evident slot IDs for mock appointment availability.

A slot is never stored — availability is computed on the fly (see
`app/services/appointment_service.py`). `slot_id` encodes `(provider_id, start_time)`
signed with HMAC-SHA256, so `book_appointment` can validate a slot came from us and
hasn't been altered, without a lookup table. See
docs/adr/0008-mock-appointment-scheduling.md.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import uuid
from datetime import UTC, datetime

from app.core.config import get_settings

_SIGNATURE_LENGTH = 16


def _signing_key() -> bytes:
    # Reuses the app's own API key as an HMAC key rather than adding a dedicated secret
    # setting — it's already a required, secret, per-deployment value.
    return get_settings().API_KEY.get_secret_value().encode()


def encode_slot_id(provider_id: uuid.UUID, start_time: datetime) -> str:
    payload = f"{provider_id}|{start_time.astimezone(UTC).isoformat()}"
    signature = hmac.new(_signing_key(), payload.encode(), hashlib.sha256).hexdigest()[
        :_SIGNATURE_LENGTH
    ]
    raw = f"{payload}|{signature}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_slot_id(slot_id: str, *, now: datetime | None = None) -> tuple[uuid.UUID, datetime]:
    """Raises ValueError if the slot is malformed, tampered with, or already in the past."""
    try:
        padded = slot_id + "=" * (-len(slot_id) % 4)
        raw = base64.urlsafe_b64decode(padded.encode()).decode()
        provider_id_str, start_iso, signature = raw.rsplit("|", 2)
        payload = f"{provider_id_str}|{start_iso}"
        expected_signature = hmac.new(_signing_key(), payload.encode(), hashlib.sha256).hexdigest()[
            :_SIGNATURE_LENGTH
        ]
        if not hmac.compare_digest(signature, expected_signature):
            raise ValueError("Slot signature does not match.")
        provider_id = uuid.UUID(provider_id_str)
        start_time = datetime.fromisoformat(start_iso)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("That slot could not be read.") from exc

    current = now if now is not None else datetime.now(UTC)
    if start_time < current:
        raise ValueError("That slot is no longer available.")

    return provider_id, start_time

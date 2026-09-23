"""Call log upsert logic.

Called from two places, both idempotent by `vapi_call_id` (Vapi may retry either):
- tool handlers, right after create_patient/update_patient succeeds or fails
- the webhook's end-of-call-report handling, which adds transcript/summary/timing and
  fills in an `outcome` for calls that never reached a save at all
"""

from __future__ import annotations

import uuid
from datetime import datetime

from app.models.call_log import CallLog
from app.repositories.call_log_repository import CallLogRepository


class CallLogService:
    def __init__(self, repository: CallLogRepository) -> None:
        self._repository = repository

    async def record_progress(
        self, vapi_call_id: str, *, patient_id: uuid.UUID | None, outcome: str
    ) -> CallLog:
        """Called right after a create_patient/update_patient tool call succeeds or fails."""
        existing = await self._repository.get_by_vapi_call_id(vapi_call_id)
        fields: dict[str, object] = {"outcome": outcome}
        if patient_id is not None:
            fields["patient_id"] = patient_id

        if existing is None:
            return await self._repository.create({"vapi_call_id": vapi_call_id, **fields})
        return await self._repository.update(existing, fields)

    async def record_end_of_call_report(
        self,
        vapi_call_id: str,
        *,
        ended_reason: str | None,
        started_at: datetime | None,
        ended_at: datetime | None,
        summary: str | None,
        transcript: str | None,
        recording_url: str | None,
    ) -> CallLog:
        duration_seconds = None
        if started_at is not None and ended_at is not None:
            duration_seconds = max(0, int((ended_at - started_at).total_seconds()))

        fields: dict[str, object] = {
            "ended_reason": ended_reason,
            "started_at": started_at,
            "ended_at": ended_at,
            "duration_seconds": duration_seconds,
            "summary": summary,
            "transcript": transcript,
            "recording_url": recording_url,
        }

        existing = await self._repository.get_by_vapi_call_id(vapi_call_id)
        if existing is None:
            # The call never triggered a single tool-call outcome (e.g. hung up before
            # any save attempt) — this is the first and only row for it.
            fields["vapi_call_id"] = vapi_call_id
            fields["outcome"] = "abandoned"
            return await self._repository.create(fields)

        # Never downgrade a real save outcome (registered/updated/failed) back to
        # "abandoned" — only fill it in when no tool call ever set one.
        if existing.outcome == "in_progress":
            fields["outcome"] = "abandoned"
        return await self._repository.update(existing, fields)

    async def list_for_patient(self, patient_id: uuid.UUID) -> list[CallLog]:
        return await self._repository.list_for_patient(patient_id)

    async def list_recent(
        self, *, outcome: str | None = None, limit: int = 50, offset: int = 0
    ) -> tuple[list[CallLog], int]:
        return await self._repository.list_recent(outcome=outcome, limit=limit, offset=offset)

    async def count_since(self, since: datetime) -> int:
        return await self._repository.count_since(since)

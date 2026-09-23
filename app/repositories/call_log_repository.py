"""DB access for call logs. No HTTP, no business rules."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.call_log import CallLog


class CallLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_vapi_call_id(self, vapi_call_id: str) -> CallLog | None:
        stmt = select(CallLog).where(CallLog.vapi_call_id == vapi_call_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_patient(self, patient_id: uuid.UUID) -> list[CallLog]:
        stmt = (
            select(CallLog)
            .where(CallLog.patient_id == patient_id)
            .order_by(CallLog.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_recent(
        self, *, outcome: str | None = None, limit: int = 50, offset: int = 0
    ) -> tuple[list[CallLog], int]:
        conditions = []
        if outcome is not None:
            conditions.append(CallLog.outcome == outcome)

        total = (
            await self._session.execute(
                select(func.count()).select_from(CallLog).where(*conditions)
            )
        ).scalar_one()

        stmt = (
            select(CallLog)
            .where(*conditions)
            .order_by(CallLog.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all()), total

    async def count_since(self, since: datetime) -> int:
        stmt = select(func.count()).select_from(CallLog).where(CallLog.created_at >= since)
        return (await self._session.execute(stmt)).scalar_one()

    async def create(self, fields: dict[str, object]) -> CallLog:
        call_log = CallLog(**fields)
        async with self._session.begin_nested():
            self._session.add(call_log)
            await self._session.flush()
        await self._session.refresh(call_log)
        return call_log

    async def update(self, call_log: CallLog, fields: dict[str, object]) -> CallLog:
        for key, value in fields.items():
            setattr(call_log, key, value)
        await self._session.flush()
        await self._session.refresh(call_log)
        return call_log

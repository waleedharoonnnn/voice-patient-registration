"""DB access for providers. No HTTP, no business rules."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.provider import Provider


class ProviderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_active(self) -> list[Provider]:
        stmt = select(Provider).where(Provider.active.is_(True)).order_by(Provider.full_name)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id(self, provider_id: uuid.UUID) -> Provider | None:
        stmt = select(Provider).where(Provider.provider_id == provider_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

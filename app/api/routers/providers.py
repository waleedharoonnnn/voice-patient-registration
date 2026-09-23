"""`/providers` — read-only list of active clinicians (mock scheduling reference data)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_appointment_service, require_api_key
from app.schemas.common import Envelope
from app.schemas.scheduling import ProviderOut
from app.services.appointment_service import AppointmentService

router = APIRouter(prefix="/providers", tags=["providers"], dependencies=[Depends(require_api_key)])


@router.get("", summary="List active providers")
async def list_providers(
    service: Annotated[AppointmentService, Depends(get_appointment_service)],
) -> Envelope[list[ProviderOut]]:
    providers = await service.list_providers()
    return Envelope(data=[ProviderOut.model_validate(p) for p in providers])

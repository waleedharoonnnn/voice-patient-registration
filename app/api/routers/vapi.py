"""POST /vapi/webhook — Vapi server messages.

Thin: auth, payload parsing, timeout/error wrapping, and dispatch — tool calls to
app/voice/tools.py handlers, end-of-call-report to the call log service. No business
logic here, and never a non-200 response to an authenticated Vapi request.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import UnauthorizedError
from app.core.logging import call_id_var
from app.db.session import webhook_session
from app.repositories.appointment_repository import AppointmentRepository
from app.repositories.call_log_repository import CallLogRepository
from app.repositories.patient_repository import PatientRepository
from app.repositories.provider_repository import ProviderRepository
from app.services.appointment_service import AppointmentService
from app.services.call_log_service import CallLogService
from app.services.patient_service import PatientService
from app.voice.schemas import VapiMessage, VapiToolCall, VapiWebhookPayload
from app.voice.tools import SAVE_FAILED, TOOL_HANDLERS, ToolContext

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/vapi", tags=["vapi"])


def require_vapi_secret(
    x_vapi_secret: Annotated[str | None, Header(alias="X-Vapi-Secret")] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """Accept either `X-Vapi-Secret: <secret>` or `Authorization: Bearer <secret>`."""
    expected = get_settings().VAPI_WEBHOOK_SECRET.get_secret_value()

    candidate = x_vapi_secret
    if candidate is None and authorization is not None:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() == "bearer":
            candidate = token

    if candidate is None or not secrets.compare_digest(candidate, expected):
        raise UnauthorizedError("Missing or invalid Vapi webhook secret.")


def _build_context(db: AsyncSession, call_id: str) -> ToolContext:
    return ToolContext(
        call_id=call_id,
        patient_service=PatientService(PatientRepository(db)),
        call_log_service=CallLogService(CallLogRepository(db)),
        appointment_service=AppointmentService(AppointmentRepository(db), ProviderRepository(db)),
    )


async def _dispatch_tool_call(tool_call: VapiToolCall, ctx: ToolContext) -> dict[str, str]:
    handler = TOOL_HANDLERS.get(tool_call.function.name)
    settings = get_settings()
    start = time.perf_counter()

    if handler is None:
        logger.warning(
            "unknown vapi tool requested",
            extra={"tool_name": tool_call.function.name, "call_id": ctx.call_id},
        )
        result = f"{SAVE_FAILED}: I don't know how to do that yet."
        outcome = "unknown_tool"
    else:
        try:
            result = await asyncio.wait_for(
                handler(tool_call.function.arguments, ctx),
                timeout=settings.VAPI_TOOL_TIMEOUT_SECONDS,
            )
            outcome = "ok"
        except TimeoutError:
            outcome = "timeout"
            result = f"{SAVE_FAILED}: That's taking longer than expected. Let's try again."
        except Exception:
            outcome = "error"
            logger.exception(
                "vapi tool handler raised",
                extra={"tool_name": tool_call.function.name, "call_id": ctx.call_id},
            )
            result = f"{SAVE_FAILED}: I'm having trouble saving right now."

    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    logger.info(
        "vapi tool call handled",
        extra={
            "tool_name": tool_call.function.name,
            "call_id": ctx.call_id,
            "outcome": outcome,
            "duration_ms": duration_ms,
        },
    )
    return {"toolCallId": tool_call.id, "result": result}


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


async def _handle_end_of_call_report(message: VapiMessage, call_id: str) -> None:
    """Never raises: a failure here is logged with the call id, and Vapi still gets 200."""
    try:
        async with webhook_session() as db:
            await _build_context(db, call_id).call_log_service.record_end_of_call_report(
                call_id,
                ended_reason=message.endedReason,
                started_at=_parse_iso(message.startedAt),
                ended_at=_parse_iso(message.endedAt),
                summary=message.analysis.summary if message.analysis else None,
                transcript=message.artifact.transcript if message.artifact else None,
                recording_url=message.artifact.recordingUrl if message.artifact else None,
            )
    except Exception:
        logger.exception("end-of-call-report handling failed", extra={"call_id": call_id})


@router.post("/webhook", dependencies=[Depends(require_vapi_secret)])
async def vapi_webhook(raw_body: dict[str, Any]) -> dict[str, Any]:
    try:
        payload = VapiWebhookPayload.model_validate(raw_body)
    except ValidationError:
        logger.warning("unrecognized vapi webhook payload shape")
        return {}

    message = payload.message
    call_id = message.call.id if message.call else "unknown"
    token = call_id_var.set(call_id)
    try:
        if message.type == "tool-calls":
            return await _handle_tool_calls(message, call_id)
        if message.type == "end-of-call-report" and message.call is not None:
            await _handle_end_of_call_report(message, call_id)
            return {}
        logger.info(
            "vapi message received", extra={"message_type": message.type, "call_id": call_id}
        )
        return {}
    finally:
        call_id_var.reset(token)


async def _handle_tool_calls(message: VapiMessage, call_id: str) -> dict[str, Any]:
    """Dispatch every tool call; if the DB itself is unavailable, answer each one with a
    speakable SAVE_FAILED instead of letting the request fail."""
    try:
        async with webhook_session() as db:
            ctx = _build_context(db, call_id)
            results = [await _dispatch_tool_call(tc, ctx) for tc in message.toolCallList]
    except Exception:
        # Reached only when the session can't open or commit (DB down, timeout at commit).
        # Individual handlers already turn their own errors into results.
        logger.exception("vapi webhook database unavailable", extra={"call_id": call_id})
        results = [
            {"toolCallId": tc.id, "result": f"{SAVE_FAILED}: I'm having trouble saving right now."}
            for tc in message.toolCallList
        ]
    return {"results": results}

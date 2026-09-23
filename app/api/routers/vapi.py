"""POST /vapi/webhook — Vapi server messages, dispatching tool calls.

Thin: auth, payload parsing, timeout/error wrapping, and dispatch to app/voice/tools.py
handlers. No business logic here.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import UnauthorizedError
from app.core.logging import call_id_var
from app.db.session import get_webhook_db
from app.repositories.patient_repository import PatientRepository
from app.services.patient_service import PatientService
from app.voice.schemas import VapiToolCall, VapiWebhookPayload
from app.voice.tools import SAVE_FAILED, TOOL_HANDLERS

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


async def _dispatch_tool_call(
    tool_call: VapiToolCall, *, call_id: str, service: PatientService
) -> dict[str, str]:
    handler = TOOL_HANDLERS.get(tool_call.function.name)
    settings = get_settings()
    start = time.perf_counter()

    if handler is None:
        logger.warning(
            "unknown vapi tool requested",
            extra={"tool_name": tool_call.function.name, "call_id": call_id},
        )
        result = f"{SAVE_FAILED}: I don't know how to do that yet."
        outcome = "unknown_tool"
    else:
        try:
            result = await asyncio.wait_for(
                handler(tool_call.function.arguments, call_id=call_id, service=service),
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
                extra={"tool_name": tool_call.function.name, "call_id": call_id},
            )
            result = f"{SAVE_FAILED}: I'm having trouble saving right now."

    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    logger.info(
        "vapi tool call handled",
        extra={
            "tool_name": tool_call.function.name,
            "call_id": call_id,
            "outcome": outcome,
            "duration_ms": duration_ms,
        },
    )
    return {"toolCallId": tool_call.id, "result": result}


@router.post("/webhook", dependencies=[Depends(require_vapi_secret)])
async def vapi_webhook(
    raw_body: dict[str, Any],
    db: Annotated[AsyncSession, Depends(get_webhook_db)],
) -> dict[str, Any]:
    try:
        payload = VapiWebhookPayload.model_validate(raw_body)
    except ValidationError:
        logger.warning("unrecognized vapi webhook payload shape")
        return {}

    message = payload.message
    call_id = message.call.id if message.call else "unknown"
    token = call_id_var.set(call_id)
    try:
        if message.type != "tool-calls":
            # end-of-call-report is handled in a later batch; everything else just logs.
            logger.info(
                "vapi message received", extra={"message_type": message.type, "call_id": call_id}
            )
            return {}

        service = PatientService(PatientRepository(db))
        results = [
            await _dispatch_tool_call(tool_call, call_id=call_id, service=service)
            for tool_call in message.toolCallList
        ]
        return {"results": results}
    finally:
        call_id_var.reset(token)

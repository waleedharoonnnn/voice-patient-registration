"""Pydantic models for Vapi server-message webhook payloads.

Tolerant of extra fields (`extra="ignore"`): Vapi's payloads carry many fields we don't
use, and a new one appearing must never break the webhook.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class VapiCustomer(BaseModel):
    """The caller. `number` is the caller ID (E.164) on phone calls; absent on web calls."""

    model_config = ConfigDict(extra="ignore")

    number: str | None = None


class VapiCall(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    customer: VapiCustomer | None = None


class VapiToolFunction(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)

    @field_validator("arguments", mode="before")
    @classmethod
    def _parse_arguments(cls, v: object) -> object:
        """Vapi sends arguments as a JSON object OR a JSON-encoded string — accept both."""
        if isinstance(v, str):
            if not v.strip():
                return {}
            try:
                parsed = json.loads(v)
            except json.JSONDecodeError:
                return {}
            return parsed if isinstance(parsed, dict) else {}
        return v


class VapiToolCall(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    function: VapiToolFunction


class VapiArtifact(BaseModel):
    """Subset of Vapi's Artifact object relevant to end-of-call-report."""

    model_config = ConfigDict(extra="ignore")

    transcript: str | None = None
    recordingUrl: str | None = None


class VapiAnalysis(BaseModel):
    """Subset of Vapi's Analysis object relevant to end-of-call-report."""

    model_config = ConfigDict(extra="ignore")

    summary: str | None = None


class VapiMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: str
    call: VapiCall | None = None
    customer: VapiCustomer | None = None
    toolCallList: list[VapiToolCall] = Field(default_factory=list)
    # end-of-call-report fields (all optional: absent for other message types).
    endedReason: str | None = None
    startedAt: str | None = None
    endedAt: str | None = None
    artifact: VapiArtifact | None = None
    analysis: VapiAnalysis | None = None

    def caller_number(self) -> str | None:
        """Caller ID from `message.customer`, falling back to `message.call.customer`."""
        for customer in (self.customer, self.call.customer if self.call else None):
            if customer and customer.number:
                return customer.number
        return None


class VapiWebhookPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    message: VapiMessage

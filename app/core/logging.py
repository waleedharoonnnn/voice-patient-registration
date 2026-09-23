"""Structured JSON logging to stdout, plus PII masking helpers.

One JSON object per line: timestamp (UTC), level, logger, message, request_id, call_id
(when set), and any extra fields passed via `logging.LoggerAdapter`/`extra=`.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
call_id_var: ContextVar[str | None] = ContextVar("call_id", default=None)

_RESERVED_LOG_RECORD_ATTRS = frozenset(
    {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "taskName",
    }
)


class JsonFormatter(logging.Formatter):
    """Renders each LogRecord as a single line of JSON."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        request_id = request_id_var.get()
        if request_id is not None:
            payload["request_id"] = request_id
        call_id = call_id_var.get()
        if call_id is not None:
            payload["call_id"] = call_id

        for key, value in record.__dict__.items():
            if key not in _RESERVED_LOG_RECORD_ATTRS and not key.startswith("_"):
                payload.setdefault(key, value)

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    """Install the JSON formatter on the root logger, replacing any existing handlers."""
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)


# --- PII masking -------------------------------------------------------------------

_PHONE_DIGITS_RE = re.compile(r"\d")


def mask_phone(phone: str, *, log_pii: bool = False) -> str:
    """Mask all but the last 4 digits of a phone number, e.g. '***-***-1234'.

    Non-digit characters in the input are dropped; the result is always in the
    '***-***-1234' shape when at least 4 digits are present.
    """
    if log_pii:
        return phone
    digits = _PHONE_DIGITS_RE.findall(phone)
    if len(digits) < 4:
        return "***"
    last_four = "".join(digits[-4:])
    return f"***-***-{last_four}"


def mask_email(email: str, *, log_pii: bool = False) -> str:
    """Mask the local part of an email, e.g. 'j***@example.com'."""
    if log_pii:
        return email
    local, sep, domain = email.partition("@")
    if not sep:
        return "***"
    if not local:
        return f"***{sep}{domain}"
    return f"{local[0]}***{sep}{domain}"


def mask_name(name: str, *, log_pii: bool = False) -> str:
    """Mask a person's name, keeping only the first letter of each word, e.g. 'J*** D***'."""
    if log_pii:
        return name
    words = name.split(" ")
    masked_words = [f"{word[0]}***" if word else word for word in words]
    return " ".join(masked_words)

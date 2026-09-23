"""Validation for email addresses.

Uses pydantic's EmailStr (backed by the `email-validator` package) rather than a
hand-rolled regex: RFC 5322-compliant email validation has enough edge cases (quoted
locals, IDN domains, length limits) that a maintained library is worth the dependency.
"""

from __future__ import annotations

from pydantic import EmailStr, TypeAdapter

_ADAPTER: TypeAdapter[str] = TypeAdapter(EmailStr)


def validate_email(value: str) -> str:
    """Validate and normalize an email address, raising ValueError on failure."""
    try:
        return _ADAPTER.validate_python(value.strip())
    except Exception as exc:
        raise ValueError("Email address is not valid.") from exc

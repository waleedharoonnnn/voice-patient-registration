"""Unit tests for app.validation.email."""

from __future__ import annotations

import pytest

from app.validation.email import validate_email


@pytest.mark.parametrize(
    "raw",
    [
        "jane.doe@example.com",
        "j@example.co",
        "jane+tag@example.com",
    ],
)
def test_validate_email_valid(raw: str) -> None:
    assert validate_email(raw) == raw


@pytest.mark.parametrize(
    "raw",
    ["not-an-email", "missing-domain@", "@missing-local.com", "", "spaces in@email.com"],
)
def test_validate_email_invalid(raw: str) -> None:
    with pytest.raises(ValueError, match="Email address is not valid"):
        validate_email(raw)

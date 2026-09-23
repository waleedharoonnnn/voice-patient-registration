"""Unit tests for the PII masking helpers."""

from __future__ import annotations

from app.core.logging import mask_email, mask_name, mask_phone


def test_mask_phone_masks_all_but_last_four() -> None:
    assert mask_phone("2025551234") == "***-***-1234"


def test_mask_phone_handles_formatted_input() -> None:
    assert mask_phone("+1 (202) 555-1234") == "***-***-1234"


def test_mask_phone_returns_raw_when_log_pii_true() -> None:
    assert mask_phone("2025551234", log_pii=True) == "2025551234"


def test_mask_phone_short_input_fully_masked() -> None:
    assert mask_phone("12") == "***"


def test_mask_email_masks_local_part() -> None:
    assert mask_email("jane.doe@example.com") == "j***@example.com"


def test_mask_email_returns_raw_when_log_pii_true() -> None:
    assert mask_email("jane.doe@example.com", log_pii=True) == "jane.doe@example.com"


def test_mask_email_without_at_sign() -> None:
    assert mask_email("not-an-email") == "***"


def test_mask_name_masks_each_word() -> None:
    assert mask_name("Jane Doe") == "J*** D***"


def test_mask_name_returns_raw_when_log_pii_true() -> None:
    assert mask_name("Jane Doe", log_pii=True) == "Jane Doe"


def test_mask_name_single_word() -> None:
    assert mask_name("Madonna") == "M***"

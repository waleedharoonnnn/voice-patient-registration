"""Unit tests for scripts/sync_vapi.py's pure logic: no network calls."""

from __future__ import annotations

import pytest
from scripts import sync_vapi


def test_strip_html_comments_removes_annotation_blocks() -> None:
    markdown = "Hello\n<!-- this is a note\nspanning lines -->\nWorld"
    assert sync_vapi.strip_html_comments(markdown) == "Hello\n\nWorld"


def test_strip_html_comments_removes_multiple_blocks() -> None:
    markdown = "<!-- a -->Keep this<!-- b -->and this<!-- c -->"
    assert sync_vapi.strip_html_comments(markdown) == "Keep thisand this"


def test_strip_html_comments_leaves_plain_text_untouched() -> None:
    markdown = "No comments here at all."
    assert sync_vapi.strip_html_comments(markdown) == markdown


def test_load_system_prompt_strips_comments_from_real_file() -> None:
    prompt = sync_vapi.load_system_prompt()
    assert "<!--" not in prompt
    assert "-->" not in prompt
    assert "Sarah" in prompt


def test_resolve_placeholders_substitutes_known_vars() -> None:
    node = {"url": "$PUBLIC_BASE_URL/webhook", "nested": ["$SECRET"]}
    env = {"PUBLIC_BASE_URL": "https://example.ngrok.dev", "SECRET": "shh"}

    resolved = sync_vapi._resolve_placeholders(node, env)

    assert resolved == {"url": "https://example.ngrok.dev/webhook", "nested": ["shh"]}


def test_resolve_placeholders_raises_on_unknown_var() -> None:
    with pytest.raises(sync_vapi.SyncError, match="UNKNOWN"):
        sync_vapi._resolve_placeholders("$UNKNOWN", {})


def test_resolve_placeholders_leaves_non_placeholder_strings_untouched() -> None:
    assert sync_vapi._resolve_placeholders("plain string", {}) == "plain string"


def test_redact_masks_server_secret_header() -> None:
    payload = {"server": {"headers": {"X-Vapi-Secret": "real-secret-value"}}}

    redacted = sync_vapi._redact(payload)

    assert redacted["server"]["headers"]["X-Vapi-Secret"] == sync_vapi._REDACTED
    assert payload["server"]["headers"]["X-Vapi-Secret"] == "real-secret-value"  # not mutated


def test_redact_handles_missing_server_block() -> None:
    assert sync_vapi._redact({"name": "x"}) == {"name": "x"}


def test_tool_identity_for_function_tool() -> None:
    spec = {"type": "function", "function": {"name": "create_patient"}}
    assert sync_vapi._tool_identity(spec) == ("function", "create_patient")


def test_tool_identity_for_end_call_tool() -> None:
    assert sync_vapi._tool_identity({"type": "endCall"}) == ("endCall", None)


def test_existing_tool_identity_matches_tool_identity_shape() -> None:
    existing = {"type": "function", "function": {"name": "create_patient"}, "id": "abc"}
    spec = {"type": "function", "function": {"name": "create_patient"}}
    assert sync_vapi._existing_tool_identity(existing) == sync_vapi._tool_identity(spec)


def test_build_assistant_payload_injects_prompt_and_tool_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://example.ngrok.dev/")
    monkeypatch.setenv("VAPI_WEBHOOK_SECRET", "test-secret")
    from app.core.config import get_settings

    get_settings.cache_clear()

    payload = sync_vapi.build_assistant_payload(tool_ids=["tool-1", "tool-2"])

    assert payload["model"]["toolIds"] == ["tool-1", "tool-2"]
    assert "Sarah" in payload["model"]["messages"][0]["content"]
    assert "<!--" not in payload["model"]["messages"][0]["content"]
    assert payload["server"]["url"] == "https://example.ngrok.dev/vapi/webhook"
    assert payload["server"]["headers"]["X-Vapi-Secret"] == "test-secret"

    get_settings.cache_clear()


def test_build_assistant_payload_requires_public_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Set (not delete): a real .env file may also define PUBLIC_BASE_URL, and
    # pydantic-settings falls back to it when the var isn't in the process env at all.
    monkeypatch.setenv("PUBLIC_BASE_URL", "")
    from app.core.config import get_settings

    get_settings.cache_clear()

    with pytest.raises(sync_vapi.SyncError, match="PUBLIC_BASE_URL"):
        sync_vapi.build_assistant_payload(tool_ids=[])

    get_settings.cache_clear()

"""Idempotent sync of our Vapi tools, assistant, and phone-number assignment.

Reads `vapi/tools/*.json` (OpenAI-style function schemas), `vapi/prompts/system_prompt.md`
(strips HTML-comment annotations), and `vapi/assistant.json` (with `$PUBLIC_BASE_URL` /
`$VAPI_WEBHOOK_SECRET` placeholders resolved from env, and `$SYSTEM_PROMPT` / `$TOOL_IDS`
sentinels filled in by this script), then upserts each via the Vapi REST API
(https://api.vapi.ai) by name/type — never creates a duplicate on a second run — and
assigns the assistant to `VAPI_PHONE_NUMBER_ID` for inbound calls.

Usage: `uv run python -m scripts.sync_vapi [--dry-run]` (or `make sync-vapi`,
`make sync-vapi-dry-run`).
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from app.core.config import get_settings

VAPI_API_BASE = "https://api.vapi.ai"
REPO_ROOT = Path(__file__).parent.parent
TOOLS_DIR = REPO_ROOT / "vapi" / "tools"
ASSISTANT_PATH = REPO_ROOT / "vapi" / "assistant.json"
PROMPT_PATH = REPO_ROOT / "vapi" / "prompts" / "system_prompt.md"
SYNC_STATE_PATH = REPO_ROOT / "vapi" / ".sync-state.json"

_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_PLACEHOLDER_RE = re.compile(r"\$([A-Z_][A-Z0-9_]*)")
_REDACTED = "***REDACTED***"

_RETRY_STATUS_CODES = {429, 500, 502, 503, 504}
_MAX_RETRIES = 4
_BASE_BACKOFF_SECONDS = 1.0


class SyncError(RuntimeError):
    """Raised for any condition that should stop the sync with a clear message."""


# --- Prompt processing ----------------------------------------------------------------


def strip_html_comments(markdown: str) -> str:
    """Remove `<!-- ... -->` annotation blocks, leaving only what the model should see."""
    return _HTML_COMMENT_RE.sub("", markdown)


def load_system_prompt() -> str:
    raw = PROMPT_PATH.read_text(encoding="utf-8")
    stripped = strip_html_comments(raw)
    # Collapse the blank-line runs left behind by removed comment blocks.
    collapsed = re.sub(r"\n{3,}", "\n\n", stripped)
    return collapsed.strip()


# --- Placeholder resolution ------------------------------------------------------------


def _resolve_placeholders(node: Any, env: dict[str, str]) -> Any:
    if isinstance(node, dict):
        return {k: _resolve_placeholders(v, env) for k, v in node.items()}
    if isinstance(node, list):
        return [_resolve_placeholders(v, env) for v in node]
    if isinstance(node, str):

        def _sub(match: re.Match[str]) -> str:
            name = match.group(1)
            if name not in env:
                raise SyncError(f"Unresolved placeholder in vapi/assistant.json: ${name}")
            return env[name]

        return _PLACEHOLDER_RE.sub(_sub, node)
    return node


def build_assistant_payload(tool_ids: list[str]) -> dict[str, Any]:
    settings = get_settings()
    if not settings.PUBLIC_BASE_URL:
        raise SyncError("PUBLIC_BASE_URL is required to build the assistant payload.")
    raw = json.loads(ASSISTANT_PATH.read_text(encoding="utf-8"))

    # Sentinels that need a computed value, not a plain env lookup — resolved first so
    # the generic placeholder pass below never has to see them.
    raw["model"]["messages"][0]["content"] = load_system_prompt()
    raw["model"]["toolIds"] = tool_ids

    env = {
        "PUBLIC_BASE_URL": settings.PUBLIC_BASE_URL.rstrip("/"),
        "VAPI_WEBHOOK_SECRET": settings.VAPI_WEBHOOK_SECRET.get_secret_value(),
    }
    resolved: dict[str, Any] = _resolve_placeholders(raw, env)
    return apply_stack_overrides(resolved)


def apply_stack_overrides(payload: dict[str, Any]) -> dict[str, Any]:
    """Apply the `VAPI_*_OVERRIDE` env rollback knobs (see app/core/config.py).

    Transcriber and voice are replaced wholesale because their fields are provider-specific;
    the model block is merged so the system prompt, tool IDs and temperature survive.
    """
    settings = get_settings()
    if settings.VAPI_TRANSCRIBER_OVERRIDE:
        payload["transcriber"] = dict(settings.VAPI_TRANSCRIBER_OVERRIDE)
    if settings.VAPI_VOICE_OVERRIDE:
        payload["voice"] = dict(settings.VAPI_VOICE_OVERRIDE)
    if settings.VAPI_MODEL_OVERRIDE:
        payload["model"] = {**payload["model"], **settings.VAPI_MODEL_OVERRIDE}
    return payload


def _redact(payload: dict[str, Any]) -> dict[str, Any]:
    redacted = copy.deepcopy(payload)
    headers = redacted.get("server", {}).get("headers")
    if isinstance(headers, dict):
        for key in headers:
            headers[key] = _REDACTED
    return redacted


# --- HTTP with retry/backoff -----------------------------------------------------------


def _request(client: httpx.Client, method: str, path: str, **kwargs: Any) -> httpx.Response:
    url = f"{VAPI_API_BASE}{path}"
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            response = client.request(method, url, **kwargs)
        except httpx.TransportError as exc:
            last_exc = exc
        else:
            if response.status_code not in _RETRY_STATUS_CODES:
                response.raise_for_status()
                return response
            last_exc = SyncError(f"{method} {path} -> {response.status_code}: {response.text}")

        if attempt < _MAX_RETRIES:
            backoff = _BASE_BACKOFF_SECONDS * (2**attempt)
            print(
                f"  retrying {method} {path} in {backoff:.0f}s (attempt {attempt + 1})",
                file=sys.stderr,
            )
            time.sleep(backoff)

    raise SyncError(f"{method} {path} failed after {_MAX_RETRIES + 1} attempts: {last_exc}")


# --- Tools -------------------------------------------------------------------------------


def _load_function_tool_specs() -> list[dict[str, Any]]:
    """Wrap each vapi/tools/*.json (raw OpenAI function schema) as a Vapi FunctionTool."""
    specs = []
    for path in sorted(TOOLS_DIR.glob("*.json")):
        function_schema = json.loads(path.read_text(encoding="utf-8"))
        specs.append({"type": "function", "function": function_schema})
    return specs


def _tool_identity(spec: dict[str, Any]) -> tuple[str, str | None]:
    if spec["type"] == "function":
        return ("function", spec["function"]["name"])
    return (spec["type"], None)


def _existing_tool_identity(tool: dict[str, Any]) -> tuple[str, str | None]:
    if tool.get("type") == "function":
        return ("function", (tool.get("function") or {}).get("name"))
    return (tool.get("type", ""), None)


def upsert_tools(client: httpx.Client, dry_run: bool) -> list[str]:
    """Create/update every custom tool + the built-in end-call tool. Returns their IDs."""
    specs = _load_function_tool_specs()
    specs.append({"type": "endCall"})

    existing_tools = _request(client, "GET", "/tool", params={"limit": 1000}).json()
    existing_by_identity = {_existing_tool_identity(t): t for t in existing_tools}

    tool_ids: list[str] = []
    for spec in specs:
        identity = _tool_identity(spec)
        label = identity[1] or identity[0]
        existing = existing_by_identity.get(identity)

        if dry_run:
            action = "update" if existing else "create"
            print(f"  [dry-run] tool '{label}': would {action}")
            tool_ids.append(existing["id"] if existing else f"<new:{label}>")
            continue

        if existing:
            response = _request(client, "PATCH", f"/tool/{existing['id']}", json=spec)
            print(f"  tool '{label}': updated ({existing['id']})")
        else:
            response = _request(client, "POST", "/tool", json=spec)
            print(f"  tool '{label}': created ({response.json()['id']})")
        tool_ids.append(response.json()["id"])

    return tool_ids


# --- Assistant ---------------------------------------------------------------------------


def upsert_assistant(client: httpx.Client, payload: dict[str, Any], dry_run: bool) -> str:
    existing_assistants = _request(client, "GET", "/assistant", params={"limit": 1000}).json()
    existing = next((a for a in existing_assistants if a.get("name") == payload["name"]), None)

    if dry_run:
        action = "update" if existing else "create"
        print(f"  [dry-run] assistant '{payload['name']}': would {action}")
        if existing:
            _print_diff_summary(existing, payload)
        return existing["id"] if existing else "<new-assistant>"

    if existing:
        response = _request(client, "PATCH", f"/assistant/{existing['id']}", json=payload)
        print(f"  assistant '{payload['name']}': updated ({existing['id']})")
    else:
        response = _request(client, "POST", "/assistant", json=payload)
        print(f"  assistant '{payload['name']}': created ({response.json()['id']})")
    assistant_id: str = response.json()["id"]
    return assistant_id


# Paths whose values are never printed: secrets, or too long to be useful in a diff line.
_OPAQUE_DIFF_PATHS = ("server.headers", "model.messages")


def diff_paths(live: Any, new: Any, path: str = "") -> list[tuple[str, Any, Any]]:
    """Leaf-level differences as (dotted.path, live_value, new_value).

    Only keys present in `new` are compared: a PATCH leaves other live fields alone, so
    they are not changes this sync would make. Opaque paths are compared as a whole.
    """
    if isinstance(new, dict) and isinstance(live, dict) and path not in _OPAQUE_DIFF_PATHS:
        diffs: list[tuple[str, Any, Any]] = []
        for key, value in new.items():
            child = f"{path}.{key}" if path else key
            diffs.extend(diff_paths(live.get(key), value, child))
        return diffs
    return [] if live == new else [(path, live, new)]


def _print_diff_summary(existing: dict[str, Any], new: dict[str, Any]) -> None:
    """Field-level diff of what a sync would change, with secrets and the prompt elided."""
    diffs = diff_paths(existing, new)
    if not diffs:
        print("    no changes")
    for path, live_value, new_value in diffs:
        if path.startswith(_OPAQUE_DIFF_PATHS):
            print(f"    ~ {path}: (differs; value not shown)")
        else:
            print(f"    ~ {path}: {json.dumps(live_value)} -> {json.dumps(new_value)}")


def assign_phone_number(client: httpx.Client, assistant_id: str, dry_run: bool) -> None:
    settings = get_settings()
    phone_number_id = settings.VAPI_PHONE_NUMBER_ID
    if not phone_number_id:
        print("  VAPI_PHONE_NUMBER_ID not set — skipping inbound assignment.")
        return

    if dry_run:
        print(
            f"  [dry-run] phone number {phone_number_id}: would assign assistantId={assistant_id}"
        )
        return

    _request(
        client, "PATCH", f"/phone-number/{phone_number_id}", json={"assistantId": assistant_id}
    )
    print(f"  phone number {phone_number_id}: assigned to assistant {assistant_id}")


# --- Orchestration -----------------------------------------------------------------------


def _validate_env() -> None:
    settings = get_settings()
    missing = []
    if not settings.VAPI_API_KEY:
        missing.append("VAPI_API_KEY")
    if not settings.PUBLIC_BASE_URL:
        missing.append("PUBLIC_BASE_URL")
    if not settings.VAPI_WEBHOOK_SECRET.get_secret_value():
        missing.append("VAPI_WEBHOOK_SECRET")
    if missing:
        raise SyncError(f"Missing required env vars: {', '.join(missing)}")


def run(dry_run: bool) -> None:
    _validate_env()
    settings = get_settings()
    if not settings.VAPI_API_KEY:
        raise SyncError("VAPI_API_KEY is required.")  # pragma: no cover (guarded above)

    client = httpx.Client(
        headers={"Authorization": f"Bearer {settings.VAPI_API_KEY.get_secret_value()}"},
        timeout=httpx.Timeout(20.0),
    )
    try:
        print("Syncing tools...")
        tool_ids = upsert_tools(client, dry_run)

        print("Building assistant payload...")
        payload = build_assistant_payload(tool_ids)
        if dry_run:
            print("Resolved assistant payload (secrets redacted):")
            print(json.dumps(_redact(payload), indent=2))

        print("Syncing assistant...")
        assistant_id = upsert_assistant(client, payload, dry_run)

        print("Assigning phone number...")
        assign_phone_number(client, assistant_id, dry_run)

        if not dry_run:
            state = {"assistant_id": assistant_id, "tool_ids": tool_ids}
            SYNC_STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
            print(f"Wrote {SYNC_STATE_PATH.relative_to(REPO_ROOT)}")
    finally:
        client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the resolved payload and planned actions without calling the Vapi API.",
    )
    args = parser.parse_args()

    try:
        run(dry_run=args.dry_run)
    except SyncError as exc:
        print(f"sync_vapi failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()

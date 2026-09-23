# Batch 5 report

## Scope

The voice agent itself: system prompt (`vapi/prompts/system_prompt.md`), assistant
config as code (`vapi/assistant.json`), the idempotent sync script
(`scripts/sync_vapi.py`), and supporting docs/tests. Appointments/transcripts are Batch
6 — the prompt has a disabled placeholder section (§3i) for the appointment offer.

## Vapi API research (before writing any config)

Per instruction, fetched and read the **live OpenAPI spec** (`https://api.vapi.ai/api-json`)
rather than guessing field names, plus `docs.vapi.ai` pages for concepts. All doc URLs
relied on are cited in `docs/adr/0006-voice-platform-and-model.md`.

Two things the batch instructions assumed that **don't exist in the current API** —
confirmed by searching the full schema, not by absence of knowledge:
- Assistant-level `silenceTimeoutSeconds` / `idleMessages` — not on `CreateAssistantDTO`.
  Silence handling is prompt-level only, backed by `maxDurationSeconds` + the `endCall`
  tool.
- "Backchanneling" — no such field anywhere in the schema.

Everything else (model/voice/transcriber field names, `server.headers` for webhook auth,
`toolIds` referencing separately-created tools, the built-in `endCall` tool type,
`{{"now" | date: ...}}` for date injection, `assistantId` on the phone-number PATCH) was
confirmed directly against the schema or `docs.vapi.ai/assistants/dynamic-variables`.

## Files created

- `vapi/prompts/system_prompt.md` — annotated prompt (HTML comments = design notes,
  stripped before upload)
- `vapi/assistant.json` — model (gpt-4o-mini, temp 0.3), voice (OpenAI `alloy`),
  transcriber (Deepgram nova-3, multilingual), turn-taking tuned for digits/spelling,
  server config, recording/transcript/summary enabled
- `scripts/sync_vapi.py` — idempotent upsert (tools by name/type, assistant by name,
  phone number assignment), `--dry-run`, retry/backoff on 429/5xx, secrets redacted in
  dry-run output, never logs the API key
- `docs/prompt-engineering.md`, `docs/adr/0006-voice-platform-and-model.md`,
  `docs/voice-tools.md` (carried forward, unchanged), `docs/test-call-script.md`
- `tests/unit/test_sync_vapi.py` (14 tests: comment stripping, placeholder resolution,
  redaction, tool identity matching, payload building — no network)

## Decisions

- **`toolIds`/`content` as JSON string sentinels** (`"$TOOL_IDS"`, `"$SYSTEM_PROMPT"`) in
  `assistant.json`, resolved by the script before the generic `$VAR` env-placeholder pass
  — keeps the static file valid JSON while still letting it document what gets injected.
- **`server.headers` over a stored Vapi credential** for webhook auth — simpler for this
  project's scope, and our webhook already accepted `X-Vapi-Secret` unchanged from Batch
  3+4 (confirmed still correct against the live schema; no webhook code touched).
- **Matching tools by `function.name`, not a separate `name` field** — the live schema
  has no top-level tool name for function tools, only `function.name`.

## Verification (all done directly, not simulated)

| Step | Result |
|---|---|
| `ruff check` / `format --check` / `mypy app` | clean |
| `pytest` | **217 passed**, 90% coverage on `app/` |
| `make sync-vapi --dry-run` | printed resolved payload, secrets redacted (`X-Vapi-Secret` shown as `***REDACTED***`), correctly reported 5 tools + assistant + phone number as "would create" |
| `make sync-vapi` (real) | created 4 function tools + 1 `endCall` tool, created assistant, assigned phone number `+17327825438` |
| Re-ran `make sync-vapi` | same IDs, "updated" not "created" for everything — **idempotency confirmed** |
| `GET /assistant/{id}` via curl | confirmed `model=gpt-4o-mini`, `voice=openai/alloy`, `transcriber=deepgram/nova-3/multi`, 5 `toolIds`, correct `server.url`, 10,388-char system prompt (comments stripped) |
| `GET /phone-number/{id}` via curl | confirmed `assistantId` matches the created assistant |
| ngrok tunnel | wasn't installed on this machine — installed via `winget install ngrok.ngrok`, hit a stale-binary auth error (agent 3.3.1 too old for the account, min 3.20.0), ran `ngrok update` → 3.39.11, then tunnel came up clean |
| `curl https://ranking-acclaim-given.ngrok-free.dev/health` | 200 through the tunnel |
| Signed tool-call through `PUBLIC_BASE_URL/vapi/webhook` | `find_patient_by_phone` for the seed patient's number returned `MATCH: ... Jane Doe` — full path (ngrok → local server → DB) confirmed live |

## Manual checks (the test-call scenarios)

`docs/test-call-script.md` — 14 scenarios (happy path, correction, out-of-order,
future DOB, bad phone/state/ZIP, start-over, interrupted read-back, duplicate caller,
update with correct/wrong DOB, Spanish, hang-up mid-call, DB failure). These require an
actual voice call (web or phone) and are yours to run per the assignment instructions —
I can't speak into a microphone. Everything each scenario depends on (tools, webhook,
DB, auth) has been verified working independently above.

## Open issues / risks

- **Batch 3+4's work was never committed** before this batch started — both batches are
  currently uncommitted together in the working tree. Flagging before committing
  anything, in case you want them reviewed/split differently than my suggested grouping.
- Prompt quality (conversational naturalness, whether the model actually follows "one
  question at a time" in practice) can only be judged by a real call — the verification
  above proves the *plumbing* works, not the *conversation quality*. That's what
  `docs/test-call-script.md` is for.
- `voice/tools.py` coverage remains at 68% (unchanged from Batch 3+4, no tools code
  touched this batch).

## Suggested commits

Batch 3+4 (still pending from before this batch):
1. `feat: add patient schemas, repository, and service layer`
2. `feat: add /patients REST API and Vapi webhook with tool handlers`
3. `test: add REST, webhook, and service unit tests`
4. `fix: dispose DB engine per test, fix null-required-field validation, fix DOB filter format, allow non-SSL local Postgres`
5. `docs: add ADRs 0004/0005, voice-tools.md, update README`

Batch 5 (this batch):
6. `feat: add system prompt, assistant config, and Vapi sync script`
7. `test: add sync_vapi unit tests`
8. `docs: add ADR 0006, prompt-engineering.md, test-call-script.md, update README`

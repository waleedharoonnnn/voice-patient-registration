# 0004 — Voice tool handlers call the service layer directly

## Status

Accepted.

## Context

`docs/adr/0002-layered-architecture.md` already established that voice bypasses the REST
API and calls `app/services/` directly. This ADR covers the two implementation details
that follow from that once the webhook was actually built.

## Decisions

- **Each tool handler builds its own `PatientService(PatientRepository(session))`** from
  the webhook's request-scoped DB session (`get_webhook_db`), same as a REST request
  builds one via `app/api/deps.py`. No separate "voice service" class — same service,
  same validation, same envelope-free thin wrapping on the way out.
- **The webhook session gets a tighter `statement_timeout`** (`get_webhook_db`, default
  5s) than the REST session, and each tool call is additionally wrapped in
  `asyncio.wait_for` (default 8s). Two layers because a hung DB query and a hung tool
  handler (e.g. a bug in application code, not just the DB) are different failure modes;
  both must never hang a live call.
- **Tool handlers never raise.** Every handler catches its own errors and returns a
  string prefix (`SAVE_FAILED: ...`, `INVALID: ...`) instead of propagating an exception,
  because there's no HTTP client on the other end to receive a 500 — there's a caller
  mid-sentence. The webhook route itself never returns non-200 for a `tool-calls`
  message; see ADR 0005 for the auth-layer exception to that.

## Consequences

- Any new voice tool is a thin function in `app/voice/tools.py` that validates via
  `app/schemas/patient.py`, calls a `PatientService` method, and formats a result string
  — it should never need new business logic of its own.

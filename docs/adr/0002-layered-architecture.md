# 0002 — Layered architecture, and why voice calls the service layer directly

## Status

Accepted.

## Context

Patient data can be written from two entry points: the REST API (`/patients`) and the
Vapi voice agent (via tool-call webhooks during a live call). Both paths must apply the
exact same validation and business rules — a phone number normalized one way over HTTP
and another way over a voice tool call would silently corrupt data and make the two
surfaces diverge over time. The voice path also has a hard constraint the REST path does
not: tool handlers must never raise or 500 back to Vapi, since a broken response there
means dead air for a caller on the phone.

## Decision

Enforce one-directional layering:

```
api/ , voice/  →  services/  →  repositories/  →  models/ , db/
```

- `app/api/routers/` and `app/voice/` are thin. They parse/validate the transport-specific
  payload (HTTP JSON vs. Vapi's tool-call/webhook shape), call into `services/`, and
  translate the result back into their transport's response shape (the envelope for HTTP;
  a short speakable string for voice). They contain no SQL and no business rules.
- `app/services/` is the **only** layer both entry points call into. All business logic —
  duplicate detection, idempotency via `source_call_id`, what counts as a valid patient
  record — lives here exactly once.
- `app/repositories/` only knows how to read/write rows; it has no HTTP or voice
  awareness and no business rules.
- `app/validation/` holds pure, dependency-free validators (phone, state, ZIP, DOB, names)
  imported by both Pydantic schemas (REST) and voice tool handlers, so the same rule is
  never implemented twice. The database also enforces the same constraints via CHECK
  constraints, as defense in depth against any bug in the Python layer.

The voice agent calls `app/services/` **directly as a Python function call**, not by
making an HTTP request back to our own `/patients` API. The take-home spec permits this,
and it avoids an unnecessary network hop, a self-referential auth story (the voice
process would need its own API key to call itself), and a duplicate failure mode
(network errors on top of validation errors) for something that can just be a function
call in the same process.

## Consequences

- Any new business rule (e.g. a new duplicate-detection heuristic) is added once in
  `services/` and is automatically correct for both entry points — there is no "remember
  to update both places."
- `voice/` handlers must catch everything `services/` can raise and convert it to a
  speakable string; they are the last line of defense against dead air, per CLAUDE.md §8.
- This does mean `services/` must be written without any assumption about which caller
  invoked it (no HTTP-specific exceptions, no Vapi-specific types leaking in), which is
  enforced by dependency direction: `services/` never imports from `api/` or `voice/`.

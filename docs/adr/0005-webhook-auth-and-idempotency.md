# 0005 — Webhook auth and idempotency

## Status

Accepted.

## Context

`POST /vapi/webhook` is a public endpoint Vapi calls during a live phone call. It needs
its own auth (not `X-API-Key` — that's for our REST clients) and must survive Vapi
retrying a tool call without creating duplicate patients.

## Decisions

- **Auth accepts either `X-Vapi-Secret: <secret>` or `Authorization: Bearer <secret>`**,
  compared with `secrets.compare_digest` against `VAPI_WEBHOOK_SECRET`. Two accepted
  header shapes because Vapi's own docs/dashboard configuration has used both forms
  across versions; accepting both avoids a redeploy if Vapi's default changes. A missing
  or wrong secret is the one case the webhook returns non-200 (401, enveloped) — this is
  the transport-auth boundary, not a mid-call tool failure.
- **Idempotency key is Vapi's own `call.id`**, stored as `patients.source_call_id`
  (unique). `create_patient` checks it first: if a patient with that call id already
  exists, return it with `created=False` (`ALREADY_SAVED`) instead of inserting again.
  This covers Vapi retrying the same tool call within one call — the realistic retry
  scenario — without needing a separate idempotency-key header or cache.
- **Non-tool-call messages (`status-update`, etc.) always return `200 {}`.** They're
  informational; Vapi doesn't expect a meaningful body back, and a webhook that errors on
  a message type it doesn't specifically handle would be fragile against Vapi adding new
  message types.
- **Payload parsing is tolerant (`extra="ignore"`) and defensive**: a payload that
  doesn't match the expected shape at all is logged and answered with `200 {}` rather
  than a 422/500, so a Vapi payload change never breaks a live call.

## Consequences

- `source_call_id` idempotency only covers retries *within the same call*. A caller who
  hangs up and calls back gets a new `call.id` and (correctly) a new patient, unless
  `find_patient_by_phone` catches the duplicate first (the spec's bonus behavior).
- Because malformed payloads are swallowed into `200 {}`, a genuine integration bug on
  Vapi's side could go unnoticed without checking logs — acceptable trade-off given the
  alternative (breaking live calls) is worse; logs capture every case explicitly.

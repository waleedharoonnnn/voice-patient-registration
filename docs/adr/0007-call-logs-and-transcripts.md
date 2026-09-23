# 0007 — Call logs and transcripts

## Status

Accepted.

## Context

The spec's bonus asks for a transcript or summary linked to the patient. The core
evaluation also asks what happens when the phone connection drops mid-call. A dropped
call leaves no patient record, so without a log there'd be nothing for staff to follow
up on.

## Decisions

- **One `call_logs` row per Vapi `call.id`** (unique). Every write is an upsert, because
  Vapi may retry both tool calls and the end-of-call report.
- **Two writers, one row.** Tool handlers record progress as soon as a save succeeds
  (`registered`/`updated`, with `patient_id`) or fails (`failed`). The
  `end-of-call-report` adds the transcript, summary, `endedReason`, timestamps, duration
  and recording URL.
- **Outcome for calls that never saved:** if no tool ever set an outcome, the
  end-of-call-report marks the call `abandoned`. A real outcome is never downgraded, so a
  `registered` call stays `registered`. Abandoned and failed calls show up in the
  dashboard's follow-up queue with their transcripts. That's how we handle a dropped
  connection.
- **Payload fields verified against Vapi's live OpenAPI spec**
  (`ServerMessageEndOfCallReport`): `endedReason`, `startedAt`/`endedAt` (ISO strings),
  `artifact.transcript`, `artifact.recordingUrl`, `analysis.summary`. There's no duration
  field, so we compute it from the timestamps.
- **`patient_id` is `ON DELETE SET NULL`**, so a call's history outlives its patient row.
- **Never a 500 to Vapi.** End-of-call handling catches and logs its own errors. Repository
  writes run inside savepoints, so a failed write can't abort the request's transaction.

## Consequences

- Transcripts contain PHI. They're only exposed behind the API key and the dashboard's
  Basic auth, and never logged.
- `language` stays empty for now: Vapi's report doesn't carry the detected language.

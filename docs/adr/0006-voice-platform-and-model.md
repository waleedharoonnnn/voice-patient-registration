# 0006 — Voice platform, model, voice, and transcriber choices

## Status

Accepted.

## Sources consulted (Batch 5, current at time of writing)

- `https://api.vapi.ai/api-json` — Vapi's live OpenAPI spec. **Primary source for every
  field name, endpoint, and enum used in `vapi/assistant.json` and
  `scripts/sync_vapi.py`** — verified directly against the schema rather than guessed,
  per instruction.
- `https://docs.vapi.ai/assistants` — assistant concept overview.
- `https://docs.vapi.ai/server-url` and `https://docs.vapi.ai/server-url/events` — server
  webhook concept and the `tool-calls` message/response shape.
- `https://docs.vapi.ai/assistants/dynamic-variables` — `{{now}}` / LiquidJS `date` filter
  syntax, used in the prompt's guardrails section.

## Decisions

**Model: OpenAI `gpt-4o-mini`, temperature 0.3.** Cost-efficient tier with reliable tool
calling (function calling is a first-class OpenAI feature, not bolted on). Temperature
0.3 favors consistent instruction-following (one question at a time, never inventing
data) over creative variation, which this task has no use for. Confirmed `model` is a
free-form string on `OpenAIModel` in the live schema — no enum constraint to satisfy.
**Upgrade path**: if tool-call reliability or multilingual quality is lacking in
practice, `gpt-4o` is a drop-in `model` value change with no other config touched.

**Transcriber: Deepgram `nova-3`, `language: "multi"`.** Nova-3 with `language: "multi"`
is Deepgram's code-switching multilingual model — it transcribes English and Spanish
(among others) in the same stream without a language pre-selection, which this task
needs since the caller can switch to Spanish mid-call. `numerals: true` converts spoken
digits to literal numerals in the transcript (helps the model and `validate_fields`
parse phone/ZIP more reliably); `smartFormat: true` and a short `keyterm` list (nova-3's
"Keyterm Prompting" feature) bias recognition toward registration-relevant phrases.
Confirmed all of these against `DeepgramTranscriber` in the live schema.

**Voice: OpenAI `alloy`, model `gpt-4o-mini-tts`.** OpenAI TTS voices are natively
multilingual — the model matches the language of the input text automatically, so
switching to Spanish mid-call needs no voice reconfiguration (no per-language `voiceId`
or `language` field exists on `OpenAIVoice` in the schema — confirmed it isn't needed).
Chosen over Cartesia/PlayHT because those require a specific provider `voiceId`, and
guessing one wrong would silently produce a broken or wrong-sounding voice with no way to
verify without a live call — `alloy`/`gpt-4o-mini-tts` are enum-confirmed, stable values.
Same "mini" cost tier as the LLM, reasonable quality/cost trade-off on free credits.

**Turn-taking, tuned for spelling and digits.** `startSpeakingPlan.waitSeconds: 0.8`
(default is 0.4) and `transcriptionEndpointingPlan.onNumberSeconds: 3.0` (vs. 0.5 for
punctuation, 1.2 for no punctuation) — a caller reading out a phone number or spelling a
name pauses between chunks in a way that default endpointing reads as "done talking."
`stopSpeakingPlan` (`numWords: 2`, `voiceSeconds: 0.3`) allows the caller to interrupt
quickly without the assistant droning through a whole sentence first.

**Not configured — confirmed absent from the current API, not merely skipped:**
- **Silence-based auto-hangup** (`silenceTimeoutSeconds`/`idleMessages` at the assistant
  level): searched the full `CreateAssistantDTO` schema — not present. Community threads
  reference these names, but they don't exist on the assistant resource in the live
  OpenAPI spec at time of writing. Silence handling is therefore prompt-level only ("gentle
  check-in once, then end politely" — see `vapi/prompts/system_prompt.md` §4) backed by
  `maxDurationSeconds: 900` as a hard ceiling and the explicit `endCall` tool (below).
- **Backchanneling**: no such field exists on `CreateAssistantDTO` or any nested plan in
  the current schema. Not configured; noted here so a future search for it isn't repeated.

**End call: the built-in `endCall` tool**, created and attached via `toolIds` exactly
like the four custom function tools (confirmed via `CreateEndCallToolDTO` — it's a tool
type, not an assistant-level flag). `endCallMessage` and a short `endCallPhrases` list
are configured as a lightweight backup.

**Server auth: `server.headers`, not a stored credential.** `Server.headers` (confirmed
in the schema) accepts arbitrary key-value headers sent with every webhook request —
setting `X-Vapi-Secret` there is equivalent to and simpler than creating a separate
Vapi "credential" object for a take-home project's scope. Our webhook
(`app/api/routers/vapi.py`) already accepted this exact header from Batch 3+4; no webhook
code changed in this batch.

**Server messages**: `tool-calls`, `end-of-call-report`, `status-update` — confirmed
valid values on `CreateAssistantDTO.serverMessages`. `end-of-call-report` is received
and logged (per the webhook's existing "any other message type: log and return 200")
but not yet acted upon — full handling is Batch 6.

**Recording/transcript/summary enabled** (`artifactPlan.recordingEnabled`,
`artifactPlan.transcriptPlan.enabled`, `analysisPlan.summaryPlan.enabled`) — not used
until Batch 6, but turning them on from day one means historical Batch 5 test calls
still have transcripts available when that batch starts.

## Consequences

- The assistant config references tool **IDs**, not names — `scripts/sync_vapi.py` must
  create/update tools before building the assistant payload, and re-resolves the ID list
  on every run (see the script's own docstring for the exact placeholder mechanism).
- Because `arguments` on a real Vapi tool call is a JSON-encoded **string** in the live
  schema (`ToolCallFunction.arguments: string`, not `oneOf<string, object>`), the
  object-vs-string tolerance already built into `app/voice/schemas.py` in Batch 3+4 was
  the right call, not excess defensiveness — confirmed, not changed.
- If Vapi adds assistant-level silence-hangup back in a future API version, the prompt's
  "gentle check-in once" behavior and the new config option would need to be reconciled
  (redundant but not conflicting) rather than one replacing the other outright.

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

### Final stack (revised Batch 8)

The stack was re-tuned in the Vapi dashboard after live test calls, then copied into
`vapi/assistant.json` from a `GET /assistant/{id}` so the next sync doesn't revert it.
Cost and latency are the per-component figures Vapi's dashboard shows:

| Component | Choice (exact config values) | Cost | Latency |
|---|---|---|---|
| Transcriber | `assembly-ai`, `speechModel: universal-streaming-english`, `language: en` | $0.005/min | ~390 ms |
| Model | `openai`, `gpt-4.1`, `temperature: 0.3` | $0.025/min | ~690 ms |
| Voice | `cartesia`, `model: sonic-3.5`, `voiceId: f91ab3e6-5071-4e15-b016-cde6f2bcd222` ("Aadhya - Soother") | $0.022/min | ~270 ms |
| **Total** | | **$0.052/min** | **~1.35 s** |

The total covers these three components only. Vapi's own platform fee and telephony are
billed on top.

**Model: OpenAI `gpt-4.1`, temperature 0.3.** Better instruction-following and more
reliable multi-step tool use than `gpt-4o-mini`. This matters most in the read-back →
confirm → save → offer-appointment chain, where a missed or out-of-order tool call is the
costliest failure. Temperature 0.3 keeps the agent on-script (one question at a time,
never inventing data).

**Transcriber: AssemblyAI Universal-Streaming (English).** It is the cheapest component
and has good accuracy on names, digits and addresses. Its turn detection (`formatTurns`)
works with Vapi smart endpointing (`smartEndpointingPlan.provider: vapi`, set in the
dashboard). Our registration keyterms carry over as AssemblyAI's `keytermsPrompt`
(Deepgram's equivalent field is `keyterm`).

**Voice: Cartesia Sonic 3.5, "Aadhya - Soother".** Cartesia gives the lowest time to
first audio of the options tried (~270 ms), which keeps turn-taking feeling natural. Vapi's
voice library lists this voice as **Hindi (`language: hi`)**, so it speaks English with
an Indian accent. Kept as chosen; warm US-English Sonic 3.5 alternatives, verified in
Vapi's Cartesia voice library, are:
- Iris - Friendly Specialist: `c894559e-d529-4d70-a6fb-3330ecf7ef6b`
- Jacqueline - Reassuring Agent: `9626c31c-bec5-4cca-baa8-f8ba9e84c8bc`
- Katie - Friendly Fixer: `f786b574-daa5-4673-aa0c-cbe3e8534c02`

**Rollback without a code change.** `VAPI_TRANSCRIBER_OVERRIDE`, `VAPI_MODEL_OVERRIDE` and
`VAPI_VOICE_OVERRIDE` (JSON objects) are applied by `scripts/sync_vapi.py`. Transcriber and
voice are replaced wholesale because their fields differ per provider. Model is merged, so
the prompt, tools and temperature are kept. For example, to restore the Batch 5 stack:
```
VAPI_TRANSCRIBER_OVERRIDE={"provider":"deepgram","model":"nova-3","language":"multi","smartFormat":true,"numerals":true}
VAPI_MODEL_OVERRIDE={"model":"gpt-4o-mini"}
VAPI_VOICE_OVERRIDE={"provider":"openai","voiceId":"alloy","model":"gpt-4o-mini-tts"}
```
Then run `make sync-vapi`. `--dry-run` prints a field-level diff against the live
assistant first.

**Rejected alternatives**
- *Deepgram nova-3 `multi` + OpenAI `gpt-4o-mini` + OpenAI `alloy`* (the Batch 5 stack).
  It supports mid-call Spanish, but live calls sounded more robotic and handled the
  multi-step flow less reliably than `gpt-4.1`.
- *`gpt-4o-mini` with the new transcriber and voice*: cheaper, but tool-chain reliability
  is what matters most here.
- *AssemblyAI `universal-streaming-multilingual`*: would keep Spanish, but was not the
  choice made. It is the first thing to try if Spanish support comes back.
- *A separate Spanish assistant*: out of scope for now.

**Trade-off: mid-call Spanish is no longer supported.** The English-only transcriber
cannot transcribe Spanish, so the prompt's language-switch behavior will not work
reliably. See README "Known limitations".

### Original Batch 5 choices (superseded, kept for history)

Deepgram `nova-3` with `language: multi` (code-switching English/Spanish), `numerals`,
`smartFormat` and `keyterm` prompting; OpenAI `gpt-4o-mini` at temperature 0.3; OpenAI
`alloy` voice on `gpt-4o-mini-tts`. That voice was chosen then because it is enum-confirmed
and natively multilingual, and no provider `voiceId` could be verified without a live
call.

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

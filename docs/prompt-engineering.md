# Prompt engineering

The annotated source is [`vapi/prompts/system_prompt.md`](../vapi/prompts/system_prompt.md)
— HTML comments in that file explain the *why* inline, section by section. This doc is the
higher-level design rationale; read the prompt itself for the letter of each rule.

## Persona

"Sarah" — a named, warm, efficient intake coordinator — instead of a generic "AI
assistant" persona. A stable, human-register voice makes short turns feel natural rather
than clipped, and gives the model somewhere to fall back to when a call goes off-script.
She never claims to be human (compliance/trust requirement, spec §1), but also doesn't
lead with "I am an AI" boilerplate — one honest sentence only if sincerely asked.

## One question at a time

The single highest-leverage rule in the prompt. Compound questions ("what's your address
and phone number?") are where LLM voice agents fail hardest — the caller answers half of
it, the model either re-asks the whole thing (annoying) or silently drops a field
(worse). One question per turn removes the failure mode instead of handling it after the
fact.

## Validation stays server-side

The model is explicitly told not to reject or accept a date of birth on its own
judgment — `validate_fields`, `create_patient`, and `update_patient` are the only source
of truth. Two reasons: LLMs are unreliable at date arithmetic (leap years, "today" drift
over a long call), and the spec requires server-side validation regardless of what the
voice agent does (spec §4: "do not rely solely on the voice agent"). The prompt's
`{{"now" | date: ...}}` date-awareness is for catching *implausible* input
conversationally ("that would make you 300 years old"), not for authority.

## Chunked read-back, not one wall of speech

Confirming ten-plus fields in one breath is unlistenable and impossible for a caller to
mentally check against. Splitting into three chunks (identity / contact+address /
optional) keeps each confirmation short enough to actually follow, and means a correction
only requires re-confirming one chunk, not the whole registration.

## Tool-result contract

Every tool returns a short prefixed string (`SAVED:`, `INVALID:`, `IDENTITY_MISMATCH`,
...) instead of structured data, and the prompt has a literal table mapping each prefix
to caller-facing behavior (see `docs/voice-tools.md` for the tool side of the same
contract). This is the one place code and prompt are tightly coupled by convention rather
than by schema — if a new prefix is ever added, both files need updating together.

## Corrections, interruptions, start-over

- **Corrections** ("actually it's D-A-V-I-S") are applied silently and confirmed back —
  no scolding, no "let me update that for you" ceremony.
- **Interruptions**: the prompt tells the model to stop, address what was said, then
  resume — this relies on Vapi's own turn-taking (`stopSpeakingPlan`), not prompt logic,
  for the interruption itself; the prompt only governs what happens *after*.
- **"Start over"** asks one confirmation before discarding everything, since it's a
  destructive action a caller might not have meant literally ("can we redo the address"
  vs. the whole call).

## Multilingual approach

A caller speaking Spanish (or saying "hablo español") flips the *entire* conversational
surface to Spanish — but tool arguments never translate. `sex` values stay the English
enum (`Male`/`Female`/`Other`/`Decline to Answer`) because that's what the database CHECK
constraint and `app/validation/demographics.py` expect; translating them would silently
break the save rather than just the transcript. Keeping the tool contract
language-invariant means Spanish support required zero changes to `app/voice/tools.py` —
only the prompt.

## Appointment offer (§3i)

Offered **once, only after a successful save**. Registration is what the caller called
for; if scheduling goes sideways, the registration is already safe. At most **two options
at a time**, because three or more spoken times are hard to hold in your head on a phone
call. Times are always said with "Eastern time", since callers may be in another zone.
Slot IDs are opaque and signed, so the model can only book times the server offered. On
`SLOT_TAKEN` the model apologizes lightly and offers the next option, not an error
message. On `BOOK_FAILED` it reassures the caller that the registration itself is saved.

## Known failure modes and mitigations

| Failure mode | Mitigation |
|---|---|
| Model asks a compound question anyway | "One question per turn" rule + low temperature (0.3) reduces drift from instructions |
| Model reads a tool's raw prefix/ID aloud | Explicit instruction + the result table is the only place prefixes appear in the prompt — never in example dialogue |
| Model calls `create_patient` before full confirmation | Step g is explicit: "only after they've explicitly confirmed everything" |
| Caller's spoken digits transcribed wrong (phone/ZIP) | `numerals: true` on the transcriber converts spoken digits to numerals before the model sees them; `validate_fields` catches what still slips through |
| Model cuts off a caller mid-spelling or mid-number | `startSpeakingPlan.transcriptionEndpointingPlan.onNumberSeconds` is tuned higher than punctuation/no-punctuation cases (see ADR 0006) |
| Model invents a field it never actually heard | Explicit guardrail: "never invent, assume, or guess" |
| Model invents or edits a slot time | `slot_id` is HMAC-signed; `book_appointment` rejects anything the server didn't issue |
| Model reads three-plus options in one breath | "At most two at a time" rule in §3i |

## How to iterate

1. Edit `vapi/prompts/system_prompt.md` directly — keep new rationale in HTML comments,
   new caller-facing behavior outside them.
2. `make sync-vapi-dry-run` to see the resolved (comment-stripped) prompt and confirm the
   diff is what you expect before touching the live assistant.
3. `make sync-vapi` to push it, then run a scenario from
   [`docs/test-call-script.md`](test-call-script.md) that exercises the changed behavior.
4. Check the call transcript and `call.analysis.summary` in the Vapi dashboard — the
   fastest way to see whether the model actually followed the new instruction, not just
   whether the prompt reads correctly to a human.

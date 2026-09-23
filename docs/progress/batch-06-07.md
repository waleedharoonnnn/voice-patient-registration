# Batch 6+7 report

## Scope

Call logs and transcripts, mock appointment scheduling (two new voice tools), the system
prompt's appointment flow, and the staff dashboard.

## Built

- **Migrations** `0002_create_call_logs`, `0003_create_providers_and_appointments`. These
  are new files; earlier migrations weren't edited. 0003 seeds 3 fake providers.
- **Call logs:** tool handlers record `registered`/`updated`/`failed`. The
  `end-of-call-report` adds the transcript, summary, timing and recording URL. Calls that
  never saved become `abandoned`, the follow-up queue for dropped connections. Payload
  fields were verified against Vapi's live OpenAPI spec.
- **Scheduling:** computed availability (Mon–Fri 9–5 ET, 30-min slots, 14 days) and
  HMAC-signed opaque `slot_id`s. A DB partial unique index prevents double booking.
  Bookings are idempotent per call. New tools `get_available_slots` and `book_appointment`,
  plus REST `GET /patients/{id}/appointments`, `/patients/{id}/calls`, `/providers`.
- **Prompt:** after a save, Sarah offers one appointment. She gives at most 2 options at a
  time, says "Eastern time", and handles SLOT_TAKEN, NO_SLOTS and BOOK_FAILED gracefully.
  The tool-result table is extended.
- **Dashboard:** server-rendered Jinja2 with one CSS file and zero JavaScript. It has
  stats, search, pagination, patient detail (grouped sections, appointments, call history
  with transcripts), and a calls page with an outcome filter and follow-up highlighting.
  Empty states and styled 401/404 pages. Security: Basic auth with constant-time compare,
  a strict CSP, `no-store`, `noindex`.
- **Docs:** ADRs 0007/0008/0009, data-model.md (with a Mermaid ERD), voice-tools.md,
  prompt-engineering.md, test-call-script.md (+4 scenarios), README (bonus features,
  dashboard, new endpoints).

## Decisions

- New deps: `jinja2` (dashboard rendering, no JS build step) and `tzdata`. On Windows and
  slim containers there's no IANA timezone database, so `zoneinfo` failed for
  `America/New_York`. Found through a 500 on the dashboard.
- Providers are seeded in the migration, not the seed script, because they're reference
  data the feature depends on.
- `slot_id` is signed with the existing `API_KEY`, so no new secret is needed.

## Bugs found and fixed while verifying

1. **Aborted transaction → 500 to Vapi.** A DB constraint error inside a tool (e.g.
   booking for a nonexistent patient) left the request's transaction aborted. The handler
   answered correctly, but the final commit failed. Fix: every repository write now runs
   in a savepoint. It's covered by `test_book_with_unknown_patient_never_raises` and by the
   concurrent-booking test.
2. **Missing timezone data** on Windows (see `tzdata` above).
3. **`preferred_date` would have been rejected as a "future date of birth"**, because it
   reused `parse_dob`. Split out `parse_calendar_date`.
4. The test cleanup fixture couldn't `TRUNCATE patients` once FKs existed. It now
   truncates dependents too.

## Verification (run directly)

| Check | Result |
|---|---|
| ruff / format / mypy (app) | clean |
| pytest | **267 passed**, 89% coverage on `app/`. Migrations 0001→0003 round trip passes |
| `alembic upgrade head` on Neon dev | at `0003 (head)`, 3 providers seeded |
| `make sync-vapi` + Vapi API GET | 7 tools attached incl. `get_available_slots`, `book_appointment`; prompt updated, comments stripped; phone number → Sarah |
| end-of-call-report via ngrok | 200, Neon row: `abandoned`, 72s, ended reason + summary stored |
| dashboard via ngrok | 401 without / with wrong creds; 200 with creds; CSP, `no-store`, `noindex` present; dropped call shown under "Needs follow-up" |

## Manual checks for you

Scenarios 15–18 in `docs/test-call-script.md` (book, slot taken, decline, dropped-call
follow-up), plus opening `/dashboard` in a browser to judge the look and feel.

## Open issues / risks

- **Neon dev had lost seed patient "Carlos"** (hard-deleted; our code only soft-deletes).
  I restored it with the idempotent seed script.
- One verification call log (`verify-b67-…`, abandoned, fake) is on Neon dev as a live
  example of the follow-up queue.
- `call_log_service.py` coverage is 63%: some update paths are only exercised through the
  webhook tests.
- Conversation-level automated evals are still blocked on the Vapi Chat API needing a card.

## Suggested commits

1. `feat: add call logs with end-of-call-report handling (migration 0002)`
2. `feat: add mock appointment scheduling, providers, and booking tools (migration 0003)`
3. `fix: run repository writes in savepoints so tool failures never 500 the webhook`
4. `feat: add appointment offer to system prompt and sync new tools`
5. `feat: add server-rendered staff dashboard`
6. `test: add call-log, scheduling, and dashboard tests`
7. `docs: add ADRs 0007-0009, ERD, and update README and voice docs`

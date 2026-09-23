# Voice AI Patient Registration Agent

CareCloud take-home assessment: a voice agent that collects US patient demographics over
a phone call, reads them back for confirmation, and saves them via a REST API backed by
Neon Postgres.

## Overview

Batch 1: FastAPI scaffold, config, logging, envelope, middleware, DB session, CI.
Batch 2: data layer — validators, `patients` table, migrations, seed script.
Batch 3+4: `/patients` REST API, service/repository layers, Vapi webhook with tool
handlers. Batch 5 (this state): the voice agent itself — system prompt, assistant config
as code, sync script. Still TBD: appointment scheduling, call transcripts/recordings
surfaced anywhere, dashboard.

## Live links

- Phone number: see Vapi dashboard (`VAPI_PHONE_NUMBER_ID` in `.env`)
- API base URL: `$PUBLIC_BASE_URL` (ngrok tunnel in dev; see below)
- Dashboard: TBD in later batch

## Architecture

See [`docs/adr/0002-layered-architecture.md`](docs/adr/0002-layered-architecture.md) for
the layering rationale. Summary:

```
app/
  main.py              # app factory: create_app(); wires routers, middleware, handlers
  core/                # config, logging, errors, security, request-id middleware
  db/                  # engine, session factory, Base
  models/              # SQLAlchemy models: patients
  schemas/             # Pydantic request/response models + envelope + patient schemas
  validation/          # pure, dependency-free validators
  repositories/        # DB access only: patient_repository
  services/            # business logic: patient_service (used by REST AND voice)
  api/
    deps.py            # shared dependencies (db session, X-API-Key auth)
    routers/           # health, patients, vapi (webhook); dashboard — TBD
  voice/               # Vapi payload parsing (schemas.py) + tool handlers (tools.py)
migrations/            # Alembic (0001_create_patients)
vapi/                  # assistant.json, prompts/system_prompt.md, tools/*.json
scripts/               # seed; sync_vapi (pushes vapi/ config to the Vapi API)
tests/unit/            # pure logic, no DB
tests/integration/     # API + DB against real Postgres
```

Dependency direction: `api`/`voice` -> `services` -> `repositories` -> `models`/`db`.

## Data model

See [`docs/data-model.md`](docs/data-model.md) for the full column/constraint table and
[`docs/adr/0003-patient-schema.md`](docs/adr/0003-patient-schema.md) for the reasoning
(soft delete, non-unique phone, UTC timestamps, DB constraints as defense in depth,
`source_call_id` idempotency, the future-DOB and `updated_at` triggers).

## Tech stack and justification

See [`docs/adr/0001-tech-stack.md`](docs/adr/0001-tech-stack.md).

## Setup

Prerequisites: [`uv`](https://docs.astral.sh/uv/), Docker (for local Postgres in tests).

```bash
uv sync                 # install runtime + dev dependencies
cp .env.example .env    # fill in local values
uv run uvicorn app.main:app --reload
```

Or via the Makefile: `make install`, `make run`.

## Environment variables

See [`.env.example`](.env.example) for the full list with placeholder values. Required
at startup: `API_KEY`, `VAPI_WEBHOOK_SECRET`, `DASHBOARD_USERNAME`, `DASHBOARD_PASSWORD`,
`DATABASE_URL`, `DATABASE_URL_DIRECT`. The app fails fast with a clear error if any
required setting is missing.

`TEST_DATABASE_URL` and `DB_SSL_REQUIRE=false` are only used by integration tests — they
point at the local Docker Compose Postgres (`db-up`), not Neon (which always needs SSL).
This machine's local Postgres services already occupy ports 5432-5434, so
`docker-compose.yml` publishes on **5544**.

`VAPI_TOOL_TIMEOUT_SECONDS` (default 8) and `VAPI_WEBHOOK_DB_STATEMENT_TIMEOUT_MS`
(default 5000) bound how long a voice tool call / its DB query may take, so a slow
backend never hangs a live call.

`PUBLIC_BASE_URL` and `VAPI_PHONE_NUMBER_ID` are only needed to run `make sync-vapi` —
`PUBLIC_BASE_URL` is wherever the webhook is actually reachable (an ngrok tunnel in dev).

## Database: migrations and seeding

```bash
make db-up        # start local Postgres (Docker Compose), for integration tests
make migrate       # uv run alembic upgrade head — applies migrations (uses DATABASE_URL_DIRECT)
make migration m="add_x"   # uv run alembic revision --autogenerate -m "add_x"
make seed          # insert 2 fake patients (idempotent; refuses on APP_ENV=prod without --force)
make db-down       # stop local Postgres
```

Migrations always run against `DATABASE_URL_DIRECT` (Neon's non-pooled endpoint), never
the pooled app URL — see `migrations/env.py`.

## API: `/patients`

All endpoints require `X-API-Key: $API_KEY` and return the envelope
`{"data": ..., "error": ...}`. Swagger UI (`/docs`) has an "Authorize" button wired to
the same key.

```bash
# Create
curl -s -X POST "$API_BASE/patients" -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" -d '{
  "first_name": "Jane", "last_name": "Doe", "date_of_birth": "06/15/1985", "sex": "Female",
  "phone_number": "(212) 555-0100", "address_line_1": "123 Main St", "city": "Springfield",
  "state": "IL", "zip_code": "62704"
}'

# List, with filters + pagination
curl -s "$API_BASE/patients?last_name=doe&limit=10&offset=0" -H "X-API-Key: $API_KEY"

# Get by id
curl -s "$API_BASE/patients/<patient_id>" -H "X-API-Key: $API_KEY"

# Partial update
curl -s -X PUT "$API_BASE/patients/<patient_id>" -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" -d '{"city": "Chicago"}'

# Soft delete
curl -s -X DELETE "$API_BASE/patients/<patient_id>" -H "X-API-Key: $API_KEY"
```

## Vapi webhook

`POST /vapi/webhook` — auth via `X-Vapi-Secret: $VAPI_WEBHOOK_SECRET` or
`Authorization: Bearer $VAPI_WEBHOOK_SECRET`. Handles Vapi's `tool-calls` server
messages; see [`docs/voice-tools.md`](docs/voice-tools.md) for each tool's contract and
[`docs/adr/0005-webhook-auth-and-idempotency.md`](docs/adr/0005-webhook-auth-and-idempotency.md)
for the auth/idempotency design. Tool JSON schemas: `vapi/tools/*.json` (not yet pushed
to a live Vapi assistant — that's a later batch).

```bash
curl -s -X POST "$API_BASE/vapi/webhook" -H "X-Vapi-Secret: $VAPI_WEBHOOK_SECRET" -H "Content-Type: application/json" -d '{
  "message": {"type": "tool-calls", "call": {"id": "demo-call-1"},
    "toolCallList": [{"id": "tc1", "function": {"name": "find_patient_by_phone", "arguments": {"phone_number": "2125550100"}}}]}
}'
```

## Voice agent

"Sarah" — see [`docs/prompt-engineering.md`](docs/prompt-engineering.md) for the design
rationale and [`docs/voice-tools.md`](docs/voice-tools.md) for the tool contract.
Config lives entirely as code under `vapi/`:

- `vapi/prompts/system_prompt.md` — the system prompt, annotated with HTML comments
  (stripped before upload).
- `vapi/assistant.json` — model/voice/transcriber/turn-taking/server config, with
  `$PUBLIC_BASE_URL` / `$VAPI_WEBHOOK_SECRET` placeholders and `$SYSTEM_PROMPT` /
  `$TOOL_IDS` sentinels resolved by the sync script.
- `vapi/tools/*.json` — the 4 tool schemas from Batch 3+4, unchanged.

Model/voice/transcriber choices and every Vapi field name are justified and
doc-URL-cited in
[`docs/adr/0006-voice-platform-and-model.md`](docs/adr/0006-voice-platform-and-model.md).

### Syncing to Vapi

```bash
make sync-vapi-dry-run   # print the resolved payload (secrets redacted) + diff, no API calls that mutate
make sync-vapi           # idempotent upsert: tools -> assistant -> phone number assignment
```

Safe to run repeatedly — matches existing tools by name/type and the assistant by name,
updating in place rather than creating duplicates. Writes `vapi/.sync-state.json`
(gitignored) with the resulting IDs.

### Testing via a call

Two terminals:

```bash
# Terminal 1
make run

# Terminal 2 — tunnel so Vapi can reach the local webhook
ngrok http --url=<your-ngrok-domain> 8000
```

Set `PUBLIC_BASE_URL` in `.env` to that ngrok domain, `make sync-vapi`, then in the Vapi
dashboard open the assistant and click **Talk to Assistant** for a free web call (or dial
the assigned phone number). Work through
[`docs/test-call-script.md`](docs/test-call-script.md) for specific scenarios. After each
call, check **Call Logs** in Vapi for the transcript/tool calls, and `GET /patients` to
confirm what was actually saved.

## How to test

```bash
make check   # ruff check, ruff format --check, mypy, pytest
```

Integration tests need the local Postgres running (`make db-up`); they apply migrations
automatically at the start of the test session and roll back (or truncate) between tests.

## Known limitations / trade-offs

- No appointment scheduling, dashboard UI, or surfaced call transcripts/recordings yet
  (scoped to later batches) — the appointment offer has a disabled placeholder section
  in the system prompt, ready for Batch 6.
- No retention/purge job for soft-deleted rows yet.
- Assistant-level silence-based auto-hangup and backchanneling aren't configured because
  they don't exist in Vapi's current API (confirmed against the live OpenAPI spec, not
  assumed) — silence handling is prompt-level only; see ADR 0006.
- `source_call_id` idempotency covers retries within one call, not a caller hanging up
  and calling back (see ADR 0005).

## Next steps

- Batch 6: end-of-call-report handling, call transcripts, appointment scheduling (mock
  data) — fills in the placeholder in `vapi/prompts/system_prompt.md`.
- Batch 7: dashboard.

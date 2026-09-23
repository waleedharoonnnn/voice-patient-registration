# Voice AI Patient Registration Agent

CareCloud take-home assessment: a voice agent that collects US patient demographics over
a phone call, reads them back for confirmation, and saves them via a REST API backed by
Neon Postgres.

## Overview

TBD in later batch (Vapi assistant + REST endpoints not yet implemented).

Batch 1 delivered the FastAPI scaffold, configuration, structured logging, the error
envelope, request middleware, the async DB session wiring, and CI. Batch 2 (this state)
adds the data layer: validators, the `patients` table, Alembic migrations, and a seed
script. There are still no `/patients` REST endpoints or Vapi integration.

## Live links

- Phone number: TBD in later batch
- API base URL: TBD in later batch
- Dashboard: TBD in later batch

## Architecture

See [`docs/adr/0002-layered-architecture.md`](docs/adr/0002-layered-architecture.md) for
the layering rationale. Summary:

```
app/
  main.py              # app factory: create_app(); wires routers, middleware, handlers
  core/                # config, logging, errors, security, request-id middleware
  db/                  # engine, session factory, Base
  models/              # SQLAlchemy models: patients (done)
  schemas/             # Pydantic request/response models + envelope
  validation/          # pure, dependency-free validators (done)
  repositories/        # DB access only — TBD
  services/            # business logic — TBD
  api/
    deps.py            # shared dependencies (db session, auth) — TBD
    routers/           # health (done), patients/vapi/dashboard — TBD
  voice/               # Vapi payload parsing + tool handlers — TBD
migrations/            # Alembic (done: 0001_create_patients)
vapi/                  # assistant config, system prompt, tool JSON schemas — TBD
scripts/               # seed (done), sync_vapi — TBD
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

`TEST_DATABASE_URL` is optional and only used by integration tests — it should point at
the local Docker Compose Postgres (`db-up`), not Neon. This machine's local Postgres
services already occupy ports 5432-5434, so `docker-compose.yml` publishes on **5544**.

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

## How to test

```bash
make check   # ruff check, ruff format --check, mypy, pytest
```

Integration tests need the local Postgres running (`make db-up`); they apply migrations
automatically at the start of the test session and roll back every test's changes.

curl examples and a call script: TBD in later batch (no `/patients` endpoints yet).

## Known limitations / trade-offs

- No `/patients` REST endpoints, Vapi integration, or dashboard UI yet (scoped to later
  batches).
- No retention/purge job for soft-deleted rows yet.
- Duplicate-patient detection (beyond the DB's supporting index) is not yet implemented —
  it belongs in the service layer, not scoped to this batch.

## Next steps

- Batch 3: `/patients` REST API, repositories, services.
- Batch 4: Vapi tool handlers, voice service integration, prompt docs.
- Batch 5: dashboard, `sync_vapi` script.

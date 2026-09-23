# Voice AI Patient Registration Agent

CareCloud take-home assessment: a voice agent that collects US patient demographics over
a phone call, reads them back for confirmation, and saves them via a REST API backed by
Neon Postgres.

## Overview

TBD in later batch (Vapi assistant + patient endpoints not yet implemented).

Batch 1 (this state) delivers the FastAPI scaffold, configuration, structured logging,
the error envelope, request middleware, the async DB session wiring (no models yet), and
CI.

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
  models/              # SQLAlchemy models (tables only, no business logic) — TBD
  schemas/             # Pydantic request/response models + envelope
  validation/          # pure, dependency-free validators — TBD
  repositories/        # DB access only — TBD
  services/            # business logic — TBD
  api/
    deps.py            # shared dependencies (db session, auth) — TBD
    routers/           # health (done), patients/vapi/dashboard — TBD
  voice/               # Vapi payload parsing + tool handlers — TBD
migrations/            # Alembic — TBD
vapi/                  # assistant config, system prompt, tool JSON schemas — TBD
scripts/               # seed, sync_vapi — TBD
tests/unit/            # pure logic, no DB
tests/integration/     # API + DB against real Postgres
```

Dependency direction: `api`/`voice` -> `services` -> `repositories` -> `models`/`db`.

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

## How to test

```bash
make check   # ruff check, ruff format --check, mypy, pytest
```

Local integration tests need Postgres: `docker compose up -d db`.

curl examples and a call script: TBD in later batch (no `/patients` endpoints yet).

## Known limitations / trade-offs

- No database models, migrations, patient endpoints, or Vapi integration yet
  (scoped to a later batch).
- No dashboard UI yet.

## Next steps

- Batch 2: SQLAlchemy models, Alembic migrations, `/patients` REST API, validators.
- Batch 3: Vapi tool handlers, voice service integration, prompt docs.
- Batch 4: dashboard, seed script, `sync_vapi` script.

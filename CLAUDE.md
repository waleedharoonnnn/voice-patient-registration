# CLAUDE.md — Engineering Contract for This Repository

This file is read by Claude Code at the start of every session. Every change in this
repo MUST follow it. If a request conflicts with this file, stop and ask.

## 1. Project

Voice AI patient-registration agent (CareCloud take-home assessment).

- Callers dial a US number (Vapi). A voice agent collects US patient demographics,
  reads them back, confirms, and saves them.
- A FastAPI backend exposes a REST API (`/patients`), receives Vapi tool-call and
  end-of-call webhooks, and serves a small read-only dashboard.
- Data lives in Neon Postgres.

The assessment document is the source of truth for requirements. When in doubt, re-read
it; do not invent requirements, and do not silently drop any.

## 2. Tech stack (fixed — do not substitute)

| Concern | Choice |
|---|---|
| Language | Python 3.12 |
| Package / env manager | `uv` (`pyproject.toml` + `uv.lock`, no `requirements.txt` except if a host needs one, generated from the lock) |
| Web framework | FastAPI |
| Validation / settings | Pydantic v2, `pydantic-settings` |
| ORM | SQLAlchemy 2.0 (async, typed `Mapped[...]` style) |
| DB driver | `asyncpg` |
| Migrations | Alembic (async env). Schema changes ONLY via migrations. Never `create_all()` outside tests. |
| Database | Neon Postgres (prod/dev branches); local Postgres via Docker Compose for tests |
| Voice platform | Vapi (assistant + tools configured as code under `vapi/`) |
| Rate limiting | `slowapi` |
| Logging | stdlib `logging` with a JSON formatter to stdout |
| Tests | `pytest`, `pytest-asyncio`, `httpx.AsyncClient` |
| Lint / format / types | `ruff` (lint + format), `mypy --strict` on `app/` |
| Hooks / CI | `pre-commit`, GitHub Actions |

## 3. Architecture and layering

```
app/
  main.py              # app factory: create_app(); wires routers, middleware, handlers
  core/                # config, logging, errors, security, request-id middleware
  db/                  # engine, session factory, Base
  models/              # SQLAlchemy models (tables only, no business logic)
  schemas/             # Pydantic request/response models + envelope
  validation/          # pure, dependency-free validators (US states, phone, ZIP, names, DOB)
  repositories/        # DB access only; no HTTP, no business rules
  services/            # business logic; the ONLY layer both REST and voice call into
  api/
    deps.py            # shared dependencies (db session, auth)
    routers/           # health, patients, vapi (webhooks), dashboard
  voice/               # Vapi payload parsing + tool handlers (thin; delegate to services)
migrations/            # Alembic
vapi/                  # assistant config, system prompt, tool JSON schemas (versioned)
scripts/               # seed, sync_vapi (push assistant config to Vapi via API)
tests/unit/            # pure logic, no DB
tests/integration/     # API + DB against real Postgres
docs/                  # architecture.md, prompt-engineering.md, adr/NNNN-title.md
```

Rules:
- Dependency direction: `api`/`voice` → `services` → `repositories` → `models`/`db`.
  Never skip a layer. Never import upward.
- Routers and voice handlers contain no business logic and no SQL.
- The voice agent persists data by calling the **service layer directly** (permitted by
  the spec), never by HTTP-calling our own API.
- Validation rules live once in `app/validation/` and are reused by Pydantic schemas,
  services, and voice tool handlers. The database also enforces them with CHECK
  constraints (defense in depth).

## 4. API contract

- Every response (success or error) uses the envelope:
  `{"data": <object|list|null>, "error": null | {"code": str, "message": str, "details": any}}`
- Status codes: 200 OK, 201 Created, 400 malformed request, 401 missing/invalid API key,
  404 not found, 422 validation failure, 429 rate limited, 500 unexpected (generic message,
  never a stack trace).
- Global exception handlers convert ALL errors (including FastAPI/Pydantic
  `RequestValidationError` and `HTTPException`) into the envelope.
- `DELETE` is a soft delete (`deleted_at`). Soft-deleted rows are excluded from all reads
  and from duplicate detection.
- `PUT` supports partial updates; unspecified fields are unchanged; `updated_at` changes.
- IDs are UUIDs; malformed UUID in a path → 404 or 422, never 500.

## 5. Data conventions

- Timestamps: `timestamptz`, stored and returned in UTC, ISO 8601.
- Phone numbers: stored normalized as exactly 10 digits (NANP: area code and exchange
  start with 2–9). Accept common spoken/written formats on input and normalize.
- `date_of_birth`: `date` type; not in the future; not before 1900-01-01.
  API accepts `MM/DD/YYYY` (spec) and ISO `YYYY-MM-DD`; responses use ISO. Document this.
- `state`: uppercase 2-letter USPS code from an explicit allow-list (50 states + DC + territories).
- `zip_code`: `^\d{5}(-\d{4})?$`.
- `sex`: one of `Male`, `Female`, `Other`, `Decline to Answer`.
- Names: 1–50 chars, letters (including accented letters), spaces, hyphens, apostrophes.
- Strings are trimmed; empty optional strings become `NULL`.
- `patient_id` default `gen_random_uuid()`; `updated_at` maintained by a DB trigger.

## 6. Security (non-negotiable)

- No secrets in code, tests, fixtures, docs, or commits. All config via environment
  variables loaded by `app/core/config.py`. Keep `.env.example` up to date (names only,
  placeholder values).
- `/patients*` requires `X-API-Key` (constant-time comparison).
- Vapi webhooks require the shared secret header Vapi sends (constant-time comparison);
  reject otherwise with 401.
- Dashboard is protected (HTTP Basic or API key) — it shows PII.
- Parameterized queries only (ORM / bound params). No string-built SQL.
- Rate-limit public endpoints. Restrictive CORS (explicit origins from config).
- Security headers middleware (no-sniff, frame-deny, referrer-policy).
- Never log secrets. PII logging is controlled by a config flag (see §7).
- No real patient data anywhere — seeds and tests use obviously fake data.

## 7. Observability

- JSON logs to stdout, one event per line, with `request_id` (and `call_id` for voice).
- Every request logged: method, path, status, duration_ms (no bodies).
- Voice: log each tool call (name, outcome, duration) and the **final collected patient
  payload** at completion (required by the spec). Full PII in logs only when
  `LOG_PII=true`; otherwise masked (e.g. phone `***-***-1234`).
- `GET /health` (liveness) and `GET /health/ready` (checks DB connectivity).

## 8. Reliability

- DB sessions: one per request, via dependency; commit/rollback handled centrally.
- Pool settings configurable; `pool_pre_ping=True`. Neon pooled endpoints use PgBouncer
  transaction mode, so asyncpg must use `statement_cache_size=0` (and no prepared-statement
  cache); Alembic uses the direct (non-pooled) URL. asyncpg takes SSL via
  `connect_args={"ssl": "require"}`, not a `sslmode` URL parameter.
- Voice tool calls must be idempotent: the Vapi `call.id` is stored on the patient
  (`source_call_id`, unique) so a retried "create" returns the existing record.
- Voice tool handlers NEVER raise to Vapi: they always return a short, speakable
  result string (success, validation problem with field name, or friendly failure) so the
  caller never hears silence.
- Timeouts on all outbound HTTP (e.g. Vapi API in scripts).

## 9. Code style

- Type hints everywhere; `mypy --strict` must pass on `app/`.
- `ruff` clean; line length 100.
- Small functions, clear names, docstrings on public functions/classes explaining *why*
  where not obvious. No commented-out code. No `print`.
- No new dependencies without stating why in the PR/commit message.
- Prefer explicit over clever.

## 10. Testing

- Every endpoint: happy path + validation failure + not-found + auth failure.
- Every validator: unit tests with valid, invalid and edge cases (leap day, today, future
  date, ZIP+4, lowercase state, phone with +1/dashes/spaces).
- Voice tool handlers: tested with recorded-shape Vapi payloads (no network).
- Integration tests run against real Postgres (Docker Compose locally, service container
  in CI), with migrations applied — not `create_all()` unless explicitly justified.
- A change is done only when `ruff`, `mypy`, and `pytest` all pass.

## 11. Documentation

- `README.md`: overview, live links (number, API base URL, dashboard), architecture,
  tech-stack justification, setup, env vars, how to test (curl examples + call script),
  known limitations/trade-offs, next steps.
- `docs/adr/`: one short ADR per significant decision (context, decision, consequences).
- `docs/prompt-engineering.md`: explains the system prompt section by section.
- The system prompt in `vapi/` is commented/annotated and versioned.
- Update docs in the same change that alters behavior.

## 12. Git

- Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`, `chore:`, `refactor:`).
- One logical change per commit. Never commit `.env`.

## 13. How to work in this repo (for Claude)

- Before coding: restate the task, list files you will create/change, flag any ambiguity.
- After coding: run `uv run ruff check . && uv run ruff format --check . && uv run mypy app && uv run pytest`
  and report results honestly. Do not claim success on failing checks.
- Do not modify files outside the task's scope. Do not weaken tests to make them pass.
- End with a short summary: what changed, how to verify, anything left open.

## 14. Batch reports

At the end of every batch, run ALL verification yourself (do not ask the user to run commands
you can run), then write `docs/progress/batch-NN.md` and print it in full, in this format:
- Batch / scope
- Files created / changed
- Decisions made (and why) + any deviation from CLAUDE.md
- Verification: each command run, and its real result (pass/fail, counts)
- Manual checks the user must do (only things you cannot do yourself, e.g. UI in a browser)
- Open issues / risks
- Suggested commit message(s)

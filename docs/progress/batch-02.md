# Batch 2 report

## Batch / scope

Data layer for patients: pure validators, the `patients` SQLAlchemy model, an Alembic
async migration (`0001_create_patients`) with CHECK constraints, triggers, and indexes,
an idempotent seed script, unit tests for every validator, and integration tests against
real Postgres. Explicitly out of scope (per the batch instructions): REST endpoints, the
service layer, and Vapi code.

## Files created / changed

**Validators** (`app/validation/`, all new)
- `names.py`, `phone.py`, `dates.py`, `address.py`, `demographics.py`, `email.py`,
  `insurance.py`

**Model / DB**
- `app/models/patient.py` (new) — the `patients` table
- `app/models/__init__.py` (changed) — imports `Patient` so Alembic autogenerate sees it
- `app/db/base.py` (changed) — added a naming convention to `Base.metadata` for
  deterministic constraint names
- `app/core/config.py` (changed) — added optional `TEST_DATABASE_URL`

**Alembic** (new)
- `alembic.ini`, `migrations/env.py` (async, reads `DATABASE_URL_DIRECT`, falls back
  only if no URL was pre-set — see Decisions), `migrations/script.py.mako`,
  `migrations/README`, `migrations/versions/0001_create_patients.py`

**Seed**
- `scripts/seed.py` (new), `scripts/__init__.py` (new)

**Tests**
- `tests/unit/validation/` (new) — 113 tests, one file per validator module
- `tests/integration/conftest.py` (new) — session-scoped migration fixture,
  per-test transaction-rollback `db_conn` fixture
- `tests/integration/test_patient_schema.py` (new) — 11 tests
- `tests/conftest.py` (changed) — added `TEST_DATABASE_URL` to the shared test env

**Docs**
- `docs/adr/0003-patient-schema.md` (new), `docs/data-model.md` (new)
- `README.md` (changed) — data model section, migration/seed commands, port note
- `CLAUDE.md` (changed, prior commit) — added §14 batch report protocol

**Infra**
- `docker-compose.yml` (changed) — host port 5432 → **5544**
- `.github/workflows/ci.yml` (changed) — added `TEST_DATABASE_URL`, Postgres service
  port → 5544
- `Makefile` (changed) — added `migrate`, `migration`, `seed`, `db-up`, `db-down`
- `.env.example` / `.env` (changed) — added `TEST_DATABASE_URL`
- `pyproject.toml` / `uv.lock` (changed) — added `email-validator` dependency

## Decisions made (and why) + deviations from CLAUDE.md

- **`email-validator` added as a runtime dependency.** Required by pydantic's
  `EmailStr`. RFC 5322 email validation has enough edge cases (quoted locals, IDN
  domains) that a maintained library beats a hand-rolled regex. Stated per CLAUDE.md §9.

- **Docker Compose Postgres moved from port 5432 to 5544.** This dev machine has *two*
  native Postgres services already bound to 5432 and 5433 (common when multiple Postgres
  versions are installed locally). They silently intercepted connections meant for the
  container — `psql` via `docker exec` worked, but any TCP client on the host got
  `InvalidPasswordError` because it was talking to the wrong server. Confirmed via
  `netstat`/`Get-Process`. Picked 5544 after confirming it was free. This is a deviation
  from the batch prompt's implicit "just use 5432" default, but not from CLAUDE.md
  itself. Updated everywhere the port is referenced: `docker-compose.yml`, `.env`,
  `.env.example`, `tests/conftest.py`, `.github/workflows/ci.yml`.

- **`migrations/env.py` only falls back to `Settings.DATABASE_URL_DIRECT` if no URL was
  already set on the Alembic `Config`.** This lets the integration test fixture (and any
  future script) point Alembic at a different database (the local Docker Postgres)
  without touching production config, while `alembic upgrade head` from the CLI with no
  override still safely defaults to `DATABASE_URL_DIRECT` per CLAUDE.md §8.

- **Integration test isolation uses a fresh `AsyncEngine` per test, not a session-scoped
  one.** Initially tried a session-scoped engine (reused across tests) for efficiency,
  but pytest-asyncio's per-test event loop by default meant asyncpg connections created
  under one test's loop were reused by a later test with a *different* loop, raising
  `RuntimeError: ... attached to a different loop` and `InterfaceError: another operation
  is in progress`. Session-scoped event loops (`loop_scope="session"`) were tried but
  interacted badly with `asyncio_mode = "auto"`. A fresh engine per test (disposed
  immediately after) is simpler, fully avoids the cross-loop problem, and the cost is
  negligible for this test count (11 tests, ~2s total).

- **`updated_at` trigger uses `clock_timestamp()`, not `now()`.** Found via a failing
  test: Postgres's `now()`/`CURRENT_TIMESTAMP` return the *transaction's* start time,
  frozen for the whole transaction — an insert and a later update in the same transaction
  (exactly what the per-test rollback fixture does) got byte-identical `updated_at`
  values. `clock_timestamp()` returns true wall-clock time at each call, which is also
  the more correct semantics for an audit column regardless of transaction length. This
  changes the behavior described implicitly by "the DB also enforces them" in CLAUDE.md
  §5 — worth flagging as a deliberate correction, not an oversight.

- **The model's `_NAME_PATTERN` used inside the CHECK constraint doubles the literal
  apostrophe (`''`) instead of using `'`.** The pattern (matching `app.validation.names`)
  allows apostrophes in names (`O'Brien`). Embedded verbatim into a single-quoted SQL
  string, an unescaped `'` would terminate the string early and produce invalid DDL. This
  was caught before ever running the migration, by inspecting the autogenerated SQL, and
  verified against real Neon with a literal `O'Brien` insert (see Verification).

- **Patient schema fields beyond the ones CLAUDE.md names explicitly** (email, address
  lines, insurance provider/member ID, emergency contact) were inferred from a standard
  patient-registration intake, since the assessment document itself wasn't available to
  this session — CLAUDE.md says to re-read the source spec when in doubt, but it wasn't
  provided as a file I could read. Flagging this as a risk (see below) rather than
  silently guessing without saying so.

- **Seed data uses fixed UUIDs and upserts on `patient_id`** for idempotency, using the
  555-01XX fictional exchange range required for phone numbers in tests/seeds.

## Verification

All commands run from the repo root; Neon dev = the branch configured in `.env`
(`DATABASE_URL_DIRECT`); local test DB = Docker Compose Postgres on port 5544.

| Command | Result |
|---|---|
| `docker compose up -d` (after fixing the port) | Container healthy: `Up ... (healthy)`, `0.0.0.0:5544->5432/tcp` |
| `uv run alembic upgrade head` (against Neon dev) | `Running upgrade -> 0001, create_patients` — succeeded |
| `uv run alembic downgrade base` then `upgrade head` (round trip, both against Neon dev and via the `test_migration_round_trip` integration test against local Postgres) | succeeded both times, no manual intervention |
| Manual insert of `O'Brien` against Neon dev, raw SQL | succeeded, confirms the CHECK constraint regex escaping is correct |
| Manual insert with `date_of_birth = 2099-01-01` against Neon dev | rejected: `RaiseError: date_of_birth cannot be in the future` (trigger fired) |
| Manual `UPDATE ... SET city` after insert, 1.1s apart, against Neon dev | `created_at` unchanged, `updated_at` changed (confirms trigger before the `clock_timestamp()` fix was even needed at real time granularity; the integration test caught the same-transaction edge case) |
| `uv run python -m scripts.seed` run twice against Neon dev | both runs: `Seeded 2 patient(s).`; direct query after: `row count: 2` (Jane Doe, Carlos O'Rourke-Martinez) |
| `APP_ENV=prod uv run python -m scripts.seed` (no `--force`) | refused: `Refusing to seed: APP_ENV=prod. Pass --force to override.`, exit code 1 |
| `uv run ruff check .` | `All checks passed!` |
| `uv run ruff format --check .` | `57 files already formatted` |
| `uv run mypy app` | `Success: no issues found in 29 source files` |
| `uv run pytest` (full suite) | **148 passed**, 0 failed (24 batch-1 + 113 validator unit + 11 integration) |
| `uv run pytest --cov=app.validation --cov-report=term-missing tests/unit/validation/` | **100% coverage**, 107/107 statements, 0 missing, across all 7 validator modules |

## Manual checks the user must do

- None required to confirm this batch works — everything above was run and verified by
  me against both Neon dev and local Postgres. The only thing worth a human glance:
  **the patient schema's field list** (email, address lines, insurance fields, emergency
  contact) was inferred rather than taken from the assessment document, since I don't
  have access to it in this session. If the actual assessment specifies different or
  additional fields, tell me and I'll adjust the model/migration before Batch 3 builds
  the REST API on top of it.

## Open issues / risks

- **Patient field list is inferred, not spec-verified** (see Decisions). Low risk to fix
  now (one more migration) but higher cost once the REST API and Vapi tool schemas are
  built on top of it in later batches.
- **No duplicate-patient detection logic yet** — the DB only provides the supporting
  partial index on `phone_number`; the actual "is this the same patient calling again?"
  heuristic is a service-layer decision, explicitly deferred.
- **No retention/purge job for soft-deleted rows** — noted in the README as a known
  limitation, not addressed in this batch.
- **This dev machine's port 5432/5433 conflict is local-environment-specific** — CI and
  other machines won't have it, but if another developer's machine also has a local
  Postgres on 5544 (unlikely but possible), `docker-compose.yml`'s port would need
  another change. Documented in the README and in a code comment.

## Suggested commit message(s)

Two logical commits (validators+model+migration is one coherent change; seed+tests+docs
could be split further, but they're all exercising/documenting the same schema so I'd
keep them together):

1. `feat: add patient validators, model, and Alembic migration`
2. `test: add validator and patient-schema integration tests, seed script, and docs`

(CLAUDE.md's own protocol update was already committed separately per the batch
instructions: `docs: add batch report protocol`.)

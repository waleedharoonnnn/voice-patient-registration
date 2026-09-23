# Batch 3+4 report

## Scope

Service layer, `/patients` REST API, and the Vapi webhook with 4 tool handlers. Not
built (per instructions): system prompt, assistant config, appointments, transcripts,
dashboard.

## Files created

- `app/schemas/patient.py` — PatientCreate/Update/Out/ListQuery/ListOut
- `app/repositories/patient_repository.py`, `app/services/patient_service.py`
- `app/api/deps.py` (X-API-Key auth), `app/api/routers/patients.py`, `app/api/routers/vapi.py`
- `app/voice/schemas.py` (tolerant Vapi payload models), `app/voice/tools.py` (4 handlers)
- `vapi/tools/*.json` (OpenAI function schemas, not pushed to Vapi yet)
- Tests: `test_patients_api.py` (26), `test_vapi_webhook.py` (18), `test_patient_service.py` (11)
- `tests/fixtures/vapi/*.json`
- `docs/adr/0004-voice-calls-service-layer.md`, `0005-webhook-auth-and-idempotency.md`, `docs/voice-tools.md`

## Files changed

- `app/db/session.py`, `app/core/config.py` — `DB_SSL_REQUIRE` (Neon needs SSL, local
  Docker Postgres doesn't), `get_webhook_db` (tight `statement_timeout`), tool-timeout setting
- `app/main.py` — wired `patients`/`vapi` routers
- `tests/conftest.py` — `app` fixture now disposes/clears the DB engine per test (see below)
- `tests/integration/conftest.py` — `clean_patients_table` fixture
- `tests/integration/test_health.py` — flipped to expect DB reachable (Docker Postgres is
  now actually running for integration tests, so "unreachable" was no longer true)
- README — API/webhook sections, env vars, limitations, next steps

## Notable bugs found and fixed during verification

1. **Engine cached across event loops.** `get_engine()` is `lru_cache`'d process-wide, but
   pytest-asyncio gives each test its own event loop — reusing pooled asyncpg connections
   across loops crashed. Fixed: `app` fixture disposes + clears the cache after each test.
2. **`PatientUpdate` field validators crashed on explicit `null`** for required fields
   (e.g. `{"first_name": null}` → `AttributeError`, not a clean 422). Fixed: all
   required-field validators now guard `v is not None`, letting the model-level
   `_reject_null_required_fields` validator produce the intended 422.
3. **`date_of_birth` list filter rejected MM/DD/YYYY.** FastAPI resolves a
   `Depends()`-model's fields using their own annotation *before* the model's own
   validators run, so a `date`-typed field only ever accepted ISO format. Fixed: the
   field is `str` in the schema; the router parses it via `parse_dob`.
4. **Local Docker Postgres unreachable via SSL.** The engine hardcoded `ssl="require"`
   (needed for Neon); local Postgres doesn't support it. Fixed with `DB_SSL_REQUIRE`.
5. **`validate_fields` tool argument shape.** Initial implementation treated the top-level
   arguments as the fields directly; spec's literal signature `validate_fields(fields:
   object)` wraps them under a `fields` key. Fixed to match, JSON schema written to match.

## Verification

- `ruff check` / `ruff format --check` / `mypy app`: all clean.
- `pytest`: **203 passed**, 90% coverage on `app/` (`voice/tools.py` at 68% — the
  untested lines are additional error-message formatting branches beyond the ones
  explicitly exercised by fixtures; core paths for all 4 tools are covered).
- Live against Neon dev via curl: create, list (last_name/date_of_birth/phone_number
  filters, including messy phone format and both date formats), get, partial update
  (confirmed `updated_at` changes), soft delete, confirmed excluded from list after
  delete, 401 without key, 422 on future DOB and invalid state.
- Live webhook call against Neon dev (`find_patient_by_phone`) returned the correct match.
- Confirmed Swagger `/docs` "Authorize" button is wired (`securitySchemes.APIKeyHeader`
  present, applied to `/patients` routes in the OpenAPI spec).
- Neon dev cleaned up: only the 2 seed rows (`Jane Doe`, `Carlos O'Rourke-Martinez`)
  remain active; the one test patient created during verification was soft-deleted.

## Open issues / risks

- No OpenAPI response examples (have tags/summaries/security scheme; examples skipped
  for time — low risk, cosmetic).
- `voice/tools.py` coverage is 68%, not 90%+ like the rest — remaining gaps are
  formatting-detail branches, not unexercised business logic.
- Duplicate-detection bonus behavior ("looks like we already have a record...") is only
  wired as a callable tool (`find_patient_by_phone`); the conversational flow that
  decides *when* to call it lives in the system prompt, not yet built.

## Suggested commits

1. `feat: add patient schemas, repository, and service layer`
2. `feat: add /patients REST API and Vapi webhook with tool handlers`
3. `test: add REST, webhook, and service unit tests`
4. `fix: dispose DB engine per test, fix null-required-field validation, fix DOB filter format, allow non-SSL local Postgres`
5. `docs: add ADRs 0004/0005, voice-tools.md, update README`

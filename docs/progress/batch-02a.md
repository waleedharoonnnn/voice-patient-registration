# Batch 2 amendment report

## Batch / scope

Audit the `patients` model, migration `0001`, validators, seed data, `docs/data-model.md`,
and ADR 0003 against `docs/assessment-spec.md` §2 (the newly-added source of truth), fix
any mismatches, and amend migration `0001` in place (nothing is deployed yet, so no new
migration was added).

## Mismatch table

| Spec field (§2) | Spec name | Found as | Verdict |
|---|---|---|---|
| Street address | `address_line_1` | `address_line1` | **Mismatch — fixed** |
| Apt/Suite/Unit | `address_line_2` | `address_line2` | **Mismatch — fixed** |
| `patient_id`, `first_name`, `last_name`, `date_of_birth`, `sex`, `phone_number`, `email`, `city`, `state`, `zip_code`, `insurance_provider`, `insurance_member_id`, `preferred_language`, `emergency_contact_name`, `emergency_contact_phone`, `created_at`, `updated_at` | — | matched exactly | No change — name, type, required/optional, and validation rule all match §2 |
| `deleted_at`, `source_call_id` | not in spec | present | Explicitly sanctioned by the spec ("Additional columns we add (justified in ADRs)") — no change |

Every other detail (types, required/optional, the `preferred_language` default, the
100-char length on address columns) already matched; the only defect was the missing
underscore before the line number in both address columns, everywhere they appear.

## Files changed

- `app/models/patient.py` — column names `address_line1`→`address_line_1`,
  `address_line2`→`address_line_2`; CHECK constraint name
  `address_line1_length`→`address_line_1_length`
- `migrations/versions/0001_create_patients.py` — amended in place (not a new revision):
  same two column names and the CHECK constraint name/expression
- `scripts/seed.py` — both seed records' dict keys renamed to match
- `tests/integration/test_patient_schema.py` — `_VALID_PATIENT` dict key renamed
- `docs/data-model.md` — column table updated
- `CLAUDE.md` — §1 now points to `docs/assessment-spec.md` as the requirements source of
  truth, to be read before every batch

No changes were needed in `docs/adr/0003-patient-schema.md` or `README.md` — neither
references the address column names directly.

## Verification

| Command | Result |
|---|---|
| `uv run alembic downgrade base` (Neon dev) | succeeded, before editing the migration |
| `uv run alembic upgrade head` (Neon dev, after the fix) | `Running upgrade -> 0001, create_patients` — succeeded |
| `uv run python -m scripts.seed` x2 (Neon dev) | both: `Seeded 2 patient(s).` |
| Direct query on Neon dev after reseeding | `row count: 2`; confirmed `address_line_1`/`address_line_2` values present and correct for both seed rows |
| `uv run ruff check .` | `All checks passed!` |
| `uv run ruff format --check .` | `59 files already formatted` |
| `uv run mypy app` | `Success: no issues found in 29 source files` |
| `uv run pytest` (full suite, local Docker Postgres on 5544) | **148 passed**, 0 failed |
| `uv run pytest --cov=app.validation --cov-report=term-missing tests/unit/validation/` | **100% coverage**, 107/107 statements |

## Manual checks the user must do

None — everything above was run and verified directly against both Neon dev and local
Postgres.

## Open issues / risks

None new. The risk flagged in the original batch-02 report (patient field list not
spec-verified) is now resolved — the schema matches `docs/assessment-spec.md` §2 exactly,
field for field.

## Suggested commit message(s)

1. `docs: point CLAUDE.md at docs/assessment-spec.md as requirements source of truth`
2. `fix: rename address_line1/2 to address_line_1/_2 to match assessment spec`

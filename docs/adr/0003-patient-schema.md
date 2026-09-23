# 0003 — Patient schema

## Status

Accepted.

## Context

The `patients` table is the one table in this system and it holds PII, so its schema
choices need explicit rationale rather than defaults. Batch 2 adds the table, its
validators, and its migration; this ADR records the decisions that aren't obvious from
reading the migration file alone.

## Decisions

**Soft delete (`deleted_at`), not hard delete.** CLAUDE.md §4 requires `DELETE` to be a
soft delete. Losing a patient record permanently on a single API call (or a caller
mis-hearing "delete" on a phone call) is a worse failure mode than an extra `WHERE
deleted_at IS NULL` in every read/duplicate-detection query. All reads and the phone
duplicate-detection index (`ix_patients_phone_number_active`) exclude soft-deleted rows.

**Timestamps are `timestamptz`, stored and read as UTC.** Callers may be in any US time
zone; storing local time would make "phone shared with another patient" duplicate checks
and audit ordering ambiguous across DST transitions. `created_at`/`updated_at` default to
`now()` (the transaction start time) at the database level — simpler and safer than
trusting the application clock, and consistent regardless of which layer (REST or voice)
performed the write.

**`phone_number` is NOT unique.** Families and households commonly share a landline or a
parent's cell number for a child's registration. A unique constraint would make the third
family member's registration fail outright. Instead, `ix_patients_phone_number_active`
(a partial index over non-deleted rows) exists purely to make duplicate-detection lookups
fast; actual duplicate handling is a service-layer decision (e.g. prompting the caller),
not a database constraint.

**Constraints exist at two layers on purpose.** `app/validation/` is the single source of
truth for each rule (phone format, state list, ZIP shape, name characters, DOB range,
sex values) and is what produces the caller-facing speakable error messages. The
database repeats the same rules as CHECK constraints. This is deliberate defense in
depth: the voice and REST paths both go through `app/validation/`, but a future bug, a
manual `psql` session, or a bypassed layer should still not be able to write invalid data.
The CHECK constraint regexes are generated from the same pattern strings the Python
validators use (see `app/models/patient.py`), so the two layers can't silently drift
apart from a typo.

**`source_call_id` and idempotency.** Vapi may retry a tool call (e.g. on a flaky
connection) without it being a real user intent to create a second patient. Storing the
`call.id` as a unique, nullable column lets the service layer look up "did this call
already create a patient?" before inserting, making voice-initiated creates idempotent
per CLAUDE.md §8. It's nullable because REST-created patients have no call id.

**A trigger enforces "date of birth not in the future," not a CHECK constraint.**
Postgres requires CHECK constraint expressions to be immutable; `CURRENT_DATE` is only
*stable* (constant within one statement, but not across statements/days), so Postgres
rejects a CHECK that references it directly. A `BEFORE INSERT OR UPDATE` trigger
(`reject_future_date_of_birth`) evaluates `CURRENT_DATE` at write time instead, which is
exactly the semantics needed ("not in the future *right now*"), and raises an exception
that the application layer translates into a validation error.

**`updated_at` is maintained by a trigger, not application code.** A `BEFORE UPDATE`
trigger (`set_updated_at`) sets `updated_at = clock_timestamp()` on every update,
regardless of which code path performed it. This guarantees the column is correct even
for a manual `UPDATE` run outside the application. `clock_timestamp()` is used instead of
`now()` deliberately: `now()`/`CURRENT_TIMESTAMP` return the *transaction's* start time
(frozen for the whole transaction), which would make two updates inside one transaction
get an identical `updated_at` — `clock_timestamp()` returns true wall-clock time at each
call.

## Consequences

- Every new validator added to `app/validation/` that has a DB-level equivalent must also
  update the CHECK constraints in a new migration, or the two layers drift.
- Because phone isn't unique, "is this a duplicate patient?" is necessarily a service-layer
  heuristic (e.g. phone + last name + DOB) rather than a database guarantee — to be defined
  when the service layer is built.
- Soft-deleted rows accumulate; a future retention/purge job is a known gap (see README
  known limitations).

# Requirements traceability

Every requirement in [`assessment-spec.md`](assessment-spec.md) is mapped to where it is
implemented and how it is verified. Status: ✅ Done · 🟡 Partial · ❌ Missing.
"Manual" means verified by live test calls using [`test-call-script.md`](test-call-script.md).
Automated conversation evals don't exist (Vapi's Chat API needs a paid plan; see Open items).

## 1. Telephony and voice agent

| Requirement | Implementation | Verification | Status |
|---|---|---|---|
| Real, dialable US number | Vapi number +1 732 782 5438, assigned by `scripts/sync_vapi.py` | `GET /phone-number` shows the assistant assigned; manual calls | ✅ |
| Natural, non-IVR conversation | `vapi/prompts/system_prompt.md` "How you speak", grouped questions (§b); GPT-4.1; Vapi smart endpointing ([ADR 0006](adr/0006-voice-platform-and-model.md)) | Manual (scripts 1–3) | ✅ |
| LLM handles phrasing, clarification, corrections | Prompt "Handling real conversations" (spelling, corrections, out-of-order answers) | Manual (scripts 4–6) | ✅ |
| Read back ALL info before saving | Prompt §f (three-chunk read-back) and §g (save only after explicit yes) | Manual | ✅ |
| Invalid data → re-prompt for that field | `validate_fields` tool → `INVALID: <field> …`; prompt §d | `test_validate_fields_invalid_phone`, `test_create_patient_invalid_returns_invalid_result`, validator unit tests | ✅ |
| Completion: "You're all set, [First Name]" and graceful end | Prompt §j + built-in `endCall` tool | Manual | ✅ |

## 2. Data model

| Requirement | Implementation | Verification | Status |
|---|---|---|---|
| All 19 fields, types, required/optional | `app/models/patient.py`, migration `0001`, [data-model.md](data-model.md) | `test_patient_schema.py`, `test_patients_api.py` | ✅ |
| Field rules (names, DOB not future / MM/DD/YYYY, sex enum, US phone, email, state, ZIP/ZIP+4, city 1–100) | `app/validation/*` (single source), used by Pydantic schemas and voice tools, plus DB CHECK constraints | `tests/unit/validation/*`, DB constraint tests | ✅ |
| Timestamps UTC, auto; `patient_id` UUID auto | `gen_random_uuid()`, `timestamptz`, `updated_at` trigger | `test_patient_id_and_timestamps_autogenerate`, `test_updated_at_changes_on_update_but_not_created_at` | ✅ |
| Optional fields offered, not forced | Prompt §e uses the spec's wording | Manual | ✅ |

## 3. Persistent database

| Requirement | Implementation | Verification | Status |
|---|---|---|---|
| Survives restarts; call 2 sees call 1 | Neon Postgres | Manual (script: second call, duplicate detection) | ✅ |
| Schema enforces the model | CHECK constraints, NOT NULLs, partial unique indexes | `test_patient_schema.py` | ✅ |
| 1–2 seed records | `scripts/seed.py` (idempotent, fake data) | `test_seed_script_is_idempotent` | ✅ |

## 4. REST API

| Requirement | Implementation | Verification | Status |
|---|---|---|---|
| GET /patients + `last_name` / `date_of_birth` / `phone_number` filters | `app/api/routers/patients.py` | `test_list_patients_*` | ✅ |
| GET /patients/:id | same | `test_get_patient_by_id`, `…_not_found`, `…_malformed_uuid_is_404_not_500` | ✅ |
| POST /patients returns record with `patient_id` | same | `test_create_patient_happy_path` | ✅ |
| PUT /patients/:id, partial | same | `test_update_patient_partial`, `…_changes_updated_at` | ✅ |
| DELETE soft-deletes | `deleted_at`; excluded from reads | `test_delete_patient_soft_deletes…`, `test_deleted_patient_hidden_*` | ✅ |
| Status codes 200/201/400/404/422/500 | `app/core/errors.py`. **Batch 8 fix:** malformed JSON returned 422, now 400 `malformed_request` | `test_create_patient_malformed_json_is_400`, `test_app_starts_and_degrades_when_db_is_unreachable` (500) | ✅ |
| Server-side validation | Pydantic schemas with max lengths, plus the service layer and DB constraints | validation-failure test per endpoint, `test_overlong_*` | ✅ |
| Envelope `{data, error}` everywhere | Global exception handlers; 413/429 middleware also return it | `test_errors.py`, `test_security.py` | ✅ |

## 5. Voice ↔ database

| Requirement | Implementation | Verification | Status |
|---|---|---|---|
| Persist via service layer | `app/voice/tools.py` → `PatientService` (no HTTP to self), [ADR 0004](adr/0004-voice-calls-service-layer.md) | `test_vapi_webhook.py` | ✅ |
| Create on confirmation | `create_patient` tool, idempotent per `call.id` | `test_create_patient_then_retry_same_call_id_is_idempotent` | ✅ |
| Relay success, or a graceful error if the write fails | `SAVED:` / `SAVE_FAILED:` results; the webhook never returns 5xx | `test_tool_handler_db_failure_returns_save_failed_with_200`, `test_resilience.py` | ✅ |

## Non-functional requirements

| Requirement | Implementation | Verification | Status |
|---|---|---|---|
| Deployed and callable at review time | Vercel (`iad1`), [ADR 0010](adr/0010-vercel-serverless-deployment.md), [deployment.md](deployment.md); Vapi webhook points at the Vercel URL | Live `/health/ready` 200, `/patients` 401 without a key, webhook secret accepted (200) | ✅ |
| Code quality | Layered architecture, ruff, mypy `--strict` | CI, `make check` | ✅ |
| README (setup, architecture, stack, env vars, limitations) | `README.md` | Commands run in Batch 8 | ✅ |
| Security: no hardcoded keys, env vars, input sanitization | `app/core/config.py`, validation, README "Security and privacy" | gitleaks (history), `test_security.py`, `test_route_auth.py` | ✅ |
| Log the final collected payload | `patient created` / `patient updated` events (PII masked unless `LOG_PII=true`) and a per-tool-call log | `test_logs_mask_pii_and_never_contain_secrets` | ✅ |

## Evaluation: edge cases and resilience

| Case | Implementation | Verification | Status |
|---|---|---|---|
| Invalid DOB | `validate_fields` / DOB validator → re-prompt | unit tests (future, today, leap day, pre-1900) | ✅ |
| Call drops mid-call | `end-of-call-report` → call log `abandoned`, nothing half-saved | `test_call_with_no_patient_is_marked_abandoned` | ✅ |
| DB write fails → spoken error, not silence | `SAVE_FAILED`, webhook-level fallback, 8 s tool timeout, 5 s statement timeout | `test_resilience.py`, `test_tool_handler_timeout_returns_friendly_result` | ✅ |
| Caller wants to start over | Prompt "Start over" (confirm once, then discard) | Manual | ✅ |

## Bonus

| Bonus | Implementation | Verification | Status |
|---|---|---|---|
| Duplicate by phone → offer update | `find_patient_by_phone`; DOB-verified `update_patient` | `test_update_patient_identity_mismatch`, `…_succeeds_with_correct_identity` | ✅ |
| Appointment scheduling (mock) | [ADR 0008](adr/0008-mock-appointment-scheduling.md); DB-enforced no double booking | `test_appointments.py` (incl. a concurrency race) | ✅ |
| Multi-language (Spanish) | Prompt "Language" section still there, but the English-only transcriber chosen in Batch 8 can't hear Spanish | Rollback via `VAPI_TRANSCRIBER_OVERRIDE` | 🟡 disabled by stack choice |
| Transcript/summary linked to patient | `call_logs`, [ADR 0007](adr/0007-call-logs-and-transcripts.md) | `test_call_logs.py`, `test_very_long_transcript_is_stored_intact` | ✅ |
| Dashboard | `/dashboard` (HTTP Basic), [ADR 0009](adr/0009-server-rendered-dashboard.md) | `test_dashboard.py` | ✅ |
| Automated API tests | `tests/` (unit + integration on real Postgres) | 308 tests, 90% coverage on `app/` | ✅ |

## Submission deliverables

| Item | Status |
|---|---|
| Repository URL, US phone number | ✅ in README Quick links |
| API base URL, dashboard URL | ✅ in README Quick links |
| Credentials / testing notes | ✅ notes; credentials sent outside the repo |
| "Next steps" in README | ✅ |

## Totals and open items

**43 requirements: 42 ✅ Done · 1 🟡 Partial · 0 ❌ Missing.** Fixed in Batch 8: 400 on
malformed JSON, rate limiting, body/field limits, the webhook's DB-down fallback, the
README rewrite and the Vercel deployment.

Partial:
1. **Spanish.** Turned off by the chosen English transcriber. Re-enable with
   `universal-streaming-multilingual` or Deepgram `multi` (ADR 0006).

Other open items:
- **No automated conversation eval** (`make eval`). Vapi's Chat API returned 402 (card
  required), so conversational criteria are verified manually.

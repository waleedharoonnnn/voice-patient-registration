# Voice tools

Handlers: `app/voice/tools.py` (8 tools). JSON schemas: `vapi/tools/*.json`
(pushed to Vapi by `make sync-vapi`). Never raise; every result is a short string the system
prompt can act on or speak. Result prefixes are the contract between code and prompt.

## `identify_caller()` — no arguments

Called once at the start of a call. Reads the caller ID from the webhook payload
(`message.customer.number`, falling back to `message.call.customer.number`). The model
never supplies it. **Returns no personal details**, because caller ID can be spoofed or
shared by a family.

- `NO_CALLER_ID`: web call, withheld number, or not a US number
- `NO_MATCH`: no active patient has this number
- `CALLER_ON_FILE`: at least one active patient has this number

## `verify_caller(date_of_birth: string)`

Caller ID plus the stated DOB. The DOB both proves identity and picks the right record
when several patients share a phone.

- `VERIFIED: patient_id=…; first_name=…; upcoming_appointments=<spoken times with doctor, " | "-separated, or none>`
- `IDENTITY_MISMATCH`: no patient on this number has that DOB (nothing revealed)
- `INVALID: date_of_birth: …`, or `NO_CALLER_ID`

After `VERIFIED`, the existing `update_patient` (DOB re-checked server-side) and
`book_appointment` tools are used with the returned `patient_id`.

## `validate_fields(fields: object)`

Validates any subset of patient fields with the same validators as the REST API, without
saving. Used mid-conversation to catch a bad field immediately.

- `VALID: field=value; ...` — or `VALID: (no fields provided)`
- `INVALID: field: reason; ...`

## `find_patient_by_phone(phone_number: string)`

Duplicate-detection lookup. Only ever returns name + id — never other PII.

- `NO_MATCH`
- `MATCH: patient_id=<id>; first_name=<>; last_name=<>` (up to 3, `; `-joined)
- `INVALID: phone_number: reason`

## `create_patient(<all spec fields>)`

Uses `message.call.id` as `source_call_id`: a retried call with the same call id returns
the existing record instead of creating a duplicate.

- `SAVED: patient_id=<id>; first_name=<>`
- `ALREADY_SAVED: patient_id=<id>; first_name=<>` (idempotent replay)
- `INVALID: field: reason; ...`
- `SAVE_FAILED: I'm having trouble saving right now.` (DB error, logged in full server-side)

## `update_patient(patient_id: string, date_of_birth: string, fields: object)`

Requires `date_of_birth` to match the stored record (identity check) before applying
`fields`.

- `UPDATED: patient_id=<id>; first_name=<>`
- `IDENTITY_MISMATCH` — patient exists, DOB doesn't match
- `NOT_FOUND` — no such patient (or malformed `patient_id`)
- `INVALID: field: reason; ...`
- `SAVE_FAILED: I'm having trouble saving right now.`

## `get_available_slots(preferred_date?: string, time_of_day?: morning|afternoon|any)`

Mock availability (see ADR 0008): Mon–Fri 9–5 Eastern, 30-minute slots, tomorrow through
14 days out, excluding booked times. `preferred_date` is MM/DD/YYYY.

- `SLOTS: 1) <slot_id> | Tuesday, October 6 at 10:30 AM Eastern with Dr. X; 2) ...` (up to 3)
- `NO_SLOTS`
- `INVALID: preferred_date|time_of_day: reason`

## `book_appointment(patient_id: string, slot_id: string, reason?: string)`

`slot_id` is signed. A tampered, malformed, or past slot is rejected before the DB is
touched. Idempotent per call.

- `BOOKED: appointment_id=<id>; time=<spoken time> Eastern`
- `SLOT_TAKEN`: someone else booked it first (the DB unique index decided). Offer another.
- `INVALID: slot_id|patient_id: reason`
- `BOOK_FAILED: I'm having trouble booking that right now.`

## Cross-cutting behavior

- **Timeout**: every handler runs under `asyncio.wait_for` (`VAPI_TOOL_TIMEOUT_SECONDS`,
  default 8s). On timeout: `SAVE_FAILED: That's taking longer than expected. Let's try again.`
- **Unknown tool name**: `SAVE_FAILED: I don't know how to do that yet.`
- **`arguments` as object or JSON string**: both accepted (`app/voice/schemas.py`).
- Every call is logged (tool name, call id, outcome, duration); errors log the full
  exception server-side but never leak DB detail into the result string.
- `create_patient` / `update_patient` also update the call log (`registered`, `updated`,
  or `failed`). A call-log write failure is logged and never changes what the caller hears.

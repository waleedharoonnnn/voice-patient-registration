# Assessment Specification (Source of Truth)

Transcribed from the CareCloud take-home assessment "Voice AI Agent — Patient Registration System".
All implementation decisions must trace back to this file. Do not add, drop or rename fields.

## 1. Telephony & Voice Agent

| Requirement | Details |
|---|---|
| Phone number | Real, dialable U.S. number via a telephony provider (we use Vapi). |
| Voice interaction | Natural conversational flow, not a rigid IVR. Should feel like a human intake coordinator. |
| LLM-powered | Understand varied phrasing, ask clarifying questions, handle corrections. |
| Confirmation | Before saving, read back ALL collected info and ask caller to confirm or correct any field. |
| Error handling | Invalid data (e.g. 3-digit phone, future DOB) → re-prompt specifically for that field. |
| Call completion | After success: brief confirmation (e.g. "You're all set, [First Name].") and end gracefully. |

## 2. Patient Demographic Data Model

| Field | Type | Validation Rules | Required |
|---|---|---|---|
| first_name | String | 1–50 chars, alphabetic + hyphens/apostrophes | Yes |
| last_name | String | 1–50 chars, alphabetic + hyphens/apostrophes | Yes |
| date_of_birth | Date | Valid date, not in future, MM/DD/YYYY | Yes |
| sex | Enum | Male, Female, Other, Decline to Answer | Yes |
| phone_number | String | Valid U.S. 10-digit phone number | Yes |
| email | String | Valid email format | No |
| address_line_1 | String | Street address | Yes |
| address_line_2 | String | Apt/Suite/Unit if applicable | No |
| city | String | 1–100 characters | Yes |
| state | String | Valid 2-letter U.S. state abbreviation | Yes |
| zip_code | String | 5-digit or ZIP+4 U.S. format | Yes |
| insurance_provider | String | Name of insurance company | No |
| insurance_member_id | String | Alphanumeric member/subscriber ID | No |
| preferred_language | String | Default: English | No |
| emergency_contact_name | String | Full name | No |
| emergency_contact_phone | String | Valid U.S. 10-digit phone number | No |
| created_at | Timestamp | Auto-generated at creation (UTC) | Auto |
| updated_at | Timestamp | Auto-generated on modification (UTC) | Auto |
| patient_id | UUID | Auto-generated unique identifier | Auto |

Additional columns we add (justified in ADRs): `deleted_at` (required by DELETE soft-delete in §4),
`source_call_id` (voice idempotency).

Conversational note: the agent does NOT need to ask every optional field. Collect required fields,
then offer: "I can also collect your insurance information, emergency contact, and preferred
language. Would you like to provide any of those?" — caller opts in.

## 3. Persistent Database

- Any relational/document DB (we use Neon Postgres).
- Data must survive server restarts ("Jane Doe" registered on Call 1 exists on Call 2).
- Schema must enforce the data model with proper column types and constraints.
- Optional: 1–2 seed patient records.

## 4. Web Service (REST API)

| Method | Endpoint | Description |
|---|---|---|
| GET | /patients | List all patients. Optional query params: ?last_name=, ?date_of_birth=, ?phone_number= |
| GET | /patients/:id | Retrieve one patient by patient_id (UUID) |
| POST | /patients | Create a patient. Returns created record with patient_id |
| PUT | /patients/:id | Update an existing patient. Partial updates allowed |
| DELETE | /patients/:id | Soft-delete (set deleted_at; do not hard-delete) |

API standards:
- Proper HTTP status codes (200, 201, 400, 404, 422, 500).
- Validate all inputs server-side (do not rely solely on the voice agent).
- Consistent JSON envelope: `{ "data": {...}, "error": null }`.

## 5. Voice Agent ↔ Database Integration

- Agent uses the REST API or directly invokes the same service layer to persist records.
- On caller confirmation → create the patient (POST /patients or equivalent DB write).
- Relay outcome to caller: success confirmation or graceful error if the write fails.
- Bonus: if caller's phone matches an existing patient, say: "It looks like we already have a
  record for [First Name] [Last Name]. Would you like to update your information instead?"

## Non-Functional Requirements

| Area | Expectation |
|---|---|
| Deployment | Running and callable at review time. Any hosting. |
| Code quality | Clean, readable, intentional structure. |
| README | Setup, architecture, tech-stack justification, env vars, known limitations/trade-offs. |
| Security | No hardcoded keys; env vars; basic input sanitization on the API. |
| Observability | Log agent conversations (at minimum the final collected data payload) to stdout or a log file. |

## Evaluation (20% each)

1. Working system — call and register end to end; data persisted and retrievable via API; second
   call without data loss.
2. Conversational quality — natural, not robotic; handles corrections (e.g. "my last name is
   spelled D-A-V-I-S, not D-A-V-I-E-S"); confirms before saving; handles interruptions and
   out-of-order responses.
3. Technical architecture — clear separation (telephony / LLM logic / data layer / API); good
   schema types and constraints; RESTful, validated endpoints; thoughtful, documented prompt
   engineering.
4. Code quality & documentation — organized, readable, consistent; complete, accurate README;
   trade-offs and limitations documented; system prompt included and commented.
5. Edge cases & resilience — invalid DOB; telephony connection drops mid-call; DB write fails
   (error, not silence); caller wants to start over mid-conversation.

## Bonus (all being implemented)

- Duplicate detection by phone → offer update instead of create.
- Appointment scheduling after registration (mock data fine).
- Multi-language: "Hablo español" → agent switches to Spanish.
- Call recording/transcript: store transcript or summary linked to the patient record.
- Dashboard: simple web UI showing registered patients (explicitly requested by the recruiter email).
- Automated tests for the API layer.

## Submission deliverables

Repository URL, U.S. phone number, API base URL, credentials/notes for testing, dashboard URL.
Include "Next Steps" in README for anything unfinished.

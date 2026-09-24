# Manual test call scenarios

Run via a Vapi web call ("Talk to Assistant" in the dashboard) or a real phone call to
the synced number. After each call: check **Call Logs** in Vapi for the transcript and
tool calls, and `GET /patients` (via `/docs`, with your `X-API-Key`) to confirm what was
actually saved.

| # | Scenario | Steps | Expected result |
|---|---|---|---|
| 1 | Happy path | Answer every question naturally with a fresh (unused) phone number, confirm the read-back | `create_patient` called once, `SAVED:` result, "You're all set, [name]", record visible in `GET /patients` |
| 2 | Correction | When asked to confirm the last name, say it's wrong and spell the correct one (e.g. "actually it's D-A-V-I-S") | Assistant updates silently, confirms the corrected spelling, saved record has the corrected name |
| 3 | Out-of-order info | Volunteer your address before being asked for it | Assistant doesn't re-ask for the address later |
| 4 | Future DOB | State a date of birth in the future | `validate_fields`/`create_patient` returns `INVALID:`, assistant re-asks only for DOB, explains briefly |
| 5 | 3-digit phone | State an obviously incomplete phone number | `INVALID:` on the phone field specifically, re-asked |
| 6 | Invalid state / ZIP | State a nonexistent state abbreviation or a 3-digit ZIP | `INVALID:` on that field, re-asked |
| 7 | Start over midway | After giving 3-4 fields, say "can we start over" | Assistant confirms once, then restarts from asking for your name; nothing from before persists in the eventual save |
| 8 | Interrupt the read-back | Talk over the assistant during the confirmation read-back | Assistant stops, addresses what you said, resumes the read-back |
| 9 | Duplicate caller | Call from (or spoof/pass) one of the **seed patients'** phone numbers (`212-555-0100` for Jane Doe) | `find_patient_by_phone` returns `MATCH:`; assistant asks "It looks like we already have a record for Jane Doe. Would you like to update your information instead?" |
| 10 | Update — correct DOB | Continue scenario 9, say yes, then state the correct DOB (`06/15/1985` for Jane Doe) | `update_patient` succeeds, `UPDATED:` result |
| 11 | Update — wrong DOB | Continue scenario 9, say yes, then state a DOB that doesn't match | `IDENTITY_MISMATCH`; assistant declines to update, asks to double check the date |
| 12 | Spanish call *(skip on the current English-only transcriber; see ADR 0006)* | Say "hablo español" (or start in Spanish) | Assistant switches fully to Spanish for the rest of the call; `sex` value saved is still the English enum word |
| 13 | Caller hangs up mid-call | Hang up partway through, before confirming the read-back | No `create_patient` call was made — confirm via `GET /patients` that nothing half-saved exists |
| 14 | DB failure | Stop the local DB (`make db-down`) or set an invalid `DATABASE_URL` and restart the server, then call | Assistant apologizes, retries once, then tells the caller plainly their info wasn't saved — never silence, never a false "you're all set" |
| 15 | Book an appointment | Finish scenario 1, say yes to scheduling, ask for "a morning next week", pick the first option | Two options offered at most, times said as "Eastern"; `book_appointment` → `BOOKED`; appointment shows on the patient's dashboard page |
| 16 | Slot taken | While on a call, book the offered slot for a different patient via a second call (or the webhook), then pick it on the first call | `SLOT_TAKEN`; Sarah apologizes lightly and offers another time |
| 17 | Decline scheduling | Finish scenario 1, say no to scheduling | No pressure, no second ask; "You're all set, [name]" and the call ends |
| 18 | Dropped call follow-up | Hang up mid-registration, then open `/dashboard/calls?outcome=abandoned` | The call shows as Abandoned / Needs follow-up with its transcript |

## Keeping calls short

Each call uses Vapi credits — the happy path (#1) takes about 3 minutes. For scenarios
that only need to reach one specific behavior (e.g. #4, #5, #6), hang up as soon as
you've confirmed the expected result rather than completing the full registration.

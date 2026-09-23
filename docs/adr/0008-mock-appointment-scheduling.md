# 0008 — Mock appointment scheduling

## Status

Accepted.

## Decisions

- **Availability is computed, not stored.** Slots are Mon–Fri, 9:00–17:00, every 30
  minutes, from tomorrow through the next 14 days, in `CLINIC_TIMEZONE`
  (America/New_York), for every active provider, minus `booked` rows. There's no slots
  table to seed or keep in sync.
- **The database prevents double booking, not the app.** A partial unique index
  `(provider_id, start_time) WHERE status = 'booked'` means two concurrent bookings can't
  both succeed. The loser gets a unique violation, which becomes `SLOT_TAKEN`. There's an
  integration test that races two real requests. Cancelled rows don't count, so a
  cancelled slot opens up again.
- **Opaque, signed `slot_id`.** It encodes `provider_id` and the UTC start time, signed with
  HMAC-SHA256 using the existing `API_KEY` as the key, then base64url-encoded. This needs no
  new secret and no lookup table. A tampered, malformed, or past slot is rejected before
  touching the DB. The model can't invent a bookable time.
- **Providers are seeded in migration 0003, not `scripts/seed.py`.** They're reference data
  the feature needs to work at all, like a lookup table, not optional demo data. Fixed
  UUIDs keep them stable across environments.
- **Idempotent per call.** `book_appointment` reuses `source_call_id`. A retried booking
  in the same call returns the existing appointment. Assumption: one appointment per
  registration call.
- **`zoneinfo` + `tzdata`.** Windows and slim containers have no IANA timezone database.
  `tzdata` (a pure-data package) provides it. This was found in testing: dashboard times
  failed on Windows without it.

## Consequences

- Availability ignores provider schedules, holidays and appointment length beyond 30
  minutes. That's acceptable for mock data, and a real system would swap in a schedule
  source behind the same service method.
- `slot_id` stops verifying if `API_KEY` rotates. Harmless, since slots only live for the
  length of a call.

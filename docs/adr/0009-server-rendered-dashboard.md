# 0009 — Server-rendered dashboard

## Status

Accepted.

## Decisions

- **Jinja2 templates rendered by FastAPI** (new dependency: `jinja2`). There's no JS
  framework, build step or second deployable, and it reuses the service layer directly:
  no SQL in routes, no extra API. One static CSS file with system fonts and no CDNs.
- **Security posture for pages that show PHI:**
  - HTTP Basic with `DASHBOARD_USERNAME`/`DASHBOARD_PASSWORD`. Both fields are always
    compared in constant time. A 401 comes back as a styled HTML page with
    `WWW-Authenticate`, so browsers show their login prompt.
  - `Content-Security-Policy: default-src 'none'; style-src 'self'; img-src 'self';
    form-action 'self'; base-uri 'none'; frame-ancestors 'none'`. No scripts can run at
    all, including inline. The templates contain no inline styles or scripts, and a test
    enforces that.
  - `Cache-Control: no-store` and `X-Robots-Tag: noindex` on every `/dashboard` response,
    including 401s and 404s.
  - Autoescaping is on. A test injects `<script>` into a transcript and summary and
    checks it comes out escaped.
  - Rate-limited by the app-wide slowapi default.
- **UX:** summary cards, search by last name, phone or DOB with friendly validation
  messages, pagination, and patient detail grouped by section. Call history uses outcome
  badges with text labels (not color alone) and transcripts in `<details>`. The follow-up
  queue highlights abandoned and failed calls. Empty states and styled 404/401 pages
  throughout. Semantic tables, labeled inputs, a skip link, and visible focus rings.
  Times are shown in Eastern Time and labeled "ET".

## Consequences

- Read-only by design. Editing patients stays in the API, where validation and auditing
  already live.
- Basic auth has no logout, lockout or per-user accounts. That's acceptable for a
  take-home demo, and the README lists it as a limitation.

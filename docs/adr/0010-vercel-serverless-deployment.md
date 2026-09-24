# 0010 — Deploy on Vercel (serverless Python)

## Status

Accepted. Supersedes the container-host plan in `docs/deployment.md` as the primary
target. The Dockerfile stays as the portable alternative.

## Context

The app needs a free, always-reachable HTTPS host so Vapi can call the webhook at review
time. Koyeb closed its free tier to new users. Vercel's Hobby plan runs FastAPI as a
single Vercel Function. Facts below were checked against the current Vercel docs and the
open-source Python builder (`vercel/vercel`, `packages/python`), not assumed.

## Decision

- **Entrypoint:** `app/main.py` exposes `app = create_app()`. `app/main.py` is a
  documented auto-detected entrypoint. No `tool.vercel.entrypoint` is needed.
- **Dependencies:** Vercel prefers `uv.lock` over every other manifest and installs with
  `uv sync --no-dev --locked`. **No `requirements.txt`**: it would be ignored while a lock
  exists. CI's `uv sync --locked` already fails if the lock drifts from `pyproject.toml`.
  `.python-version` is `3.12`: Vercel matches on major.minor, and a patch pin could make
  `uv sync` look for an interpreter it doesn't have.
- **`vercel.json`:**
  - Region `iad1`, next to Neon us-east and Vapi. Hobby allows one region.
  - `maxDuration: 30`. The Hobby maximum is 300 s. Voice tools already time out at 8 s,
    so 30 s is only a ceiling for slow REST calls.
  - `excludeFiles` drops tests, docs, scripts, migrations and `vapi/`. Nothing under
    `app/` is excluded.
- **Database:** `DB_POOL_MODE=null` gives SQLAlchemy `NullPool`: one connection per
  session, closed on release, so frozen or recycled instances never hold stale
  connections. Neon's pooled (PgBouncer) endpoint does the pooling, and
  `statement_cache_size=0` plus SSL are unchanged. `queue` (the default) is kept for
  local and Docker.
- **Static files:** `[tool.vercel.fastapi.static] cdn = false`, so `/static` goes through
  the function. CDN-promoted files would bypass our middleware, losing the security
  headers, request id and access log. The CSS is tiny, so there's no real cost.
- **Rate limiting:** counters stay in memory, so the limit applies per function
  instance. That still stops bursts at one instance but isn't global. The client key
  comes from `x-real-ip` (`RATE_LIMIT_CLIENT_IP_HEADER`), which Vercel overwrites on every
  request, so it can't be spoofed. Without it, every request would share the proxy's
  address. The header is ignored unless configured.
- **Lifespan:** no startup work, and nothing writes to disk (the filesystem is read-only
  apart from `/tmp`). Shutdown disposes the engine within 0.4 s, inside Vercel's 500 ms
  cleanup window.
- **Migrations** don't run on Vercel. They're applied from a checkout or CI against
  `DATABASE_URL_DIRECT` before promoting a deploy (see deployment.md).

## Consequences

- A cold start adds a new TLS connection to Neon on the first query of each request
  (roughly 10s of ms in `iad1`). Acceptable against voice-turn latency.
- **The per-instance rate limit is the main gap.** The fix is a shared store: point
  `limits` at Redis (e.g. Upstash, which has a free tier) via a storage URI. Not done
  now, to avoid adding an external dependency for a demo.
- Vercel's 4.5 MB body limit is above our 2 MB cap, so our 413 envelope still applies.

# Deployment

Provider-neutral: any host that runs a container and gives it a `$PORT` works (Render,
Fly.io, Railway, Cloud Run, a VM). Nothing is deployed yet. Live URLs in the README are
placeholders until then.

## The image

`Dockerfile` is a multi-stage build:
- `python:3.12-slim` base, with dependencies installed by `uv sync --locked --no-dev` from `uv.lock`.
- Runs as a non-root `app` user.
- `HEALTHCHECK` on `/health`, and binds `$PORT` (default 8000).
- `uvicorn` is PID 1, so SIGTERM triggers a graceful shutdown that disposes the DB pool.
- `.dockerignore` keeps `.env`, tests, docs and `.git` out of the image.

```bash
docker build -t voiceai .
docker run --env-file .env -e PORT=8765 -p 8765:8765 voiceai
curl localhost:8765/health/ready        # {"data":{"status":"ready"},...}
```

Tuning via env (read by uvicorn):

| Var | Default | Why |
|---|---|---|
| `WEB_CONCURRENCY` | `1` | Rate-limit counters live in process memory, so N workers allow N× the limit per IP. One async worker comfortably serves this workload. Scale out only after moving the limiter to a shared store (Redis). |
| `FORWARDED_ALLOW_IPS` | `*` | Trust the platform proxy's `X-Forwarded-For` so rate limiting and logs see real client IPs. Set it to the proxy's IP range if the container is ever reachable directly. |

## Migrations: a separate release step

Run migrations **once per deploy, before the new version takes traffic**, not on app
startup:

```bash
docker run --rm --env-file .env.prod voiceai alembic upgrade head
```

Why not on startup:
- With several instances, each would race to migrate.
- A failed migration would crash-loop the web process instead of failing the deploy.
- Migrations need the **direct** Neon URL (`DATABASE_URL_DIRECT`). PgBouncer transaction
  mode on the pooled URL breaks DDL.

Most hosts have a "release command" or "pre-deploy" hook for this (Render: Pre-Deploy
Command; Fly: `release_command`; Railway: pre-deploy). The image includes `migrations/`
and `alembic.ini`, so the same artifact runs both steps.

## Environment variables per environment

| Var | Local dev | Test / CI | Production |
|---|---|---|---|
| `APP_ENV` | `dev` | `test` | `prod` |
| `DATABASE_URL` | Neon **dev** branch, pooled | local Postgres :5544 | Neon **prod** branch, pooled |
| `DATABASE_URL_DIRECT` | Neon dev, direct | local Postgres | Neon prod, direct |
| `TEST_DATABASE_URL` | local :5544 | local :5544 | — |
| `DB_SSL_REQUIRE` | `true` | `false` | `true` |
| `API_KEY`, `VAPI_WEBHOOK_SECRET`, `DASHBOARD_PASSWORD` | own random values | dummy values | **new** random values (never reuse dev) |
| `DASHBOARD_USERNAME` | any | dummy | non-obvious name |
| `LOG_PII` | `false` (`true` only for local debugging) | `false` | `false` |
| `CORS_ORIGINS` | `http://localhost:3000` | — | exact origins of any browser client (none needed today) |
| `RATE_LIMIT_DEFAULT` | `60/minute` | high | `60/minute` |
| `ENABLE_API_DOCS` | `true` | `true` | `true` for reviewers, else `false` |
| `ENABLE_HSTS` | `false` | `false` | `true` (HTTPS only) |
| `MAX_REQUEST_BODY_BYTES` | `2000000` | default | `2000000` |
| `CLINIC_TIMEZONE` | `America/New_York` | default | clinic's zone |
| `VAPI_API_KEY`, `PUBLIC_BASE_URL`, `VAPI_PHONE_NUMBER_ID` | only on the machine running `make sync-vapi` | — | not needed by the web process |

The full list with descriptions is in `.env.example` and the README.

## Deploy checklist

1. `make check` is green, CI is green on `main`.
2. Create a Neon **prod** branch. Copy its pooled and direct URLs into the host's secret store.
3. Generate fresh secrets (`python -c "import secrets;print(secrets.token_urlsafe(32))"`)
   for `API_KEY`, `VAPI_WEBHOOK_SECRET` and `DASHBOARD_PASSWORD`. Set the remaining vars
   from the table above.
4. Point the host at the repo `Dockerfile`. Set the release command to
   `alembic upgrade head` and the health check path to `/health/ready`.
5. Deploy. Check `GET https://<host>/health/ready` → 200.
6. Optional: seed fake demo data. The seed script isn't in the image, so run it from a
   checkout with prod env vars: `uv run python -m scripts.seed`.
7. **Point Vapi at the new URL.** Locally, set `PUBLIC_BASE_URL=https://<host>` and
   `VAPI_WEBHOOK_SECRET=<prod value>`, then:
   ```bash
   make sync-vapi-dry-run   # expect: server.url and server.headers differ, nothing else
   make sync-vapi
   ```
8. Smoke test: one `curl` to `/patients` with the key, the dashboard login, and one real
   test call (scenario 1 in `docs/test-call-script.md`). Confirm the patient and call log
   appear.

## Rollback

- **App:** redeploy the previous image or commit (every host keeps release history).
  Migrations so far are additive, so older code runs fine on the newer schema.
- **Schema:** `alembic downgrade -1` via the release-command image, and only if a
  migration itself is broken. Check the migration's `downgrade()` first: dropping tables
  loses data.
- **Vapi:** `git checkout <good-commit> -- vapi/` then `make sync-vapi`. To swap only
  part of the voice stack, set the `VAPI_*_OVERRIDE` vars (ADR 0006) and re-sync.
- **Webhook URL:** if the new host is down, set `PUBLIC_BASE_URL` back to the previous URL
  and `make sync-vapi`.

# 0001 — Tech stack

## Status

Accepted.

## Context

This is a CareCloud take-home assessment: a voice agent (Vapi) collects US patient
demographics over a phone call and a FastAPI backend persists them to Postgres, with a
REST API and a small read-only dashboard. The stack needs to be quick to stand up
correctly, type-safe, testable without excessive ceremony, and to demonstrate production
judgment (structured logging, migrations, auth, rate limiting) rather than just a
happy-path demo.

## Decision

- **Python 3.12 + `uv`** — `uv` gives fast, reproducible installs from a single
  `pyproject.toml`/`uv.lock`, replacing pip/venv/pip-tools with one tool. 3.12 is the
  latest version with mature library support across the chosen stack.
- **FastAPI** — async-native, Pydantic-integrated request/response validation, automatic
  OpenAPI docs, and a dependency-injection system that keeps auth/DB-session wiring out
  of route bodies.
- **Pydantic v2 + `pydantic-settings`** — a single validation layer reused for request
  schemas, settings, and (via `app/validation/`) values shared with the voice tool
  handlers. `pydantic-settings` gives fail-fast, typed environment configuration for free.
- **SQLAlchemy 2.0 (async, typed `Mapped[...]`) + `asyncpg`** — async ORM with modern
  typed models, paired with `asyncpg` for performance and native Postgres feature support
  (e.g. `gen_random_uuid()` defaults).
- **Alembic (async env)** — schema changes must be reviewable, versioned, and repeatable
  across dev/test/prod Neon branches; `create_all()` is fine for throwaway tests only.
- **Neon Postgres** — serverless Postgres with branching (useful for isolated dev/test
  databases) and both a pooled (PgBouncer) and direct connection string, which this
  project uses for the app and Alembic respectively (see
  [`docs/adr/0002-layered-architecture.md`](0002-layered-architecture.md) for how that
  shapes `app/db/session.py`).
- **Vapi** — the specified voice platform; assistant configuration, system prompt, and
  tool schemas are versioned as code under `vapi/` rather than edited only in a UI.
- **`slowapi`** — lightweight rate limiting compatible with FastAPI/Starlette, avoiding a
  dependency on external infrastructure (e.g. Redis) for a project this size.
- **stdlib `logging` + JSON formatter** — structured logs are easy to grep/ingest without
  pulling in a heavier logging framework.
- **`pytest` / `pytest-asyncio` / `httpx.AsyncClient`** — the standard async-FastAPI
  testing combination; `httpx.AsyncClient` with `ASGITransport` exercises the real
  middleware/exception-handler stack without a running server.
- **`ruff` + `mypy --strict`** — one fast tool for lint+format, and strict typing on
  `app/` to catch mistakes before runtime, appropriate for a small codebase reviewed
  under time pressure.

## Consequences

- Two Neon connection strings must be configured (`DATABASE_URL` pooled,
  `DATABASE_URL_DIRECT` direct) and asyncpg must disable its prepared-statement cache
  against the pooled endpoint (PgBouncer transaction mode) — see
  [`app/db/session.py`](../../app/db/session.py).
- `mypy --strict` and `ruff`'s bandit-style `S` rules add short-term friction but catch
  whole classes of bugs (unhandled `Optional`s, unparameterized SQL) relevant to a
  healthcare-adjacent take-home.
- No background job/queue system was introduced; all work (webhook handling, tool calls)
  is synchronous within the request/response cycle, which is sufficient at this scale.

# syntax=docker/dockerfile:1
# Multi-stage build: dependencies are resolved from uv.lock in a builder stage, and only
# the virtualenv + source are copied into a slim, non-root runtime image.

# --- Builder --------------------------------------------------------------------------
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.8.9 /uv /usr/local/bin/uv

# Use the image's Python (no downloads), precompile bytecode for faster cold starts, and
# copy (not hardlink) files so the venv is self-contained for the next stage.
ENV UV_PYTHON_DOWNLOADS=never \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Dependencies first (cached layer): only re-runs when the lock file changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

# --- Runtime --------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

RUN groupadd --system app && useradd --system --gid app --no-create-home app

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
# Runtime code only. migrations/ + alembic.ini ship too so the *same image* can run the
# release step (`alembic upgrade head`) — see docs/deployment.md.
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    # One async worker by default: rate-limit counters are in-process memory, so N
    # workers would allow N x the configured rate per IP. Raise for throughput only
    # together with a shared limiter store (see docs/deployment.md).
    WEB_CONCURRENCY=1 \
    # Trust X-Forwarded-For from the platform's load balancer so rate limiting and logs
    # see the real client IP. Safe only when the container is reachable solely through
    # that proxy (true on Render/Fly/Railway/Cloud Run); override otherwise.
    FORWARDED_ALLOW_IPS="*"

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8000\")}/health', timeout=4)" || exit 1

# Shell form via `sh -c` so $PORT (set by most PaaS hosts) is expanded; `exec` makes
# uvicorn PID 1 so SIGTERM triggers graceful shutdown (lifespan disposes the DB engine).
# uvicorn reads WEB_CONCURRENCY and FORWARDED_ALLOW_IPS from the environment.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --no-server-header"]

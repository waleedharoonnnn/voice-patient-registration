.PHONY: install run lint format typecheck test check migrate migration seed db-up db-down

install:
	uv sync

run:
	uv run uvicorn app.main:app --reload

lint:
	uv run ruff check .

format:
	uv run ruff format .

typecheck:
	uv run mypy app

test:
	uv run pytest

check:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy app
	uv run pytest

migrate:
	uv run alembic upgrade head

migration:
	uv run alembic revision --autogenerate -m "$(m)"

seed:
	uv run python -m scripts.seed

db-up:
	docker compose up -d

db-down:
	docker compose down

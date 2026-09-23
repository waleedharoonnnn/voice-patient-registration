.PHONY: install run lint format typecheck test check

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

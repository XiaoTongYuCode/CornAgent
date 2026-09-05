.PHONY: sync lint test dev migrate
sync:
	uv sync --group dev --locked
lint:
	uv run ruff check app tests migrations
	uv run python -m compileall -q app

test:
	uv run pytest -q

dev:
	uv run python -m app.serve

migrate:
	uv run alembic upgrade head

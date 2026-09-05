.PHONY: setup dev check build
setup:
	cd server && uv sync --group dev --locked
	cd frontend && npm ci
	cd server && uv run python -m app.setup

dev:
	cd server && uv run python ../scripts/dev.py

check:
	$(MAKE) -C server lint test
	cd frontend && npm run lint && npm test

build:
	cd frontend && npm run build

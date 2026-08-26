.PHONY: install test check

install:
	uv sync --all-packages --all-extras
	pnpm install

test:
	uv run pytest -m "not integration"
	pnpm --filter @tam-forge/web test -- --run

check:
	uv run ruff check .
	uv run mypy apps/backend/src packages/protocol/src
	uv run pytest -m "not integration"
	pnpm --filter @tam-forge/web lint
	pnpm --filter @tam-forge/web typecheck
	pnpm --filter @tam-forge/web test -- --run

.PHONY: install test check check-openapi check-policy integration e2e macos-check

install:
	uv sync --all-packages --all-extras
	pnpm install

test:
	uv run pytest -m "not integration"
	pnpm --filter @tam-forge/web test -- --run

check:
	pnpm run test:bootstrap
	pnpm run verify:bootstrap
	uv run ruff check .
	uv run mypy apps/backend/src packages/protocol/src
	MYPYPATH=apps/backend/src:packages/protocol/src uv run mypy scripts/ci/check_openapi.py scripts/ci/check_repository_policy.py scripts/dev/seed_foundation_demo.py
	uv run pytest -m "not integration"
	pnpm --filter @tam-forge/web lint
	pnpm --filter @tam-forge/web typecheck
	pnpm --filter @tam-forge/web test -- --run
	pnpm --filter @tam-forge/web build
	uv run python scripts/ci/check_openapi.py
	uv run python scripts/ci/check_repository_policy.py
	$(MAKE) macos-check

check-openapi:
	uv run python scripts/ci/check_openapi.py

check-policy:
	uv run python scripts/ci/check_repository_policy.py

integration:
	uv run pytest -m integration apps/backend/tests/integration -q

e2e:
	pnpm --filter @tam-forge/web exec playwright test e2e/foundation-learning.spec.ts

macos-check:
	@if command -v xcodebuild >/dev/null 2>&1; then \
		xcodebuild -project apps/macos/TAMForge.xcodeproj -scheme TAMForge -destination 'platform=macOS' build && \
		xcodebuild -project apps/macos/TAMForge.xcodeproj -scheme TAMForge -destination 'platform=macOS' -only-testing:TAMForgeTests test; \
	else \
		echo "Skipping macOS check: xcodebuild is unavailable."; \
	fi

.PHONY: install test check check-openapi check-policy integration e2e macos-check

# Keep local verification comfortable on the 8 GB development Mac. Callers can
# also supply -derivedDataPath here to reuse an existing task-specific cache.
MACOS_BUILD_ARGUMENTS ?= -jobs 2

install:
	uv sync --all-packages --all-extras

test:
	uv run pytest -m "not integration"

check:
	uv run python -m scripts.ci.verify_bootstrap
	uv run ruff check .
	uv run mypy apps/backend/src packages/protocol/src
	MYPYPATH=apps/backend/src:packages/protocol/src uv run mypy scripts/ci/check_openapi.py scripts/ci/check_repository_policy.py scripts/ci/verify_bootstrap.py scripts/ci/verify_compose.py scripts/dev/seed_foundation_demo.py
	uv run pytest -m "not integration"
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
	uv run pytest -m integration apps/backend/tests/integration/foundation/test_month1_workspace.py -q

# The exactly pinned/resolved Apple build-tool plugin needs this headless Xcode flag.
macos-check:
	@if command -v xcodebuild >/dev/null 2>&1; then \
		xcodebuild $(MACOS_BUILD_ARGUMENTS) -skipPackagePluginValidation -project apps/macos/TAMForge.xcodeproj -scheme TAMForge -destination 'platform=macOS' build && \
		xcodebuild $(MACOS_BUILD_ARGUMENTS) -skipPackagePluginValidation -project apps/macos/TAMForge.xcodeproj -scheme TAMForge -destination 'platform=macOS' -only-testing:TAMForgeTests test; \
	else \
		echo "Skipping macOS check: xcodebuild is unavailable."; \
	fi

#!/usr/bin/env bash
set -euo pipefail
export PYTHONPATH="apps/backend/src:packages/protocol/src${PYTHONPATH:+:$PYTHONPATH}"
exec uv run python -m tamforge_backend.testing.plan03_integration_gate "$@"

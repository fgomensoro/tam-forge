"""Contract tests for FastAPI-derived checked OpenAPI inputs."""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

FROZEN_E10_I04_OPENAPI_SHA256 = (
    "7e491966f2d7da2a3ed83436e096c7b67cc033141623e49f6ca5a2818979b344"
)


def _check_openapi_module() -> object:
    script = Path(__file__).parents[1] / "check_openapi.py"
    spec = importlib.util.spec_from_file_location("check_openapi", script)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_normalized_fastapi_schema_matches_frozen_e10_i04_auth_contract() -> None:
    """Keep the locked E10-I04 auth schema explicit beside the drift guard."""
    check_openapi = _check_openapi_module()

    document = check_openapi.normalized_openapi_document()

    assert hashlib.sha256(document).hexdigest() == FROZEN_E10_I04_OPENAPI_SHA256

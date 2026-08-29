"""Contract tests for FastAPI-derived checked OpenAPI inputs."""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

FROZEN_E10_I04_OPENAPI_SHA256 = (
    "fc91de42a3a2414941fadd840d325cea2224ef5c6fba61677a916ea5cd150de4"
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


def test_native_capacity_response_is_documented_only_on_start() -> None:
    """Only native start allocates bounded server-side OAuth state."""
    check_openapi = _check_openapi_module()

    paths = check_openapi.generated_openapi_schema()["paths"]

    assert "429" in paths["/api/v1/auth/native/start"]["post"]["responses"]
    for path in (
        "/api/v1/auth/native/exchange",
        "/api/v1/auth/native/refresh",
        "/api/v1/auth/native/revoke",
    ):
        assert "429" not in paths[path]["post"]["responses"]

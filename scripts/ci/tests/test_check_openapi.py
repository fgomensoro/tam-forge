"""Contract tests for FastAPI-derived checked OpenAPI inputs."""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path


FROZEN_E10_I03_OPENAPI_SHA256 = (
    "34f57897aa94cc47a83a59d82e609e80ac89643cc83caae291020f6dcfdb816e"
)


def _check_openapi_module() -> object:
    script = Path(__file__).parents[1] / "check_openapi.py"
    spec = importlib.util.spec_from_file_location("check_openapi", script)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_normalized_fastapi_schema_matches_frozen_e10_i03_dispatch_contract() -> None:
    """Keep the locked E10-I03 schema baseline explicit beside the drift guard."""
    check_openapi = _check_openapi_module()

    document = check_openapi.normalized_openapi_document()

    assert hashlib.sha256(document).hexdigest() == FROZEN_E10_I03_OPENAPI_SHA256

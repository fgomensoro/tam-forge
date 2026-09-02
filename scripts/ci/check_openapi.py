"""Fail when checked OpenAPI inputs drift from FastAPI's schema."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tamforge_backend.config import APPROVED_GITHUB_USER_ID, Settings
from tamforge_backend.main import create_app

ROOT = Path(__file__).parents[2]
NATIVE_TARGET = ROOT / "apps" / "macos" / "TAMForge" / "openapi.yaml"


def generated_openapi_schema() -> dict[str, object]:
    app = create_app(
        Settings(
            environment="test",
            github_user_id=APPROVED_GITHUB_USER_ID,
            secure_cookies=False,
            _env_file=None,
        )
    )
    return app.openapi()


def normalized_openapi_document() -> bytes:
    return json.dumps(
        generated_openapi_schema(),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def native_openapi_schema() -> dict[str, object]:
    """Lower FastAPI's OpenAPI 3.1 output to the native generator's 3.0 subset."""
    transformed = _native_openapi_value(generated_openapi_schema())
    assert isinstance(transformed, dict)
    transformed["openapi"] = "3.0.3"
    return transformed


def native_openapi_document() -> bytes:
    return json.dumps(
        native_openapi_schema(),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def _native_openapi_value(value: object) -> object:
    if isinstance(value, list):
        return [_native_openapi_value(item) for item in value]
    if not isinstance(value, dict):
        return value

    transformed: dict[str, object] = {
        str(key): _native_openapi_value(item) for key, item in value.items()
    }
    original_any_of = value.get("anyOf")
    transformed_any_of = transformed.get("anyOf")
    if (
        isinstance(original_any_of, list)
        and isinstance(transformed_any_of, list)
        and len(original_any_of) == len(transformed_any_of) == 2
    ):
        null_indexes = [
            index for index, item in enumerate(original_any_of) if item == {"type": "null"}
        ]
        if len(null_indexes) == 1:
            non_null_index = 1 - null_indexes[0]
            alternative = transformed_any_of[non_null_index]
            if isinstance(alternative, dict):
                wrapper = {
                    key: item for key, item in transformed.items() if key != "anyOf"
                }
                if "$ref" in alternative:
                    return _normalize_openapi_30_bounds(
                        {**wrapper, "allOf": [alternative], "nullable": True}
                    )
                return _normalize_openapi_30_bounds(
                    {**alternative, **wrapper, "nullable": True}
                )
    return _normalize_openapi_30_bounds(transformed)


def _normalize_openapi_30_bounds(schema: dict[str, object]) -> dict[str, object]:
    """Translate OpenAPI 3.1 numeric exclusive bounds without losing their meaning."""
    normalized = dict(schema)
    for bound, exclusive in (
        ("minimum", "exclusiveMinimum"),
        ("maximum", "exclusiveMaximum"),
    ):
        threshold = normalized.get(exclusive)
        if not isinstance(threshold, (int, float)) or isinstance(threshold, bool):
            continue
        normalized.pop(exclusive)
        current = normalized.get(bound)
        if not isinstance(current, (int, float)) or isinstance(current, bool):
            normalized[bound] = threshold
            normalized[exclusive] = True
            continue
        is_more_restrictive = (
            threshold >= current if bound == "minimum" else threshold <= current
        )
        if is_more_restrictive:
            normalized[bound] = threshold
            normalized[exclusive] = True
    return normalized


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--write",
        action="store_true",
        help="Replace the checked-in types with the generated schema.",
    )
    arguments = parser.parse_args()
    document = native_openapi_document()
    if arguments.write:
        NATIVE_TARGET.write_bytes(document)
        print(f"updated {NATIVE_TARGET.relative_to(ROOT)}")
        return 0
    if not NATIVE_TARGET.exists() or NATIVE_TARGET.read_bytes() != document:
        print("Native OpenAPI input is out of date.")
        print("Regenerate it with: uv run python scripts/ci/check_openapi.py --write")
        return 1
    print("Native OpenAPI input matches the backend schema.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

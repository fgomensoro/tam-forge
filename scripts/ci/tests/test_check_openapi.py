"""Contract tests for FastAPI-derived checked OpenAPI inputs."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

from tamforge_backend.recordings.schemas import RECORDING_OPENAPI_MODELS

FROZEN_E10_I04_OPENAPI_SHA256 = (
    "af6b5c53c00cabe887ce2b79805e9df3c1f72d0b0889b2c3416454196dad1726"
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


def test_native_openapi_transform_preserves_nullable_constraints_and_references() -> None:
    """Keep the generator input OpenAPI 3.0-compatible without changing FastAPI's contract."""
    check_openapi = _check_openapi_module()

    document = check_openapi.native_openapi_schema()
    schemas = document["components"]["schemas"]

    assert document["openapi"] == "3.0.3"
    assert schemas["TodayResponse"]["properties"]["day_id"] == {
        "exclusiveMinimum": True,
        "minimum": 0.0,
        "nullable": True,
        "title": "Day Id",
        "type": "integer",
    }
    assert schemas["TodayResponse"]["properties"]["primary_continue"] == {
        "allOf": [{"$ref": "#/components/schemas/ContinueAction"}],
        "nullable": True,
    }
    assert schemas["NotificationPage"]["properties"]["next_cursor"] == {
        "exclusiveMinimum": True,
        "minimum": 0.0,
        "nullable": True,
        "title": "Next Cursor",
        "type": "integer",
    }


def test_native_openapi_transform_preserves_every_fastapi_null_union() -> None:
    """A new nullable FastAPI property must remain visible to the native generator."""
    check_openapi = _check_openapi_module()
    canonical = check_openapi.generated_openapi_schema()
    native = check_openapi.native_openapi_schema()

    nullable_paths = list(_nullable_union_paths(canonical))

    assert nullable_paths
    for path in nullable_paths:
        assert _value_at(native, path).get("nullable") is True


def test_recording_contract_components_are_checked_in_without_placeholder_routes() -> None:
    check_openapi = _check_openapi_module()
    expected_components = {
        "CanonicalPCMFormat",
        "PendingRecordingPage",
        "RecordingCreateCommand",
        "RecordingCreateResponse",
        "RecordingGap",
        "RecordingPartCryptoHeaders",
        "RecordingPartDescriptor",
        "RecordingPartReceipt",
        "RecordingPartUploadMetadata",
        "RecordingProblem",
        "RecordingSealCommand",
        "RecordingSealResponse",
        "RecordingSourceLineageSegment",
        "RecordingStatusResponse",
        "RecordingTrackDeclaration",
        "RecordingTrackManifest",
        "RecordingTrackStatus",
    }
    assert {model.__name__ for model in RECORDING_OPENAPI_MODELS} == expected_components

    generated = check_openapi.generated_openapi_schema()
    native = check_openapi.native_openapi_schema()
    checked_in = json.loads(check_openapi.NATIVE_TARGET.read_text(encoding="utf-8"))
    generated_schemas = generated["components"]["schemas"]
    native_schemas = native["components"]["schemas"]
    checked_in_schemas = checked_in["components"]["schemas"]

    assert expected_components <= generated_schemas.keys()
    assert expected_components <= native_schemas.keys()
    assert {name: native_schemas[name] for name in expected_components} == {
        name: checked_in_schemas[name] for name in expected_components
    }
    assert not any(path.startswith("/api/v1/recordings") for path in generated["paths"])


def test_generated_swift_contract_references_key_recording_components() -> None:
    contract = (
        Path(__file__).parents[3]
        / "apps"
        / "macos"
        / "TAMForge"
        / "Core"
        / "API"
        / "GeneratedOpenAPIContract.swift"
    ).read_text(encoding="utf-8")

    for component in (
        "RecordingSealCommand",
        "RecordingTrackManifest",
        "RecordingSourceLineageSegment",
        "RecordingStatusResponse",
    ):
        assert f"Components.Schemas.{component}" in contract


def _nullable_union_paths(
    value: object, path: tuple[str | int, ...] = ()
) -> list[tuple[str | int, ...]]:
    if isinstance(value, dict):
        any_of = value.get("anyOf")
        if (
            isinstance(any_of, list)
            and len(any_of) == 2
            and sum(item == {"type": "null"} for item in any_of) == 1
        ):
            return [path]
        return [
            child_path
            for key, child in value.items()
            for child_path in _nullable_union_paths(child, (*path, key))
        ]
    if isinstance(value, list):
        return [
            child_path
            for index, child in enumerate(value)
            for child_path in _nullable_union_paths(child, (*path, index))
        ]
    return []


def _value_at(document: dict[str, object], path: tuple[str | int, ...]) -> dict[str, object]:
    value: object = document
    for part in path:
        value = value[part]  # type: ignore[index]
    assert isinstance(value, dict)
    return value

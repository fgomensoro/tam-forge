"""Content-addressed activity artifact validation and commitment hashing."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from ..storage.models import (
    StoredObject,
    build_object_key,
    validate_content_type,
    validate_sha256,
)
from .contracts import ValidatedOutput

ARTIFACT_CLASSES: Final = frozenset(
    {
        "original_audio",
        "transcript",
        "written_output",
        "sql_output",
        "recall_note",
        "case_artifact",
        "analysis",
        "export",
    }
)
LINK_ROLES: Final = frozenset(
    {
        "original_output",
        "presentation_audio",
        "transcript",
        "analysis",
        "supporting",
        "correction",
    }
)
_FILENAME = re.compile(r"^[^/\\\x00-\x1f\x7f]{1,512}$")
_CONTENT_TYPE = re.compile(r"^[a-z0-9][a-z0-9.+-]*/[a-z0-9][a-z0-9.+-]*$")


class ArtifactValidationError(ValueError):
    """An upload intent, confirmation, or commitment manifest is invalid."""


@dataclass(frozen=True, slots=True)
class ArtifactUploadIntent:
    owner_id: int
    activity_id: int
    artifact_class: str
    object_key: str
    sha256: str
    byte_length: int
    content_type: str
    original_filename: str
    metadata: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class ArtifactCommitment:
    artifact_id: int
    sha256: str
    link_role: str

    def __post_init__(self) -> None:
        if self.artifact_id <= 0 or self.link_role not in LINK_ROLES:
            raise ArtifactValidationError("artifact commitment is invalid")
        try:
            validate_sha256(self.sha256)
        except ValueError as exc:
            raise ArtifactValidationError("artifact commitment hash is invalid") from exc


def build_upload_intent(
    *,
    owner_id: int,
    activity_id: int,
    artifact_class: str,
    sha256: str,
    byte_length: int,
    content_type: str,
    original_filename: str,
) -> ArtifactUploadIntent:
    if owner_id <= 0 or activity_id <= 0:
        raise ArtifactValidationError("artifact owner or activity is invalid")
    if artifact_class not in ARTIFACT_CLASSES:
        raise ArtifactValidationError("artifact class is invalid")
    if byte_length < 0:
        raise ArtifactValidationError("artifact byte length is invalid")
    if (
        not _FILENAME.fullmatch(original_filename)
        or not original_filename.strip()
        or len(original_filename.encode("utf-8")) > 512
    ):
        raise ArtifactValidationError("artifact filename is invalid")
    try:
        digest = validate_sha256(sha256)
        validated_content_type = validate_content_type(content_type)
        object_key = build_object_key(
            artifact_class=artifact_class,
            owner_id=str(owner_id),
            logical_id=f"activity-{activity_id}",
            sha256=digest,
        )
    except ValueError as exc:
        raise ArtifactValidationError("artifact upload metadata is invalid") from exc
    if len(validated_content_type.encode("utf-8")) > 128:
        raise ArtifactValidationError("artifact content type is too long")
    if not _CONTENT_TYPE.fullmatch(validated_content_type):
        raise ArtifactValidationError("artifact content type is invalid")
    return ArtifactUploadIntent(
        owner_id=owner_id,
        activity_id=activity_id,
        artifact_class=artifact_class,
        object_key=object_key,
        sha256=digest,
        byte_length=byte_length,
        content_type=validated_content_type,
        original_filename=original_filename,
        metadata={"activity-id": str(activity_id), "owner-id": str(owner_id)},
    )


def verify_confirm_request(intent: ArtifactUploadIntent, *, object_key: str) -> None:
    if object_key != intent.object_key:
        raise ArtifactValidationError("confirmation requires the server-generated object key")


def verify_stored_object(intent: ArtifactUploadIntent, stored: StoredObject) -> None:
    expected_metadata = intent.metadata
    if (
        stored.key != intent.object_key
        or stored.sha256 != intent.sha256
        or stored.byte_length != intent.byte_length
        or stored.content_type != intent.content_type
        or any(stored.metadata.get(key) != value for key, value in expected_metadata.items())
    ):
        raise ArtifactValidationError("uploaded object does not match the confirmed intent")


def build_commitment_digest(
    output: ValidatedOutput,
    artifacts: tuple[ArtifactCommitment, ...],
) -> bytes:
    manifest = sorted(
        (
            {
                "artifact_id": item.artifact_id,
                "sha256": item.sha256,
                "link_role": item.link_role,
            }
            for item in artifacts
        ),
        key=lambda item: (item["artifact_id"], item["link_role"]),
    )
    if len({(item["artifact_id"], item["link_role"]) for item in manifest}) != len(manifest):
        raise ArtifactValidationError("artifact commitment contains duplicate links")
    canonical = json.dumps(
        {"output": output.canonical_payload, "artifacts": manifest},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).digest()


def unencrypted_metadata() -> dict[str, object]:
    """Record the honest pre-deployment state until at-rest encryption is approved."""
    return {
        "schema_version": 1,
        "encrypted": False,
        "algorithm": None,
        "key_reference": None,
    }


__all__ = [
    "ArtifactCommitment",
    "ArtifactUploadIntent",
    "ArtifactValidationError",
    "build_commitment_digest",
    "build_upload_intent",
    "unencrypted_metadata",
    "verify_confirm_request",
    "verify_stored_object",
]

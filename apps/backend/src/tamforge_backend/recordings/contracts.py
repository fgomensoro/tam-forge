"""Canonical byte domains shared by recording encryption, hashing, and sealing."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence

from pydantic import BaseModel

from .schemas import RecordingPartUploadMetadata, RecordingSealCommand, RecordingTrackManifest

MANIFEST_DOMAIN = b"tamforge.recording.manifest.v1\0"
PART_AAD_DOMAIN = b"tamforge.recording.part-aad.v1\0"
TIMELINE_DOMAIN = b"tamforge.recording.timeline.v1\0"

RECORDING_HEADER_NAMES = (
    "Idempotency-Key",
    "X-TAM-Recording-Schema",
    "X-TAM-Track-Kind",
    "X-TAM-Sample-Encoding",
    "X-TAM-Sample-Rate",
    "X-TAM-Channel-Count",
    "X-TAM-Part-Sequence",
    "X-TAM-Sample-Start",
    "X-TAM-Sample-Count",
    "X-TAM-Plaintext-Length",
    "X-TAM-Ciphertext-Length",
    "X-TAM-Plaintext-SHA256",
    "X-TAM-Ciphertext-SHA256",
    "X-TAM-Part-Nonce",
    "X-TAM-Part-Key",
    "X-TAM-Part-Encryption",
)
SENSITIVE_RECORDING_HEADERS = frozenset({"authorization", "x-tam-part-key"})

CanonicalValue = str | int | bool | None | list["CanonicalValue"] | dict[str, "CanonicalValue"]


def canonical_json_bytes(value: BaseModel | Mapping[str, object]) -> bytes:
    """Encode the contract's integer-only JSON subset deterministically."""
    raw: object = value.model_dump(mode="json") if isinstance(value, BaseModel) else dict(value)
    normalized = _canonical_value(raw)
    return json.dumps(
        normalized,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def recording_manifest_hash_input(manifest: RecordingSealCommand) -> bytes:
    return MANIFEST_DOMAIN + canonical_json_bytes(manifest)


def recording_manifest_sha256(manifest: RecordingSealCommand) -> str:
    return hashlib.sha256(recording_manifest_hash_input(manifest)).hexdigest()


def part_aad_bytes(metadata: RecordingPartUploadMetadata) -> bytes:
    """Bind decryptable metadata; ciphertext digest is verified outside its own AAD."""
    payload = metadata.model_dump(
        mode="json",
        exclude={"ciphertext_sha256"},
    )
    return PART_AAD_DOMAIN + canonical_json_bytes(payload)


def timeline_hash_input(track: RecordingTrackManifest) -> bytes:
    payload = track.model_dump(
        mode="json",
        exclude={"pcm_sha256", "timeline_sha256"},
    )
    return TIMELINE_DOMAIN + canonical_json_bytes(payload)


def timeline_sha256(track: RecordingTrackManifest) -> str:
    return hashlib.sha256(timeline_hash_input(track)).hexdigest()


def _canonical_value(value: object) -> CanonicalValue:
    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float):
        raise TypeError("canonical recording JSON forbids floating-point values")
    if isinstance(value, Mapping):
        normalized: dict[str, CanonicalValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("canonical recording JSON requires string object keys")
            normalized[key] = _canonical_value(item)
        return normalized
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray | memoryview):
        return [_canonical_value(item) for item in value]
    raise TypeError(f"unsupported canonical recording JSON value: {type(value).__name__}")


__all__ = [
    "MANIFEST_DOMAIN",
    "PART_AAD_DOMAIN",
    "RECORDING_HEADER_NAMES",
    "SENSITIVE_RECORDING_HEADERS",
    "TIMELINE_DOMAIN",
    "canonical_json_bytes",
    "part_aad_bytes",
    "recording_manifest_hash_input",
    "recording_manifest_sha256",
    "timeline_hash_input",
    "timeline_sha256",
]

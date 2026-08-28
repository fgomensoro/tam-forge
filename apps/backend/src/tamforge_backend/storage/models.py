"""Value objects and trust-boundary validation for private object storage."""

from __future__ import annotations

import re
from base64 import b64encode
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Final

MAX_OBJECT_KEY_BYTES: Final = 1024
MAX_PRESIGN_EXPIRY_SECONDS: Final = 900
MAX_METADATA_BYTES: Final = 2 * 1024
READ_CHUNK_BYTES: Final = 64 * 1024
SHA256_METADATA_KEY: Final = "sha256"
BYTE_LENGTH_METADATA_KEY: Final = "byte-length"

_KEY_SEGMENT = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_METADATA_KEY = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_RESERVED_METADATA = {SHA256_METADATA_KEY, BYTE_LENGTH_METADATA_KEY}


class ObjectStoreError(Exception):
    """Base error whose message is safe to expose without provider details."""


class InvalidObjectKey(ObjectStoreError):
    """Object key is not a server-generated scoped key."""


class InvalidObjectMetadata(ObjectStoreError):
    """Object metadata is invalid or attempts to replace integrity fields."""


class InvalidPresignExpiry(ObjectStoreError):
    """Presigned request expiry exceeds the application policy."""


class ObjectConflict(ObjectStoreError):
    """An immutable key already exists with different content or metadata."""


class ObjectIntegrityError(ObjectConflict):
    """The declared integrity data does not match the object bytes."""


class ObjectTooLarge(ObjectStoreError):
    """The object exceeds the configured bounded upload size."""


class ObjectNotFound(ObjectStoreError):
    """The requested private object does not exist."""


def validate_sha256(value: str) -> str:
    if not _SHA256.fullmatch(value):
        raise ObjectIntegrityError("SHA-256 must be 64 lowercase hexadecimal characters")
    return value


def provider_sha256_checksum(value: str) -> str:
    """Return the S3-native base64 checksum for one canonical hex digest."""
    return b64encode(bytes.fromhex(validate_sha256(value))).decode("ascii")


def _validate_key_segment(value: str) -> str:
    if not _KEY_SEGMENT.fullmatch(value) or value in {".", ".."}:
        raise InvalidObjectKey("object key segment is invalid")
    return value


def build_object_key(
    *,
    artifact_class: str,
    owner_id: str,
    logical_id: str,
    sha256: str,
) -> str:
    """Build the only supported class/owner/logical-id/hash key shape."""
    digest = validate_sha256(sha256)
    key = "/".join(
        (
            _validate_key_segment(artifact_class),
            _validate_key_segment(owner_id),
            _validate_key_segment(logical_id),
            digest,
        )
    )
    return validate_object_key(key)


def validate_object_key(key: str) -> str:
    """Reject arbitrary paths; accept only the server-generated four-part shape."""
    if (
        not key
        or key.startswith("/")
        or "\\" in key
        or len(key.encode("utf-8")) > MAX_OBJECT_KEY_BYTES
        or any(ord(character) < 32 or ord(character) == 127 for character in key)
    ):
        raise InvalidObjectKey("object key is invalid")
    parts = key.split("/")
    if len(parts) != 4:
        raise InvalidObjectKey("object key must contain class, owner, logical ID, and hash")
    for part in parts[:3]:
        _validate_key_segment(part)
    try:
        validate_sha256(parts[3])
    except ObjectIntegrityError:
        raise InvalidObjectKey("object key hash segment is invalid") from None
    return key


def validate_key_sha256(key: str, sha256: str) -> tuple[str, str]:
    validated_key = validate_object_key(key)
    digest = validate_sha256(sha256)
    if validated_key.rsplit("/", 1)[1] != digest:
        raise ObjectIntegrityError("object key hash does not match declared SHA-256")
    return validated_key, digest


def validate_content_type(content_type: str) -> str:
    if (
        not content_type
        or len(content_type) > 255
        or any(ord(character) < 32 or ord(character) == 127 for character in content_type)
    ):
        raise InvalidObjectMetadata("content type is invalid")
    return content_type


def normalize_metadata(metadata: Mapping[str, str]) -> Mapping[str, str]:
    normalized: dict[str, str] = {}
    total_bytes = 0
    for key, value in metadata.items():
        if (
            not _METADATA_KEY.fullmatch(key)
            or key in _RESERVED_METADATA
            or not isinstance(value, str)
            or not value.isascii()
            or len(value) > 1024
            or any(ord(character) < 32 or ord(character) == 127 for character in value)
        ):
            raise InvalidObjectMetadata("object metadata is invalid")
        total_bytes += len(key.encode("utf-8")) + len(value.encode("utf-8"))
        if total_bytes > MAX_METADATA_BYTES:
            raise InvalidObjectMetadata("object metadata is too large")
        normalized[key] = value
    return MappingProxyType(normalized)


def integrity_metadata(
    *,
    sha256: str,
    byte_length: int,
    metadata: Mapping[str, str],
) -> Mapping[str, str]:
    digest = validate_sha256(sha256)
    if byte_length < 0:
        raise ObjectIntegrityError("byte length cannot be negative")
    merged = dict(normalize_metadata(metadata))
    merged[SHA256_METADATA_KEY] = digest
    merged[BYTE_LENGTH_METADATA_KEY] = str(byte_length)
    total_bytes = sum(
        len(key.encode("ascii")) + len(value.encode("ascii"))
        for key, value in merged.items()
    )
    if total_bytes > MAX_METADATA_BYTES:
        raise InvalidObjectMetadata("object metadata is too large")
    return MappingProxyType(merged)


def validate_presign_expiry(expires_seconds: int) -> int:
    if not 1 <= expires_seconds <= MAX_PRESIGN_EXPIRY_SECONDS:
        raise InvalidPresignExpiry(
            f"expiry must be between 1 and {MAX_PRESIGN_EXPIRY_SECONDS} seconds"
        )
    return expires_seconds


@dataclass(frozen=True, slots=True)
class StoredObject:
    key: str
    sha256: str
    byte_length: int
    content_type: str
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        validate_key_sha256(self.key, self.sha256)
        validate_content_type(self.content_type)
        expected = integrity_metadata(
            sha256=self.sha256,
            byte_length=self.byte_length,
            metadata={
                key: value
                for key, value in self.metadata.items()
                if key not in _RESERVED_METADATA
            },
        )
        if dict(expected) != dict(self.metadata):
            raise ObjectIntegrityError("stored object metadata is incomplete")
        object.__setattr__(self, "metadata", expected)


@dataclass(frozen=True, slots=True)
class PresignPutRequest:
    key: str
    sha256: str
    byte_length: int
    content_type: str
    metadata: Mapping[str, str] = field(default_factory=dict)
    expires_seconds: int = 300

    def __post_init__(self) -> None:
        validate_key_sha256(self.key, self.sha256)
        if self.byte_length < 0:
            raise ObjectIntegrityError("byte length cannot be negative")
        validate_content_type(self.content_type)
        normalized_metadata = normalize_metadata(self.metadata)
        integrity_metadata(
            sha256=self.sha256,
            byte_length=self.byte_length,
            metadata=normalized_metadata,
        )
        object.__setattr__(self, "metadata", normalized_metadata)
        validate_presign_expiry(self.expires_seconds)


@dataclass(frozen=True, slots=True)
class PresignedRequest:
    url: str = field(repr=False)
    method: str
    headers: Mapping[str, str]
    expires_seconds: int

    def __post_init__(self) -> None:
        if not self.url:
            raise ValueError("presigned URL cannot be empty")
        if self.method != "PUT":
            raise ValueError("only private PUT requests are supported")
        object.__setattr__(self, "headers", MappingProxyType(dict(self.headers)))
        validate_presign_expiry(self.expires_seconds)

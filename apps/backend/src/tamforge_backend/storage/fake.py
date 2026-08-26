"""Deterministic in-process implementation of the object-store contract."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from urllib.parse import quote

import anyio

from .models import (
    READ_CHUNK_BYTES,
    ObjectConflict,
    ObjectIntegrityError,
    ObjectNotFound,
    ObjectTooLarge,
    PresignedRequest,
    PresignPutRequest,
    StoredObject,
    integrity_metadata,
    validate_content_type,
    validate_key_sha256,
    validate_object_key,
    validate_presign_expiry,
)


class InMemoryObjectStore:
    """Contract fake. Production data must never use this adapter."""

    def __init__(self, *, max_upload_bytes: int = 1024 * 1024 * 1024) -> None:
        if max_upload_bytes < 1:
            raise ValueError("max upload bytes must be positive")
        self._max_upload_bytes = max_upload_bytes
        self._objects: dict[str, tuple[StoredObject, bytes]] = {}
        self._lock = anyio.Lock()

    async def put_immutable(
        self,
        *,
        key: str,
        body: AsyncIterator[bytes],
        sha256: str,
        content_type: str,
        metadata: Mapping[str, str],
    ) -> StoredObject:
        _, digest = validate_key_sha256(key, sha256)
        validate_content_type(content_type)
        data = bytearray()
        hasher = hashlib.sha256()
        async for chunk in body:
            if not isinstance(chunk, bytes):
                raise ObjectIntegrityError("object body chunks must be bytes")
            if len(data) + len(chunk) > self._max_upload_bytes:
                raise ObjectTooLarge("object exceeds configured upload limit")
            data.extend(chunk)
            hasher.update(chunk)
        if hasher.hexdigest() != digest:
            raise ObjectIntegrityError("streamed body does not match declared SHA-256")
        object_metadata = integrity_metadata(
            sha256=digest,
            byte_length=len(data),
            metadata=metadata,
        )
        candidate = StoredObject(
            key=key,
            sha256=digest,
            byte_length=len(data),
            content_type=content_type,
            metadata=object_metadata,
        )

        async with self._lock:
            existing = self._objects.get(key)
            if existing is not None:
                if existing[0] == candidate:
                    return existing[0]
                raise ObjectConflict("immutable object already exists with different content")
            self._objects[key] = (candidate, bytes(data))
        return candidate

    async def stat(self, key: str) -> StoredObject | None:
        validate_object_key(key)
        async with self._lock:
            entry = self._objects.get(key)
            return entry[0] if entry is not None else None

    @asynccontextmanager
    async def open(self, key: str) -> AsyncIterator[AsyncIterator[bytes]]:
        validate_object_key(key)
        async with self._lock:
            entry = self._objects.get(key)
            if entry is None:
                raise ObjectNotFound("private object was not found")
            data = entry[1]

        async def stream() -> AsyncIterator[bytes]:
            for offset in range(0, len(data), READ_CHUNK_BYTES):
                yield data[offset : offset + READ_CHUNK_BYTES]

        yield stream()

    async def presign_put(self, request: PresignPutRequest) -> PresignedRequest:
        if request.byte_length > self._max_upload_bytes:
            raise ObjectTooLarge("object exceeds configured upload limit")
        metadata = integrity_metadata(
            sha256=request.sha256,
            byte_length=request.byte_length,
            metadata=request.metadata,
        )
        headers = {
            "content-type": request.content_type,
            "if-none-match": "*",
            **{f"x-amz-meta-{key}": value for key, value in metadata.items()},
        }
        return PresignedRequest(
            url=f"https://object-store.invalid/{quote(request.key)}?signed=1",
            method="PUT",
            headers=headers,
            expires_seconds=request.expires_seconds,
        )

    async def presign_get(self, key: str, *, expires_seconds: int) -> str:
        validate_object_key(key)
        validate_presign_expiry(expires_seconds)
        return f"https://object-store.invalid/{quote(key)}?signed=1"

"""S3-compatible private immutable object-store adapter."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from functools import partial
from tempfile import SpooledTemporaryFile
from typing import Any

import anyio
import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError
from mypy_boto3_s3 import S3Client
from mypy_boto3_s3.type_defs import GetObjectOutputTypeDef

from .models import (
    BYTE_LENGTH_METADATA_KEY,
    READ_CHUNK_BYTES,
    SHA256_METADATA_KEY,
    ObjectConflict,
    ObjectIntegrityError,
    ObjectNotFound,
    ObjectStoreError,
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

_NOT_FOUND_CODES = {"404", "NoSuchKey", "NotFound"}
_RETRYABLE_CONFLICT_CODES = {"409", "ConditionalRequestConflict"}
_EXISTING_CONFLICT_CODES = {"412", "PreconditionFailed"}


class S3ObjectStore:
    """Private S3 adapter. All blocking provider operations run off-loop."""

    def __init__(
        self,
        *,
        endpoint_url: str | None,
        region: str,
        bucket: str,
        access_key: str,
        secret_key: str,
        max_upload_bytes: int = 1024 * 1024 * 1024,
        memory_spool_bytes: int = 1024 * 1024,
        client: S3Client | None = None,
    ) -> None:
        if not region or not bucket:
            raise ValueError("object-store region and bucket are required")
        if max_upload_bytes < 1 or not 1 <= memory_spool_bytes <= max_upload_bytes:
            raise ValueError("object-store spool bounds are invalid")
        if client is None and (not access_key or not secret_key):
            raise ValueError("object-store credentials are required")
        self._bucket = bucket
        self._max_upload_bytes = max_upload_bytes
        self._memory_spool_bytes = memory_spool_bytes
        self._client: S3Client = client or boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    def __repr__(self) -> str:
        return f"S3ObjectStore(bucket={self._bucket!r})"

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
        spool = SpooledTemporaryFile(max_size=self._memory_spool_bytes, mode="w+b")
        byte_length = 0
        hasher = hashlib.sha256()
        try:
            async for chunk in body:
                if not isinstance(chunk, bytes):
                    raise ObjectIntegrityError("object body chunks must be bytes")
                byte_length += len(chunk)
                if byte_length > self._max_upload_bytes:
                    raise ObjectTooLarge("object exceeds configured upload limit")
                hasher.update(chunk)
                await anyio.to_thread.run_sync(spool.write, chunk)
            if hasher.hexdigest() != digest:
                raise ObjectIntegrityError("streamed body does not match declared SHA-256")
            object_metadata = integrity_metadata(
                sha256=digest,
                byte_length=byte_length,
                metadata=metadata,
            )
            candidate = StoredObject(
                key=key,
                sha256=digest,
                byte_length=byte_length,
                content_type=content_type,
                metadata=object_metadata,
            )
            for attempt in range(3):
                await anyio.to_thread.run_sync(spool.seek, 0)
                try:
                    await anyio.to_thread.run_sync(
                        partial(
                            self._client.put_object,
                            Bucket=self._bucket,
                            Key=key,
                            Body=spool,
                            ContentLength=byte_length,
                            ContentType=content_type,
                            Metadata=dict(object_metadata),
                            IfNoneMatch="*",
                        )
                    )
                    return candidate
                except ClientError as exc:
                    error_code = self._error_code(exc)
                    if error_code not in (
                        _RETRYABLE_CONFLICT_CODES | _EXISTING_CONFLICT_CODES
                    ):
                        raise ObjectStoreError("object-store write failed") from None
                    existing = await self.stat(key)
                    if existing is not None:
                        if existing == candidate:
                            return existing
                        raise ObjectConflict(
                            "immutable object already exists with different content"
                        ) from None
                    if error_code in _EXISTING_CONFLICT_CODES:
                        raise ObjectConflict(
                            "immutable object already exists with different content"
                        ) from None
                    if attempt < 2:
                        await anyio.sleep(0)
                except BotoCoreError:
                    raise ObjectStoreError("object-store write failed") from None
            raise ObjectStoreError("object-store conditional write did not settle")
        finally:
            await anyio.to_thread.run_sync(spool.close)

    async def stat(self, key: str) -> StoredObject | None:
        validate_object_key(key)
        try:
            response = await anyio.to_thread.run_sync(
                partial(self._client.head_object, Bucket=self._bucket, Key=key)
            )
        except ClientError as exc:
            if self._error_code(exc) in _NOT_FOUND_CODES:
                return None
            raise ObjectStoreError("object-store stat failed") from None
        except BotoCoreError:
            raise ObjectStoreError("object-store stat failed") from None

        metadata = dict(response.get("Metadata", {}))
        digest = metadata.get(SHA256_METADATA_KEY, "")
        encoded_length = metadata.get(BYTE_LENGTH_METADATA_KEY, "")
        try:
            metadata_length = int(encoded_length)
            content_length = int(response["ContentLength"])
        except (KeyError, TypeError, ValueError):
            raise ObjectIntegrityError("stored object integrity metadata is invalid") from None
        if metadata_length != content_length:
            raise ObjectIntegrityError("stored object byte length does not match metadata")
        return StoredObject(
            key=key,
            sha256=digest,
            byte_length=content_length,
            content_type=str(response.get("ContentType", "application/octet-stream")),
            metadata=metadata,
        )

    @asynccontextmanager
    async def open(self, key: str) -> AsyncIterator[AsyncIterator[bytes]]:
        validate_object_key(key)
        try:
            response: GetObjectOutputTypeDef = await anyio.to_thread.run_sync(
                partial(self._client.get_object, Bucket=self._bucket, Key=key)
            )
        except ClientError as exc:
            if self._error_code(exc) in _NOT_FOUND_CODES:
                raise ObjectNotFound("private object was not found") from None
            raise ObjectStoreError("object-store read failed") from None
        except BotoCoreError:
            raise ObjectStoreError("object-store read failed") from None
        provider_body = response["Body"]

        async def stream() -> AsyncIterator[bytes]:
            while True:
                chunk = await anyio.to_thread.run_sync(provider_body.read, READ_CHUNK_BYTES)
                if not chunk:
                    return
                yield chunk

        try:
            yield stream()
        finally:
            await anyio.to_thread.run_sync(provider_body.close)

    async def presign_put(self, request: PresignPutRequest) -> PresignedRequest:
        if request.byte_length > self._max_upload_bytes:
            raise ObjectTooLarge("object exceeds configured upload limit")
        object_metadata = integrity_metadata(
            sha256=request.sha256,
            byte_length=request.byte_length,
            metadata=request.metadata,
        )
        params: dict[str, Any] = {
            "Bucket": self._bucket,
            "Key": request.key,
            "ContentLength": request.byte_length,
            "ContentType": request.content_type,
            "Metadata": dict(object_metadata),
            "IfNoneMatch": "*",
        }
        try:
            url = await anyio.to_thread.run_sync(
                partial(
                    self._client.generate_presigned_url,
                    "put_object",
                    Params=params,
                    ExpiresIn=request.expires_seconds,
                    HttpMethod="PUT",
                )
            )
        except (BotoCoreError, ClientError, ValueError):
            raise ObjectStoreError("object-store signing failed") from None
        headers = {
            "content-length": str(request.byte_length),
            "content-type": request.content_type,
            "if-none-match": "*",
            **{f"x-amz-meta-{key}": value for key, value in object_metadata.items()},
        }
        return PresignedRequest(
            url=url,
            method="PUT",
            headers=headers,
            expires_seconds=request.expires_seconds,
        )

    async def presign_get(self, key: str, *, expires_seconds: int) -> str:
        validate_object_key(key)
        validate_presign_expiry(expires_seconds)
        try:
            return await anyio.to_thread.run_sync(
                partial(
                    self._client.generate_presigned_url,
                    "get_object",
                    Params={"Bucket": self._bucket, "Key": key},
                    ExpiresIn=expires_seconds,
                    HttpMethod="GET",
                )
            )
        except (BotoCoreError, ClientError, ValueError):
            raise ObjectStoreError("object-store signing failed") from None

    @staticmethod
    def _error_code(exc: ClientError) -> str:
        return str(exc.response.get("Error", {}).get("Code", ""))

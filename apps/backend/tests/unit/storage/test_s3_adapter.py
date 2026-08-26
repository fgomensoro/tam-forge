from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from base64 import b64encode
from collections.abc import AsyncIterator
from pathlib import Path
from tempfile import SpooledTemporaryFile
from typing import Any
from urllib.parse import parse_qs, urlsplit

import anyio
import boto3
import pytest
from botocore import UNSIGNED
from botocore.client import Config
from botocore.exceptions import ClientError
from moto import mock_aws


async def chunks(*values: bytes) -> AsyncIterator[bytes]:
    for value in values:
        yield value


class ConflictOnceClient:
    def __init__(self, client: object) -> None:
        self._client = client
        self.put_calls = 0

    def put_object(self, **kwargs: object) -> object:
        from botocore.exceptions import ClientError

        self.put_calls += 1
        if self.put_calls == 1:
            raise ClientError(
                {"Error": {"Code": "ConditionalRequestConflict", "Message": "race"}},
                "PutObject",
            )
        return self._client.put_object(**kwargs)  # type: ignore[attr-defined]

    def __getattr__(self, name: str) -> object:
        return getattr(self._client, name)


class FailingSpool:
    def __init__(self, fail_operation: str) -> None:
        self._delegate = SpooledTemporaryFile(max_size=1, mode="w+b")
        self._fail_operation = fail_operation

    def write(self, value: bytes) -> int:
        if self._fail_operation == "write":
            raise OSError("sensitive write path")
        return self._delegate.write(value)

    def seek(self, offset: int) -> int:
        if self._fail_operation == "seek":
            raise OSError("sensitive seek path")
        return self._delegate.seek(offset)

    def read(self, size: int = -1) -> bytes:
        if self._fail_operation == "read":
            raise OSError("sensitive read path")
        return self._delegate.read(size)

    def tell(self) -> int:
        return self._delegate.tell()

    def close(self) -> None:
        self._delegate.close()
        if self._fail_operation == "close":
            raise OSError("sensitive close path")


@pytest.fixture
def s3_store(moto_s3_client: Any) -> object:
    from tamforge_backend.storage.s3 import S3ObjectStore

    return S3ObjectStore(
        endpoint_url=None,
        region="us-east-1",
        bucket="tam-forge-test",
        access_key="test-access",
        secret_key="test-secret",
        client=moto_s3_client,
    )


@pytest.mark.anyio
async def test_moto_adapter_enforces_immutable_conditional_create(s3_store: object) -> None:
    from tamforge_backend.storage.models import ObjectConflict, build_object_key
    from tamforge_backend.storage.ports import ObjectStore

    store: ObjectStore = s3_store  # type: ignore[assignment]
    first = b"first"
    second = b"second"
    first_digest = hashlib.sha256(first).hexdigest()
    second_digest = hashlib.sha256(second).hexdigest()
    key = build_object_key(
        artifact_class="recording-segment",
        owner_id="0191af17-cc6e-7da1-a9d0-b0e542bc7460",
        logical_id="track-1-seq-0-49",
        sha256=first_digest,
    )

    initial = await store.put_immutable(
        key=key,
        body=chunks(first),
        sha256=first_digest,
        content_type="application/octet-stream",
        metadata={"track": "1"},
    )
    repeated = await store.put_immutable(
        key=key,
        body=chunks(first),
        sha256=first_digest,
        content_type="application/octet-stream",
        metadata={"track": "1"},
    )

    assert repeated == initial
    with pytest.raises(ObjectConflict):
        await store.put_immutable(
            key=key,
            body=chunks(second),
            sha256=second_digest,
            content_type="application/octet-stream",
            metadata={"track": "1"},
        )


@pytest.mark.anyio
async def test_moto_adapter_streams_reads_and_presigns_without_public_acl(
    s3_store: object,
) -> None:
    from tamforge_backend.storage.models import PresignPutRequest, build_object_key
    from tamforge_backend.storage.ports import ObjectStore

    store: ObjectStore = s3_store  # type: ignore[assignment]
    payload = b"z" * 150_000
    digest = hashlib.sha256(payload).hexdigest()
    key = build_object_key(
        artifact_class="archive",
        owner_id="0191af17-cc6e-7da1-a9d0-b0e542bc7460",
        logical_id="export-v1",
        sha256=digest,
    )
    stored = await store.put_immutable(
        key=key,
        body=chunks(payload),
        sha256=digest,
        content_type="application/octet-stream",
        metadata={},
    )

    async with store.open(key) as stream:
        received_chunks = [chunk async for chunk in stream]
    signed = await store.presign_put(
        PresignPutRequest(
            key=key,
            sha256=digest,
            byte_length=len(payload),
            content_type="application/octet-stream",
            metadata={},
            expires_seconds=60,
        )
    )

    assert stored.byte_length == len(payload)
    assert b"".join(received_chunks) == payload
    assert len(received_chunks) > 1
    assert signed.headers["x-amz-acl"] == "private"
    assert "X-Amz-Signature" in signed.url

    unsigned = boto3.client(
        "s3",
        region_name="us-east-1",
        config=Config(signature_version=UNSIGNED),
    )
    for operation in (unsigned.head_object, unsigned.get_object):
        with pytest.raises(ClientError) as exc_info:
            operation(Bucket="tam-forge-test", Key=key)
        assert exc_info.value.response["ResponseMetadata"]["HTTPStatusCode"] == 403


@pytest.mark.anyio
async def test_s3_upload_rejects_body_larger_than_disk_spool_bound() -> None:
    from tamforge_backend.storage.models import ObjectTooLarge, build_object_key
    from tamforge_backend.storage.s3 import S3ObjectStore

    with mock_aws():
        client = boto3.client(
            "s3",
            region_name="us-east-1",
            aws_access_key_id="test-access",
            aws_secret_access_key="test-secret",
            config=Config(signature_version="s3v4"),
        )
        client.create_bucket(Bucket="tam-forge-test")
        store = S3ObjectStore(
            endpoint_url=None,
            region="us-east-1",
            bucket="tam-forge-test",
            access_key="test-access",
            secret_key="test-secret",
            max_upload_bytes=4,
            memory_spool_bytes=2,
            client=client,
        )
        payload = b"12345"
        digest = hashlib.sha256(payload).hexdigest()
        key = build_object_key(
            artifact_class="archive",
            owner_id="0191af17-cc6e-7da1-a9d0-b0e542bc7460",
            logical_id="bounded",
            sha256=digest,
        )

        with pytest.raises(ObjectTooLarge):
            await store.put_immutable(
                key=key,
                body=chunks(b"12", b"345"),
                sha256=digest,
                content_type="application/octet-stream",
                metadata={},
            )

        assert await store.stat(key) is None


@pytest.mark.anyio
async def test_s3_retries_conditional_race_without_overwriting() -> None:
    from tamforge_backend.storage.models import build_object_key
    from tamforge_backend.storage.s3 import S3ObjectStore

    with mock_aws():
        client = boto3.client(
            "s3",
            region_name="us-east-1",
            aws_access_key_id="test-access",
            aws_secret_access_key="test-secret",
            config=Config(signature_version="s3v4"),
        )
        client.create_bucket(Bucket="tam-forge-test")
        racing_client = ConflictOnceClient(client)
        store = S3ObjectStore(
            endpoint_url=None,
            region="us-east-1",
            bucket="tam-forge-test",
            access_key="test-access",
            secret_key="test-secret",
            client=racing_client,  # type: ignore[arg-type]
        )
        payload = b"race-safe"
        digest = hashlib.sha256(payload).hexdigest()
        key = build_object_key(
            artifact_class="recording-segment",
            owner_id="0191af17-cc6e-7da1-a9d0-b0e542bc7460",
            logical_id="track-1-seq-0-49",
            sha256=digest,
        )

        stored = await store.put_immutable(
            key=key,
            body=chunks(payload),
            sha256=digest,
            content_type="application/octet-stream",
            metadata={},
        )

        assert stored.sha256 == digest
        assert racing_client.put_calls == 2


def test_adapter_repr_never_contains_credentials_or_signed_urls() -> None:
    from tamforge_backend.storage.s3 import S3ObjectStore

    store = S3ObjectStore(
        endpoint_url="https://objects.example.test",
        region="eu-central-1",
        bucket="tam-forge",
        access_key="do-not-leak-access",
        secret_key="do-not-leak-secret",
    )

    rendered = repr(store)
    assert "do-not-leak-access" not in rendered
    assert "do-not-leak-secret" not in rendered


def test_presigned_request_repr_redacts_url() -> None:
    from tamforge_backend.storage.models import PresignedRequest

    request = PresignedRequest(
        url="https://signed.example.test/private?signature=do-not-leak",
        method="PUT",
        headers={},
        expires_seconds=60,
    )

    assert "signed.example.test" not in repr(request)
    assert "do-not-leak" not in repr(request)


def test_runtime_import_does_not_require_boto_stubs() -> None:
    source_root = Path(__file__).resolve().parents[3] / "src"
    script = """
import builtins
real_import = builtins.__import__
def guarded(name, *args, **kwargs):
    if name.startswith('mypy_boto3_s3'):
        raise AssertionError('runtime imported boto stubs')
    return real_import(name, *args, **kwargs)
builtins.__import__ = guarded
import tamforge_backend.storage.s3
"""
    environment = {**os.environ, "PYTHONPATH": str(source_root)}

    result = subprocess.run(
        [sys.executable, "-c", script],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.anyio
async def test_s3_put_and_stat_use_provider_validated_sha256(
    moto_s3_client: Any,
) -> None:
    from tamforge_backend.storage.models import build_object_key
    from tamforge_backend.storage.s3 import S3ObjectStore

    store = S3ObjectStore(
        endpoint_url=None,
        region="us-east-1",
        bucket="tam-forge-test",
        access_key="test-access",
        secret_key="test-secret",
        client=moto_s3_client,
    )
    payload = b"provider-checksum"
    digest = hashlib.sha256(payload).hexdigest()
    expected_checksum = b64encode(bytes.fromhex(digest)).decode("ascii")
    key = build_object_key(
        artifact_class="roadmap-source",
        owner_id="0191af17-cc6e-7da1-a9d0-b0e542bc7460",
        logical_id="month-1-v1",
        sha256=digest,
    )

    await store.put_immutable(
        key=key,
        body=chunks(payload),
        sha256=digest,
        content_type="text/plain",
        metadata={},
    )
    stored = await store.stat(key)

    assert stored is not None
    assert moto_s3_client.last_put_kwargs is not None
    assert moto_s3_client.last_put_kwargs["ChecksumSHA256"] == expected_checksum
    assert moto_s3_client.last_head_kwargs is not None
    assert moto_s3_client.last_head_kwargs["ChecksumMode"] == "ENABLED"


@pytest.mark.anyio
async def test_presigned_put_binds_native_checksum_and_private_acl(
    s3_store: object,
) -> None:
    from tamforge_backend.storage.models import PresignPutRequest, build_object_key
    from tamforge_backend.storage.ports import ObjectStore

    store: ObjectStore = s3_store  # type: ignore[assignment]
    digest = hashlib.sha256(b"signed-checksum").hexdigest()
    expected_checksum = b64encode(bytes.fromhex(digest)).decode("ascii")
    key = build_object_key(
        artifact_class="written-artifact",
        owner_id="0191af17-cc6e-7da1-a9d0-b0e542bc7460",
        logical_id="attempt-a",
        sha256=digest,
    )

    signed = await store.presign_put(
        PresignPutRequest(
            key=key,
            sha256=digest,
            byte_length=15,
            content_type="text/plain",
            metadata={},
            expires_seconds=60,
        )
    )
    signed_headers = parse_qs(urlsplit(signed.url).query)["X-Amz-SignedHeaders"][0].split(";")

    assert signed.headers["x-amz-checksum-sha256"] == expected_checksum
    assert signed.headers["x-amz-acl"] == "private"
    assert "x-amz-checksum-sha256" in signed_headers
    assert "x-amz-acl" in signed_headers


@pytest.mark.anyio
@pytest.mark.parametrize("checksum", (None, b64encode(b"x" * 32).decode("ascii")))
async def test_stat_rejects_missing_or_mismatched_provider_checksum(
    moto_s3_client: Any,
    checksum: str | None,
) -> None:
    from tamforge_backend.storage.models import ObjectIntegrityError, build_object_key
    from tamforge_backend.storage.s3 import S3ObjectStore

    payload = b"provider-checksum"
    digest = hashlib.sha256(payload).hexdigest()
    key = build_object_key(
        artifact_class="roadmap-source",
        owner_id="0191af17-cc6e-7da1-a9d0-b0e542bc7460",
        logical_id="month-1-v1",
        sha256=digest,
    )
    moto_s3_client._client.put_object(
        Bucket="tam-forge-test",
        Key=key,
        Body=payload,
        ContentType="text/plain",
        Metadata={"sha256": digest, "byte-length": str(len(payload))},
    )
    if checksum is not None:
        moto_s3_client.checksums[("tam-forge-test", key)] = checksum
    store = S3ObjectStore(
        endpoint_url=None,
        region="us-east-1",
        bucket="tam-forge-test",
        access_key="test-access",
        secret_key="test-secret",
        client=moto_s3_client,
    )

    with pytest.raises(ObjectIntegrityError):
        await store.stat(key)


def test_moto_checksum_gap_is_filled_by_direct_bad_digest_rejection(
    moto_s3_client: Any,
) -> None:
    wrong_checksum = b64encode(b"x" * 32).decode("ascii")

    with pytest.raises(ClientError) as exc_info:
        moto_s3_client.put_object(
            Bucket="tam-forge-test",
            Key="wrong-checksum",
            Body=b"actual-body",
            ChecksumSHA256=wrong_checksum,
        )

    assert exc_info.value.response["Error"]["Code"] == "BadDigest"


@pytest.mark.anyio
async def test_upload_limiter_bounds_aggregate_spool_use(
    moto_s3_client: Any,
) -> None:
    from tamforge_backend.storage.models import build_object_key
    from tamforge_backend.storage.s3 import S3ObjectStore

    store = S3ObjectStore(
        endpoint_url=None,
        region="us-east-1",
        bucket="tam-forge-test",
        access_key="test-access",
        secret_key="test-secret",
        max_concurrent_uploads=1,
        client=moto_s3_client,
    )
    active = 0
    maximum_active = 0

    async def tracked_body(payload: bytes) -> AsyncIterator[bytes]:
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        try:
            await anyio.sleep(0.01)
            yield payload
        finally:
            active -= 1

    async def upload(logical_id: str) -> None:
        payload = logical_id.encode()
        digest = hashlib.sha256(payload).hexdigest()
        await store.put_immutable(
            key=build_object_key(
                artifact_class="archive",
                owner_id="0191af17-cc6e-7da1-a9d0-b0e542bc7460",
                logical_id=logical_id,
                sha256=digest,
            ),
            body=tracked_body(payload),
            sha256=digest,
            content_type="application/octet-stream",
            metadata={},
        )

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(upload, "first")
        task_group.start_soon(upload, "second")

    assert maximum_active == 1


@pytest.mark.anyio
async def test_spool_open_oserror_is_mapped_to_generic_error(
    monkeypatch: pytest.MonkeyPatch,
    moto_s3_client: Any,
) -> None:
    from tamforge_backend.storage.models import ObjectStoreError, build_object_key
    from tamforge_backend.storage.s3 import S3ObjectStore

    def fail_open(*args: object, **kwargs: object) -> object:
        raise OSError("sensitive temp path")

    monkeypatch.setattr("tamforge_backend.storage.s3.SpooledTemporaryFile", fail_open)
    payload = b"spool"
    digest = hashlib.sha256(payload).hexdigest()
    store = S3ObjectStore(
        endpoint_url=None,
        region="us-east-1",
        bucket="tam-forge-test",
        access_key="test-access",
        secret_key="test-secret",
        client=moto_s3_client,
    )

    with pytest.raises(ObjectStoreError, match="temporary spool failed") as exc_info:
        await store.put_immutable(
            key=build_object_key(
                artifact_class="archive",
                owner_id="0191af17-cc6e-7da1-a9d0-b0e542bc7460",
                logical_id="spool",
                sha256=digest,
            ),
            body=chunks(payload),
            sha256=digest,
            content_type="application/octet-stream",
            metadata={},
        )

    assert "sensitive temp path" not in str(exc_info.value)


@pytest.mark.anyio
@pytest.mark.parametrize("operation", ("write", "seek", "read", "close"))
async def test_spool_io_oserror_is_mapped_to_generic_error(
    monkeypatch: pytest.MonkeyPatch,
    moto_s3_client: Any,
    operation: str,
) -> None:
    from tamforge_backend.storage.models import ObjectStoreError, build_object_key
    from tamforge_backend.storage.s3 import S3ObjectStore

    monkeypatch.setattr(
        "tamforge_backend.storage.s3.SpooledTemporaryFile",
        lambda *args, **kwargs: FailingSpool(operation),
    )
    payload = b"spool-io"
    digest = hashlib.sha256(payload).hexdigest()
    store = S3ObjectStore(
        endpoint_url=None,
        region="us-east-1",
        bucket="tam-forge-test",
        access_key="test-access",
        secret_key="test-secret",
        client=moto_s3_client,
    )

    with pytest.raises(ObjectStoreError, match="temporary spool failed") as exc_info:
        await store.put_immutable(
            key=build_object_key(
                artifact_class="archive",
                owner_id="0191af17-cc6e-7da1-a9d0-b0e542bc7460",
                logical_id=f"spool-{operation}",
                sha256=digest,
            ),
            body=chunks(payload),
            sha256=digest,
            content_type="application/octet-stream",
            metadata={},
        )

    assert "sensitive" not in str(exc_info.value)


@pytest.mark.anyio
async def test_spool_close_failure_does_not_mask_primary_integrity_error(
    monkeypatch: pytest.MonkeyPatch,
    moto_s3_client: Any,
) -> None:
    from tamforge_backend.storage.models import ObjectIntegrityError, build_object_key
    from tamforge_backend.storage.s3 import S3ObjectStore

    monkeypatch.setattr(
        "tamforge_backend.storage.s3.SpooledTemporaryFile",
        lambda *args, **kwargs: FailingSpool("close"),
    )
    declared_digest = hashlib.sha256(b"declared").hexdigest()
    store = S3ObjectStore(
        endpoint_url=None,
        region="us-east-1",
        bucket="tam-forge-test",
        access_key="test-access",
        secret_key="test-secret",
        client=moto_s3_client,
    )

    with pytest.raises(ObjectIntegrityError):
        await store.put_immutable(
            key=build_object_key(
                artifact_class="archive",
                owner_id="0191af17-cc6e-7da1-a9d0-b0e542bc7460",
                logical_id="spool-primary",
                sha256=declared_digest,
            ),
            body=chunks(b"different"),
            sha256=declared_digest,
            content_type="application/octet-stream",
            metadata={},
        )

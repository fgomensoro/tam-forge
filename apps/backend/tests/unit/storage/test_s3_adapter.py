from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator

import boto3
import pytest
from botocore.client import Config
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


@pytest.fixture
def s3_store() -> object:
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
        yield S3ObjectStore(
            endpoint_url=None,
            region="us-east-1",
            bucket="tam-forge-test",
            access_key="test-access",
            secret_key="test-secret",
            client=client,
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
    assert "x-amz-acl" not in signed.headers
    assert "X-Amz-Signature" in signed.url


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

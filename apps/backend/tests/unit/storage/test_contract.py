from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Callable, Iterator

import anyio
import pytest


async def chunks(*values: bytes) -> AsyncIterator[bytes]:
    for value in values:
        yield value


async def read_all(stream: AsyncIterator[bytes]) -> bytes:
    return b"".join([chunk async for chunk in stream])


@pytest.fixture(params=("memory", "s3"))
def object_store_factory(request: pytest.FixtureRequest) -> Iterator[Callable[[], object]]:
    from tamforge_backend.storage.fake import InMemoryObjectStore

    if request.param == "memory":
        yield InMemoryObjectStore
        return

    from tamforge_backend.storage.s3 import S3ObjectStore

    client = request.getfixturevalue("moto_s3_client")
    yield lambda: S3ObjectStore(
        endpoint_url=None,
        region="us-east-1",
        bucket="tam-forge-test",
        access_key="test-access",
        secret_key="test-secret",
        client=client,
    )


def test_server_generated_key_is_scoped_and_rejects_unsafe_inputs() -> None:
    from tamforge_backend.storage.models import InvalidObjectKey, build_object_key

    digest = "a" * 64
    assert build_object_key(
        artifact_class="roadmap-source",
        owner_id="0191af17-cc6e-7da1-a9d0-b0e542bc7460",
        logical_id="month-1-v1",
        sha256=digest,
    ) == (
        "roadmap-source/0191af17-cc6e-7da1-a9d0-b0e542bc7460/month-1-v1/"
        f"{digest}"
    )

    unsafe_values = ("", "/absolute", "../escape", "with/slash", "line\nbreak", "nul\0byte")
    for value in unsafe_values:
        with pytest.raises(InvalidObjectKey):
            build_object_key(
                artifact_class="roadmap-source",
                owner_id=value,
                logical_id="month-1-v1",
                sha256=digest,
            )


@pytest.mark.anyio
async def test_identical_key_and_content_is_idempotent(
    object_store_factory: Callable[[], object],
) -> None:
    from tamforge_backend.storage.models import build_object_key
    from tamforge_backend.storage.ports import ObjectStore

    store: ObjectStore = object_store_factory()  # type: ignore[assignment,operator]
    payload = b"immutable-source"
    digest = hashlib.sha256(payload).hexdigest()
    key = build_object_key(
        artifact_class="roadmap-source",
        owner_id="0191af17-cc6e-7da1-a9d0-b0e542bc7460",
        logical_id="month-1-v1",
        sha256=digest,
    )

    first = await store.put_immutable(
        key=key,
        body=chunks(payload[:5], payload[5:]),
        sha256=digest,
        content_type="text/markdown",
        metadata={"source": "obsidian"},
    )
    second = await store.put_immutable(
        key=key,
        body=chunks(payload),
        sha256=digest,
        content_type="text/markdown",
        metadata={"source": "obsidian"},
    )

    assert second == first
    assert first.sha256 == digest
    assert first.byte_length == len(payload)
    assert first.metadata["sha256"] == digest
    assert first.metadata["byte-length"] == str(len(payload))


@pytest.mark.anyio
async def test_same_key_with_different_content_conflicts(
    object_store_factory: Callable[[], object],
) -> None:
    from tamforge_backend.storage.models import ObjectConflict, build_object_key
    from tamforge_backend.storage.ports import ObjectStore

    store: ObjectStore = object_store_factory()  # type: ignore[assignment,operator]
    first_payload = b"first"
    second_payload = b"second"
    first_digest = hashlib.sha256(first_payload).hexdigest()
    second_digest = hashlib.sha256(second_payload).hexdigest()
    key = build_object_key(
        artifact_class="roadmap-source",
        owner_id="0191af17-cc6e-7da1-a9d0-b0e542bc7460",
        logical_id="month-1-v1",
        sha256=first_digest,
    )
    await store.put_immutable(
        key=key,
        body=chunks(first_payload),
        sha256=first_digest,
        content_type="text/plain",
        metadata={},
    )

    with pytest.raises(ObjectConflict):
        await store.put_immutable(
            key=key,
            body=chunks(second_payload),
            sha256=second_digest,
            content_type="text/plain",
            metadata={},
        )


@pytest.mark.anyio
async def test_same_content_with_different_metadata_conflicts(
    object_store_factory: Callable[[], object],
) -> None:
    from tamforge_backend.storage.models import ObjectConflict, build_object_key
    from tamforge_backend.storage.ports import ObjectStore

    store: ObjectStore = object_store_factory()  # type: ignore[assignment,operator]
    payload = b"same"
    digest = hashlib.sha256(payload).hexdigest()
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
        metadata={"source": "obsidian"},
    )

    with pytest.raises(ObjectConflict):
        await store.put_immutable(
            key=key,
            body=chunks(payload),
            sha256=digest,
            content_type="text/plain",
            metadata={"source": "different"},
        )


@pytest.mark.anyio
async def test_concurrent_identical_create_is_race_safe(
    object_store_factory: Callable[[], object],
) -> None:
    from tamforge_backend.storage.models import StoredObject, build_object_key
    from tamforge_backend.storage.ports import ObjectStore

    store: ObjectStore = object_store_factory()  # type: ignore[assignment,operator]
    payload = b"concurrent"
    digest = hashlib.sha256(payload).hexdigest()
    key = build_object_key(
        artifact_class="recording-segment",
        owner_id="0191af17-cc6e-7da1-a9d0-b0e542bc7460",
        logical_id="track-1-seq-0-49",
        sha256=digest,
    )
    results: list[StoredObject] = []

    async def upload() -> None:
        results.append(
            await store.put_immutable(
                key=key,
                body=chunks(payload),
                sha256=digest,
                content_type="application/octet-stream",
                metadata={},
            )
        )

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(upload)
        task_group.start_soon(upload)

    assert len(results) == 2
    assert results[0] == results[1]


@pytest.mark.anyio
async def test_declared_checksum_must_match_streamed_body(
    object_store_factory: Callable[[], object],
) -> None:
    from tamforge_backend.storage.models import ObjectIntegrityError, build_object_key
    from tamforge_backend.storage.ports import ObjectStore

    store: ObjectStore = object_store_factory()  # type: ignore[assignment,operator]
    declared_digest = hashlib.sha256(b"declared").hexdigest()
    key = build_object_key(
        artifact_class="roadmap-source",
        owner_id="0191af17-cc6e-7da1-a9d0-b0e542bc7460",
        logical_id="month-1-v1",
        sha256=declared_digest,
    )

    with pytest.raises(ObjectIntegrityError):
        await store.put_immutable(
            key=key,
            body=chunks(b"different"),
            sha256=declared_digest,
            content_type="text/plain",
            metadata={},
        )

    assert await store.stat(key) is None


@pytest.mark.anyio
async def test_fresh_key_must_bind_its_terminal_hash_to_declared_digest(
    object_store_factory: Callable[[], object],
) -> None:
    from tamforge_backend.storage.models import ObjectIntegrityError, build_object_key
    from tamforge_backend.storage.ports import ObjectStore

    store: ObjectStore = object_store_factory()  # type: ignore[assignment,operator]
    key_digest = hashlib.sha256(b"key-content").hexdigest()
    body = b"different-content"
    body_digest = hashlib.sha256(body).hexdigest()
    key = build_object_key(
        artifact_class="roadmap-source",
        owner_id="0191af17-cc6e-7da1-a9d0-b0e542bc7460",
        logical_id="month-1-v1",
        sha256=key_digest,
    )

    with pytest.raises(ObjectIntegrityError):
        await store.put_immutable(
            key=key,
            body=chunks(body),
            sha256=body_digest,
            content_type="text/plain",
            metadata={},
        )

    assert await store.stat(key) is None


def test_presign_request_binds_key_terminal_hash_to_declared_digest() -> None:
    from tamforge_backend.storage.models import (
        ObjectIntegrityError,
        PresignPutRequest,
        build_object_key,
    )

    key_digest = hashlib.sha256(b"key-content").hexdigest()
    declared_digest = hashlib.sha256(b"different-content").hexdigest()
    key = build_object_key(
        artifact_class="written-artifact",
        owner_id="0191af17-cc6e-7da1-a9d0-b0e542bc7460",
        logical_id="attempt-a",
        sha256=key_digest,
    )

    with pytest.raises(ObjectIntegrityError):
        PresignPutRequest(
            key=key,
            sha256=declared_digest,
            byte_length=17,
            content_type="text/plain",
            metadata={},
        )


@pytest.mark.parametrize(
    "metadata",
    (
        {"language": "español"},
        {"first": "x" * 1000, "second": "y" * 1000},
    ),
)
def test_metadata_is_ascii_and_two_kibibytes_including_integrity_fields(
    metadata: dict[str, str],
) -> None:
    from tamforge_backend.storage.models import InvalidObjectMetadata, PresignPutRequest

    digest = hashlib.sha256(b"metadata").hexdigest()
    key = (
        "written-artifact/0191af17-cc6e-7da1-a9d0-b0e542bc7460/attempt-a/"
        f"{digest}"
    )

    with pytest.raises(InvalidObjectMetadata):
        PresignPutRequest(
            key=key,
            sha256=digest,
            byte_length=8,
            content_type="text/plain",
            metadata=metadata,
        )


@pytest.mark.anyio
async def test_open_streams_content_in_bounded_chunks(
    object_store_factory: Callable[[], object],
) -> None:
    from tamforge_backend.storage.models import build_object_key
    from tamforge_backend.storage.ports import ObjectStore

    store: ObjectStore = object_store_factory()  # type: ignore[assignment,operator]
    payload = b"x" * 150_000
    digest = hashlib.sha256(payload).hexdigest()
    key = build_object_key(
        artifact_class="archive",
        owner_id="0191af17-cc6e-7da1-a9d0-b0e542bc7460",
        logical_id="export-v1",
        sha256=digest,
    )
    await store.put_immutable(
        key=key,
        body=chunks(payload),
        sha256=digest,
        content_type="application/octet-stream",
        metadata={},
    )

    async with store.open(key) as stream:
        received_chunks = [chunk async for chunk in stream]

    assert b"".join(received_chunks) == payload
    assert len(received_chunks) > 1
    assert max(map(len, received_chunks)) <= 64 * 1024


@pytest.mark.anyio
async def test_presigns_are_private_and_expiry_is_bounded(
    object_store_factory: Callable[[], object],
) -> None:
    from tamforge_backend.storage.models import (
        InvalidPresignExpiry,
        PresignPutRequest,
        build_object_key,
    )
    from tamforge_backend.storage.ports import ObjectStore

    store: ObjectStore = object_store_factory()  # type: ignore[assignment,operator]
    digest = hashlib.sha256(b"direct-upload").hexdigest()
    key = build_object_key(
        artifact_class="written-artifact",
        owner_id="0191af17-cc6e-7da1-a9d0-b0e542bc7460",
        logical_id="attempt-a",
        sha256=digest,
    )
    request = PresignPutRequest(
        key=key,
        sha256=digest,
        byte_length=13,
        content_type="text/plain",
        metadata={},
        expires_seconds=300,
    )

    signed_put = await store.presign_put(request)
    signed_get = await store.presign_get(key, expires_seconds=300)

    assert signed_put.method == "PUT"
    assert signed_put.expires_seconds == 300
    assert signed_put.headers["if-none-match"] == "*"
    assert signed_put.headers["x-amz-meta-sha256"] == digest
    assert signed_put.headers["x-amz-meta-byte-length"] == "13"
    assert signed_get
    assert "http" in signed_put.url
    assert "http" in signed_get

    for expiry in (0, 901):
        with pytest.raises(InvalidPresignExpiry):
            await store.presign_get(key, expires_seconds=expiry)


@pytest.mark.anyio
async def test_upload_body_has_a_hard_size_limit() -> None:
    from tamforge_backend.storage.fake import InMemoryObjectStore
    from tamforge_backend.storage.models import ObjectTooLarge, build_object_key

    store = InMemoryObjectStore(max_upload_bytes=4)
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

"""Docker-free ingest failure matrix for native recording parts and seals.

The real ``RecordingService`` runs against ``InMemoryObjectStore`` and an
in-memory repository double. The double reuses the SQL repository's static
helpers and ORM row objects but re-implements its identity, replay, overlap,
high-water, and seal-state rules in Python, so those rules are pinned here as
a regression contract while the service orchestration (decrypt before
reserve, immutable object handling, seal replay) is production code. The
PostgreSQL repository itself is covered by the integration job.
"""

from __future__ import annotations

import pytest
from tamforge_backend.recordings.schemas import (
    RecordingPartReceipt,
)
from tamforge_backend.recordings.service import (
    RecordingConflict,
    RecordingService,
    recording_part_object_key,
)
from tamforge_backend.testing.recordings import (
    OWNER_ID,
    SYSTEM_ID,
    InMemoryRecordingRepository,
    encrypted_part,
    seal_command,
    started_service,
    upload,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def test_identical_duplicate_part_is_idempotent_and_never_rewrites_storage() -> None:
    service, _, store, recording_id = await started_service()
    part = encrypted_part(recording_id=recording_id)

    first = await upload(service, part, "part-0")
    second = await upload(service, part, "part-0")

    assert first.replayed is False
    assert second.replayed is True
    assert second.model_copy(update={"replayed": False}) == first
    assert first.high_water_sample == 8
    assert store.put_calls == 1


async def test_conflicting_duplicate_bytes_fail_closed_without_touching_stored_audio() -> None:
    service, repository, store, recording_id = await started_service()
    original = encrypted_part(recording_id=recording_id)
    conflicting = encrypted_part(recording_id=recording_id, marker=9)
    await upload(service, original, "part-0")

    with pytest.raises(RecordingConflict):
        await upload(service, conflicting, "part-0")
    with pytest.raises(RecordingConflict):
        await upload(service, conflicting, "part-0-retry")

    assert store.put_calls == 1
    stored = await store.stat(recording_part_object_key(owner_id=OWNER_ID, metadata=original[0]))
    assert stored is not None
    assert stored.sha256 == original[0].plaintext_sha256
    assert [item.sequence for item in repository.parts] == [0]
    assert (
        await store.stat(recording_part_object_key(owner_id=OWNER_ID, metadata=conflicting[0]))
        is None
    )


async def test_reordered_parts_cannot_advance_high_water_past_a_hidden_gap() -> None:
    service, _, _, recording_id = await started_service()
    late = encrypted_part(recording_id=recording_id, sequence=1, sample_start=8)
    early = encrypted_part(recording_id=recording_id, sequence=0, sample_start=0)
    overlapping = encrypted_part(recording_id=recording_id, sequence=2, sample_start=12, marker=5)

    late_receipt = await upload(service, late, "part-1")
    assert late_receipt.high_water_sample == 0
    status = await service.status(owner_id=OWNER_ID, recording_id=recording_id)
    assert status.tracks[0].high_water_sample == 0
    assert status.tracks[0].stored_part_count == 1

    early_receipt = await upload(service, early, "part-0")
    assert early_receipt.high_water_sample == 16

    with pytest.raises(RecordingConflict):
        await upload(service, overlapping, "part-2")
    status = await service.status(owner_id=OWNER_ID, recording_id=recording_id)
    assert status.tracks[0].high_water_sample == 16
    assert status.tracks[0].stored_part_count == 2


async def test_corrupt_ciphertext_hash_or_length_never_reaches_immutable_storage() -> None:
    service, repository, store, recording_id = await started_service()
    metadata, _, ciphertext, _ = part = encrypted_part(recording_id=recording_id)
    tampered = ciphertext[:-1] + bytes([ciphertext[-1] ^ 0x01])
    wrong_hash = metadata.model_copy(update={"ciphertext_sha256": "1" * 64})
    wrong_length = metadata.model_copy(update={"ciphertext_byte_length": len(ciphertext) - 1})

    with pytest.raises(RecordingConflict):
        await upload(service, part, "part-0", ciphertext=tampered)
    with pytest.raises(RecordingConflict):
        await upload(service, part, "part-0", metadata=wrong_hash)
    with pytest.raises(RecordingConflict):
        await upload(service, part, "part-0", metadata=wrong_length)

    assert store.put_calls == 0
    assert repository.parts == []
    status = await service.status(owner_id=OWNER_ID, recording_id=recording_id)
    assert status.state == "reserved"
    assert all(track.stored_part_count == 0 for track in status.tracks)


async def test_seal_replay_returns_the_same_receipt_and_rejects_a_reused_identity() -> None:
    service, _, store, recording_id = await started_service()
    microphone = encrypted_part(recording_id=recording_id)
    system = encrypted_part(
        recording_id=recording_id, track_id=SYSTEM_ID, track_kind="system_audio", channel_count=2
    )
    await upload(service, microphone, "mic-0")
    await upload(service, system, "sys-0")
    command = seal_command(recording_id, [(microphone[0], microphone[3])], [(system[0], system[3])])

    first = await service.seal(owner_id=OWNER_ID, command=command, idempotency_key="seal-1")
    replayed = await service.seal(owner_id=OWNER_ID, command=command, idempotency_key="seal-1")

    assert first.replayed is False
    assert replayed.replayed is True
    assert replayed.model_copy(update={"replayed": False}) == first
    assert first.audio_created_on_server is True
    assert first.transcript_lineage_accepted is False
    assert store.put_calls == 4  # two parts and two manifests, never rewritten
    with pytest.raises(RecordingConflict):
        await service.seal(owner_id=OWNER_ID, command=command, idempotency_key="seal-2")
    with pytest.raises(RecordingConflict):
        await upload(
            service, encrypted_part(recording_id=recording_id, sequence=1, sample_start=8), "mic-1"
        )


async def test_service_restart_resumes_durable_state_without_choosing_between_bytes() -> None:
    _, repository, store, recording_id = await started_service()
    part = encrypted_part(recording_id=recording_id)
    conflicting = encrypted_part(recording_id=recording_id, marker=9)

    class CrashAfterObjectWrite(InMemoryRecordingRepository):
        async def finalize_part(self, **kwargs: object) -> RecordingPartReceipt:
            raise RuntimeError("process lost before the part was finalized")

    crashing = CrashAfterObjectWrite()
    crashing.__dict__.update(repository.__dict__)
    with pytest.raises(RuntimeError):
        await upload(RecordingService(crashing, store), part, "part-0")  # type: ignore[arg-type]
    assert store.put_calls == 1
    assert [item.state for item in repository.parts] == ["reserved"]

    restarted = RecordingService(repository, store)  # type: ignore[arg-type]
    status = await restarted.status(owner_id=OWNER_ID, recording_id=recording_id)
    assert status.state == "uploading"
    assert status.tracks[0].high_water_sample == 0

    with pytest.raises(RecordingConflict):
        await upload(restarted, conflicting, "part-0")
    with pytest.raises(RecordingConflict):
        await upload(restarted, conflicting, "part-0-b")
    assert store.put_calls == 1

    resumed = await upload(restarted, part, "part-0")
    assert resumed.replayed is False
    assert resumed.high_water_sample == 8
    assert store.put_calls == 1
    stored = await store.stat(recording_part_object_key(owner_id=OWNER_ID, metadata=part[0]))
    assert stored is not None
    assert stored.sha256 == part[0].plaintext_sha256
    pending = await restarted.pending(owner_id=OWNER_ID)
    assert [item.recording_id for item in pending] == [recording_id]

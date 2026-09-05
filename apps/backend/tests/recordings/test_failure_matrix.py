"""Docker-free ingest failure matrix for native recording parts and seals.

The real ``RecordingService`` runs against ``InMemoryObjectStore`` and an
in-memory repository double that keeps the SQL repository's identity, replay,
and high-water rules (it reuses the repository's static helpers and ORM row
objects). PostgreSQL durability itself is covered by the integration job.
"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from uuid import UUID, uuid4

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from tamforge_backend.recordings.contracts import part_aad_bytes, timeline_sha256
from tamforge_backend.recordings.models import Recording, RecordingPart, RecordingTrack
from tamforge_backend.recordings.repository import (
    PartReservation,
    SealSnapshot,
    SqlAlchemyRecordingRepository,
    StoredPartSnapshot,
    _same_format,
)
from tamforge_backend.recordings.schemas import (
    RecordingCreateCommand,
    RecordingCreateResponse,
    RecordingPartReceipt,
    RecordingPartUploadMetadata,
    RecordingSealCommand,
    RecordingSealResponse,
    RecordingStatusResponse,
    RecordingTrackManifest,
)
from tamforge_backend.recordings.service import (
    RecordingConflict,
    RecordingNotFound,
    RecordingService,
    recording_part_object_key,
)
from tamforge_backend.storage.fake import InMemoryObjectStore

pytestmark = pytest.mark.anyio

OWNER_ID = 7
MICROPHONE_ID = UUID("22222222-2222-4222-8222-222222222222")
SYSTEM_ID = UUID("33333333-3333-4333-8333-333333333333")
STARTED_AT = datetime(2026, 9, 1, 16, tzinfo=UTC)
TIMESCALE = 1_000_000_000


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class InMemoryRecordingRepository:
    """Repository double: dict rows, same identity/replay/high-water rules."""

    def __init__(self) -> None:
        self.recordings: list[Recording] = []
        self.tracks: list[RecordingTrack] = []
        self.parts: list[RecordingPart] = []
        self.gaps: list[tuple[int, int, int, str]] = []
        self._next_id = 1

    def _id(self) -> int:
        self._next_id += 1
        return self._next_id

    def _recording(self, owner_id: int, recording_id: UUID) -> Recording:
        for item in self.recordings:
            if item.owner_id == owner_id and item.client_recording_id == recording_id:
                return item
        raise RecordingNotFound("recording was not found")

    def _track(self, recording: Recording, track_id: UUID) -> RecordingTrack:
        for item in self.tracks:
            if item.recording_id == recording.id and item.client_track_id == track_id:
                return item
        raise RecordingNotFound("recording track was not found")

    def _track_parts(self, track: RecordingTrack) -> list[RecordingPart]:
        return [item for item in self.parts if item.track_id == track.id]

    async def create(
        self,
        *,
        owner_id: int,
        command: RecordingCreateCommand,
        idempotency_key: str,
        request_hash: bytes,
    ) -> RecordingCreateResponse:
        for existing in self.recordings:
            if existing.owner_id != owner_id:
                continue
            if (
                existing.client_recording_id != command.recording_id
                and existing.create_idempotency_key != idempotency_key
            ):
                continue
            if (
                existing.client_recording_id != command.recording_id
                or existing.create_idempotency_key != idempotency_key
                or existing.create_request_hash != request_hash
            ):
                raise RecordingConflict("recording create identity was reused")
            return RecordingCreateResponse.model_validate(existing.create_result_json).model_copy(
                update={"replayed": True}
            )
        result = RecordingCreateResponse(
            recording_id=command.recording_id, state="reserved", replayed=False
        )
        recording = Recording(
            id=self._id(),
            owner_id=owner_id,
            client_recording_id=command.recording_id,
            schema_version=command.schema_version,
            state="reserved",
            started_at=command.started_at,
            create_idempotency_key=idempotency_key,
            create_request_hash=request_hash,
            create_result_json=result.model_dump(mode="json"),
            audio_created_on_server=False,
            transcript_lineage_accepted=False,
        )
        self.recordings.append(recording)
        for declaration in command.tracks:
            self.tracks.append(
                RecordingTrack(
                    id=self._id(),
                    owner_id=owner_id,
                    recording_id=recording.id,
                    client_track_id=declaration.track_id,
                    schema_version=command.schema_version,
                    kind=declaration.kind,
                    sample_encoding=declaration.format.sample_encoding,
                    sample_rate_hz=declaration.format.sample_rate_hz,
                    channel_count=declaration.format.channel_count,
                    interleaved=declaration.format.interleaved,
                    conversion_version=declaration.conversion_version,
                    state="reserved",
                    high_water_sample=0,
                    stored_part_count=0,
                    stored_byte_length=0,
                )
            )
        return result

    async def reserve_part(
        self,
        *,
        owner_id: int,
        metadata: RecordingPartUploadMetadata,
        object_key: str,
        idempotency_key: str,
        request_hash: bytes,
    ) -> PartReservation:
        recording = self._recording(owner_id, metadata.recording_id)
        track = self._track(recording, metadata.track_id)
        if recording.state in {"sealing", "stored", "stored_with_gaps"}:
            raise RecordingConflict("recording no longer accepts parts")
        if not _same_format(track, metadata):
            raise RecordingConflict("recording part format does not match its track")
        for existing in self._track_parts(track):
            if (
                existing.sequence != metadata.sequence
                and existing.idempotency_key != idempotency_key
            ):
                continue
            if not SqlAlchemyRecordingRepository._same_part(
                existing,
                metadata=metadata,
                object_key=object_key,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
            ):
                raise RecordingConflict("recording part identity was reused")
            return SqlAlchemyRecordingRepository._reservation(recording, track, existing)
        for existing in self._track_parts(track):
            if (
                existing.sample_start < metadata.sample_start + metadata.sample_count
                and existing.sample_start + existing.sample_count > metadata.sample_start
            ):
                raise RecordingConflict("recording part range overlaps existing audio")
        part = RecordingPart(
            id=self._id(),
            owner_id=owner_id,
            recording_id=recording.id,
            track_id=track.id,
            schema_version=metadata.schema_version,
            sequence=metadata.sequence,
            sample_start=metadata.sample_start,
            sample_count=metadata.sample_count,
            byte_length=metadata.byte_length,
            ciphertext_byte_length=metadata.ciphertext_byte_length,
            plaintext_sha256=bytes.fromhex(metadata.plaintext_sha256),
            ciphertext_sha256=bytes.fromhex(metadata.ciphertext_sha256),
            encryption_version=metadata.encryption_version,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            object_key=object_key,
            state="reserved",
        )
        self.parts.append(part)
        recording.state = "uploading"
        track.state = "uploading"
        return SqlAlchemyRecordingRepository._reservation(recording, track, part)

    async def finalize_part(
        self,
        *,
        owner_id: int,
        metadata: RecordingPartUploadMetadata,
        object_key: str,
        idempotency_key: str,
    ) -> RecordingPartReceipt:
        recording = self._recording(owner_id, metadata.recording_id)
        track = self._track(recording, metadata.track_id)
        part = next(
            (item for item in self._track_parts(track) if item.sequence == metadata.sequence),
            None,
        )
        if part is None:
            raise RecordingNotFound("recording part reservation was not found")
        if (
            part.idempotency_key != idempotency_key
            or part.object_key != object_key
            or part.plaintext_sha256.hex() != metadata.plaintext_sha256
        ):
            raise RecordingConflict("recording part reservation conflicts")
        if part.state == "stored":
            return RecordingPartReceipt.model_validate(part.result_json).model_copy(
                update={"replayed": True}
            )
        part.state = "stored"
        stored = sorted(
            (item for item in self._track_parts(track) if item.state == "stored"),
            key=lambda item: (item.sample_start, item.sequence),
        )
        cursor = 0
        for item in stored:
            if item.sample_start != cursor:
                break
            cursor += item.sample_count
        track.high_water_sample = cursor
        track.stored_part_count = len(stored)
        track.stored_byte_length = sum(item.byte_length for item in stored)
        receipt = RecordingPartReceipt(
            recording_id=metadata.recording_id,
            track_id=metadata.track_id,
            sequence=metadata.sequence,
            sample_start=metadata.sample_start,
            sample_count=metadata.sample_count,
            plaintext_sha256=metadata.plaintext_sha256,
            high_water_sample=cursor,
            replayed=False,
        )
        part.result_json = receipt.model_dump(mode="json")
        return receipt

    async def prepare_seal(
        self,
        *,
        owner_id: int,
        command: RecordingSealCommand,
        idempotency_key: str,
        request_hash: bytes,
    ) -> SealSnapshot:
        recording = self._recording(owner_id, command.recording_id)
        if recording.state in {"stored", "stored_with_gaps"}:
            if (
                recording.seal_idempotency_key != idempotency_key
                or recording.seal_request_hash != request_hash
                or recording.seal_result_json is None
            ):
                raise RecordingConflict("recording seal identity was reused")
            return SealSnapshot(
                stored_part_hashes=MappingProxyType({}),
                parts=(),
                response=RecordingSealResponse.model_validate(recording.seal_result_json),
            )
        if recording.seal_idempotency_key is not None and (
            recording.seal_idempotency_key != idempotency_key
            or recording.seal_request_hash != request_hash
        ):
            raise RecordingConflict("recording seal identity was reused")
        tracks = [item for item in self.tracks if item.recording_id == recording.id]
        by_track = {item.id: item.client_track_id for item in tracks}
        parts = sorted(
            (item for item in self.parts if item.recording_id == recording.id),
            key=lambda item: (item.track_id, item.sequence),
        )
        if any(item.state != "stored" for item in parts):
            raise RecordingConflict("recording still has unpersisted parts")
        recording.state = "sealing"
        recording.seal_idempotency_key = idempotency_key
        recording.seal_request_hash = request_hash
        return SealSnapshot(
            stored_part_hashes=MappingProxyType(
                {
                    (str(by_track[item.track_id]), item.sequence): item.plaintext_sha256.hex()
                    for item in parts
                }
            ),
            parts=tuple(
                StoredPartSnapshot(
                    track_id=by_track[item.track_id],
                    sequence=item.sequence,
                    byte_length=item.byte_length,
                    object_key=item.object_key,
                )
                for item in parts
            ),
        )

    async def finalize_seal(
        self,
        *,
        owner_id: int,
        command: RecordingSealCommand,
        idempotency_key: str,
        request_hash: bytes,
        recording_manifest_sha256: str,
        manifests: Sequence[tuple[UUID, str, str, int]],
    ) -> RecordingSealResponse:
        del recording_manifest_sha256
        recording = self._recording(owner_id, command.recording_id)
        if (
            recording.state != "sealing"
            or recording.seal_idempotency_key != idempotency_key
            or recording.seal_request_hash != request_hash
        ):
            raise RecordingConflict("recording seal was not reserved")
        digests = {track_id: digest for track_id, _, digest, _ in manifests}
        for track in self.tracks:
            if track.recording_id == recording.id:
                track.state = "stored"
                track.manifest_sha256 = bytes.fromhex(digests[track.client_track_id])
        first, second = (digests[item.track_id] for item in command.tracks)
        result = RecordingSealResponse(
            recording_id=command.recording_id,
            state="stored_with_gaps" if command.coverage_status == "stored_with_gaps" else "stored",
            coverage_status=command.coverage_status,
            track_manifest_sha256=(first, second),
            audio_created_on_server=True,
            transcript_lineage_accepted=False,
            replayed=False,
        )
        recording.state = result.state
        recording.coverage_status = command.coverage_status
        recording.audio_created_on_server = True
        recording.seal_result_json = result.model_dump(mode="json")
        return result

    async def status(self, *, owner_id: int, recording_id: UUID) -> RecordingStatusResponse:
        recording = self._recording(owner_id, recording_id)
        tracks = [item for item in self.tracks if item.recording_id == recording.id]
        return SqlAlchemyRecordingRepository._status(recording, tracks, {})

    async def pending(self, *, owner_id: int) -> tuple[RecordingStatusResponse, ...]:
        return tuple(
            [
                await self.status(owner_id=owner_id, recording_id=item.client_recording_id)
                for item in self.recordings
                if item.owner_id == owner_id
                and item.state in {"reserved", "uploading", "sealing", "needs_attention"}
            ]
        )


class CountingObjectStore(InMemoryObjectStore):
    def __init__(self) -> None:
        super().__init__()
        self.put_calls = 0

    async def put_immutable(self, **kwargs: object) -> object:  # type: ignore[override]
        self.put_calls += 1
        return await super().put_immutable(**kwargs)  # type: ignore[arg-type]


def create_command(recording_id: UUID) -> RecordingCreateCommand:
    return RecordingCreateCommand.model_validate(
        {
            "recording_id": str(recording_id),
            "started_at": STARTED_AT,
            "tracks": [
                {
                    "track_id": str(MICROPHONE_ID),
                    "kind": "microphone",
                    "format": {"channel_count": 1},
                },
                {
                    "track_id": str(SYSTEM_ID),
                    "kind": "system_audio",
                    "format": {"channel_count": 2},
                },
            ],
        }
    )


def encrypted_part(
    *,
    recording_id: UUID,
    track_id: UUID = MICROPHONE_ID,
    track_kind: str = "microphone",
    channel_count: int = 1,
    sequence: int = 0,
    sample_start: int = 0,
    marker: int | None = None,
) -> tuple[RecordingPartUploadMetadata, bytes, bytes, bytes]:
    marker = marker if marker is not None else sequence + (1 if track_kind == "microphone" else 101)
    plaintext = bytes([marker, 0]) * (8 * channel_count)
    key = b"k" * 32
    nonce = bytes([marker]) * 12
    payload = {
        "recording_id": str(recording_id),
        "track_id": str(track_id),
        "track_kind": track_kind,
        "format": {"channel_count": channel_count},
        "sequence": sequence,
        "sample_start": sample_start,
        "sample_count": 8,
        "byte_length": len(plaintext),
        "ciphertext_byte_length": len(plaintext) + 16,
        "plaintext_sha256": hashlib.sha256(plaintext).hexdigest(),
        "ciphertext_sha256": "0" * 64,
        "nonce_base64url": base64.urlsafe_b64encode(nonce).rstrip(b"=").decode(),
        "encryption_version": "aes-256-gcm-hkdf-sha256-v1",
    }
    provisional = RecordingPartUploadMetadata.model_validate(payload)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, part_aad_bytes(provisional))
    metadata = RecordingPartUploadMetadata.model_validate(
        {**payload, "ciphertext_sha256": hashlib.sha256(ciphertext).hexdigest()}
    )
    return metadata, key, ciphertext, plaintext


def track_manifest(
    *,
    track_id: UUID,
    track_kind: str,
    channel_count: int,
    parts: Sequence[tuple[RecordingPartUploadMetadata, bytes]],
) -> RecordingTrackManifest:
    ordered = sorted(parts, key=lambda item: item[0].sequence)
    tick = lambda sample: (sample * TIMESCALE + 24_000) // 48_000  # noqa: E731
    provisional = RecordingTrackManifest.model_validate(
        {
            "track_id": str(track_id),
            "kind": track_kind,
            "format": {"channel_count": channel_count},
            "total_sample_count": max(m.sample_start + m.sample_count for m, _ in ordered),
            "parts": [
                {
                    "sequence": m.sequence,
                    "sample_start": m.sample_start,
                    "sample_count": m.sample_count,
                    "byte_length": m.byte_length,
                    "plaintext_sha256": m.plaintext_sha256,
                }
                for m, _ in ordered
            ],
            "gaps": [],
            "source_lineage": [
                {
                    "sample_start": m.sample_start,
                    "sample_count": m.sample_count,
                    "source_sample_rate_hz": 48_000,
                    "source_channel_count": channel_count,
                    "device_id": f"fixture:{track_kind}",
                    "route": "fixture:route",
                    "presentation_time_start": tick(m.sample_start),
                    "presentation_time_end": tick(m.sample_start + m.sample_count),
                    "presentation_time_timescale": TIMESCALE,
                    "conversion_version": "tamforge-pcm16-v1",
                }
                for m, _ in ordered
            ],
            "pcm_sha256": hashlib.sha256(b"".join(p for _, p in ordered)).hexdigest(),
            "timeline_sha256": "0" * 64,
            "conversion_version": "tamforge-pcm16-v1",
        }
    )
    return provisional.model_copy(update={"timeline_sha256": timeline_sha256(provisional)})


def seal_command(
    recording_id: UUID,
    microphone_parts: Sequence[tuple[RecordingPartUploadMetadata, bytes]],
    system_parts: Sequence[tuple[RecordingPartUploadMetadata, bytes]],
) -> RecordingSealCommand:
    return RecordingSealCommand.model_validate(
        {
            "recording_id": str(recording_id),
            "started_at": STARTED_AT,
            "ended_at": STARTED_AT + timedelta(seconds=1),
            "coverage_status": "complete",
            "tracks": (
                track_manifest(
                    track_id=MICROPHONE_ID,
                    track_kind="microphone",
                    channel_count=1,
                    parts=microphone_parts,
                ),
                track_manifest(
                    track_id=SYSTEM_ID,
                    track_kind="system_audio",
                    channel_count=2,
                    parts=system_parts,
                ),
            ),
        }
    )


async def started_service() -> tuple[
    RecordingService, InMemoryRecordingRepository, CountingObjectStore, UUID
]:
    repository = InMemoryRecordingRepository()
    store = CountingObjectStore()
    service = RecordingService(repository, store)  # type: ignore[arg-type]
    recording_id = uuid4()
    await service.create(
        owner_id=OWNER_ID, command=create_command(recording_id), idempotency_key="create-1"
    )
    return service, repository, store, recording_id


async def upload(
    service: RecordingService,
    part: tuple[RecordingPartUploadMetadata, bytes, bytes, bytes],
    idempotency_key: str,
    *,
    ciphertext: bytes | None = None,
    metadata: RecordingPartUploadMetadata | None = None,
) -> RecordingPartReceipt:
    return await service.upload_part(
        owner_id=OWNER_ID,
        metadata=metadata or part[0],
        part_key=part[1],
        ciphertext=ciphertext if ciphertext is not None else part[2],
        idempotency_key=idempotency_key,
    )


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
    service, repository, store, recording_id = await started_service()
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
    del service

"""Transactional owner-scoped persistence for durable recording ingest."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.models import Owner
from ..database import transaction_scope
from ..models.base import utc_now
from .contracts import timeline_sha256
from .models import Recording, RecordingGap, RecordingPart, RecordingTrack
from .schemas import (
    RecordingCreateCommand,
    RecordingCreateResponse,
    RecordingPartReceipt,
    RecordingPartUploadMetadata,
    RecordingSealCommand,
    RecordingSealResponse,
    RecordingStatusResponse,
    RecordingTrackStatus,
)
from .service import RecordingConflict, RecordingNotFound


@dataclass(frozen=True, slots=True)
class PartReservation:
    recording_id: UUID
    track_id: UUID
    sequence: int
    sample_start: int
    sample_count: int
    byte_length: int
    plaintext_sha256: str
    object_key: str
    state: str
    high_water_sample: int
    stored_receipt: RecordingPartReceipt | None = None

    def receipt(self, *, replayed: bool) -> RecordingPartReceipt:
        if self.stored_receipt is not None:
            return self.stored_receipt.model_copy(update={"replayed": replayed})
        return RecordingPartReceipt(
            recording_id=self.recording_id,
            track_id=self.track_id,
            sequence=self.sequence,
            sample_start=self.sample_start,
            sample_count=self.sample_count,
            plaintext_sha256=self.plaintext_sha256,
            high_water_sample=self.high_water_sample,
            replayed=replayed,
        )


@dataclass(frozen=True, slots=True)
class StoredPartSnapshot:
    track_id: UUID
    sequence: int
    byte_length: int
    object_key: str


@dataclass(frozen=True, slots=True)
class SealSnapshot:
    stored_part_hashes: Mapping[tuple[str, int], str]
    parts: tuple[StoredPartSnapshot, ...]
    response: RecordingSealResponse | None = None


def _same_format(track: RecordingTrack, metadata: RecordingPartUploadMetadata) -> bool:
    return (
        track.kind == metadata.track_kind
        and track.sample_encoding == metadata.format.sample_encoding
        and track.sample_rate_hz == metadata.format.sample_rate_hz
        and track.channel_count == metadata.format.channel_count
        and track.interleaved == metadata.format.interleaved
    )


class SqlAlchemyRecordingRepository:
    """Own every write transaction and serialize mutations at the track row."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        owner_id: int,
        command: RecordingCreateCommand,
        idempotency_key: str,
        request_hash: bytes,
    ) -> RecordingCreateResponse:
        async with transaction_scope(self._session):
            await self._lock_owner(owner_id)
            existing = await self._session.scalar(
                select(Recording)
                .where(Recording.owner_id == owner_id)
                .where(
                    or_(
                        Recording.client_recording_id == command.recording_id,
                        Recording.create_idempotency_key == idempotency_key,
                    )
                )
                .with_for_update()
            )
            if existing is not None:
                if (
                    existing.client_recording_id != command.recording_id
                    or existing.create_idempotency_key != idempotency_key
                    or existing.create_request_hash != request_hash
                ):
                    raise RecordingConflict("recording create identity was reused")
                return RecordingCreateResponse.model_validate(
                    existing.create_result_json
                ).model_copy(update={"replayed": True})

            result = RecordingCreateResponse(
                recording_id=command.recording_id,
                state="reserved",
                replayed=False,
            )
            recording = Recording(
                owner_id=owner_id,
                client_recording_id=command.recording_id,
                schema_version=command.schema_version,
                state="reserved",
                started_at=command.started_at,
                create_idempotency_key=idempotency_key,
                create_request_hash=request_hash,
                create_result_json=result.model_dump(mode="json"),
            )
            self._session.add(recording)
            await self._session.flush()
            for declaration in command.tracks:
                self._session.add(
                    RecordingTrack(
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
                    )
                )
            await self._session.flush()
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
        async with transaction_scope(self._session):
            recording, track = await self._locked_track(
                owner_id=owner_id,
                recording_id=metadata.recording_id,
                track_id=metadata.track_id,
            )
            if recording.state in {"sealing", "stored", "stored_with_gaps"}:
                raise RecordingConflict("recording no longer accepts parts")
            if not _same_format(track, metadata):
                raise RecordingConflict("recording part format does not match its track")

            existing = await self._session.scalar(
                select(RecordingPart)
                .where(RecordingPart.owner_id == owner_id)
                .where(RecordingPart.recording_id == recording.id)
                .where(RecordingPart.track_id == track.id)
                .where(
                    or_(
                        RecordingPart.sequence == metadata.sequence,
                        RecordingPart.idempotency_key == idempotency_key,
                    )
                )
                .with_for_update()
            )
            if existing is not None:
                if not self._same_part(
                    existing,
                    metadata=metadata,
                    object_key=object_key,
                    idempotency_key=idempotency_key,
                    request_hash=request_hash,
                ):
                    raise RecordingConflict("recording part identity was reused")
                return self._reservation(recording, track, existing)

            overlap = await self._session.scalar(
                select(RecordingPart.id)
                .where(RecordingPart.owner_id == owner_id)
                .where(RecordingPart.recording_id == recording.id)
                .where(RecordingPart.track_id == track.id)
                .where(RecordingPart.sample_start < metadata.sample_start + metadata.sample_count)
                .where(
                    RecordingPart.sample_start + RecordingPart.sample_count > metadata.sample_start
                )
            )
            if overlap is not None:
                raise RecordingConflict("recording part range overlaps existing audio")

            part = RecordingPart(
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
            self._session.add(part)
            recording.state = "uploading"
            track.state = "uploading"
            await self._session.flush()
            return self._reservation(recording, track, part)

    async def finalize_part(
        self,
        *,
        owner_id: int,
        metadata: RecordingPartUploadMetadata,
        object_key: str,
        idempotency_key: str,
    ) -> RecordingPartReceipt:
        async with transaction_scope(self._session):
            recording, track = await self._locked_track(
                owner_id=owner_id,
                recording_id=metadata.recording_id,
                track_id=metadata.track_id,
            )
            part = await self._session.scalar(
                select(RecordingPart)
                .where(RecordingPart.owner_id == owner_id)
                .where(RecordingPart.recording_id == recording.id)
                .where(RecordingPart.track_id == track.id)
                .where(RecordingPart.sequence == metadata.sequence)
                .with_for_update()
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

            now = utc_now()
            part.state = "stored"
            part.stored_at = now
            stored = tuple(
                (
                    await self._session.scalars(
                        select(RecordingPart)
                        .where(RecordingPart.owner_id == owner_id)
                        .where(RecordingPart.recording_id == recording.id)
                        .where(RecordingPart.track_id == track.id)
                        .where(or_(RecordingPart.state == "stored", RecordingPart.id == part.id))
                        .order_by(RecordingPart.sample_start, RecordingPart.sequence)
                    )
                ).all()
            )
            cursor = 0
            for item in stored:
                if item.sample_start != cursor:
                    break
                cursor += item.sample_count
            track.high_water_sample = cursor
            track.stored_part_count = len(stored)
            track.stored_byte_length = sum(item.byte_length for item in stored)
            track.state = "uploading"
            recording.state = "uploading"
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
            await self._session.flush()
            return receipt

    async def prepare_seal(
        self,
        *,
        owner_id: int,
        command: RecordingSealCommand,
        idempotency_key: str,
        request_hash: bytes,
    ) -> SealSnapshot:
        async with transaction_scope(self._session):
            recording = await self._locked_recording(owner_id, command.recording_id)
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
            if recording.started_at != command.started_at:
                raise RecordingConflict("recording start time does not match")
            if recording.seal_idempotency_key is not None and (
                recording.seal_idempotency_key != idempotency_key
                or recording.seal_request_hash != request_hash
            ):
                raise RecordingConflict("recording seal identity was reused")

            tracks = tuple(
                (
                    await self._session.scalars(
                        select(RecordingTrack)
                        .where(RecordingTrack.owner_id == owner_id)
                        .where(RecordingTrack.recording_id == recording.id)
                        .order_by(RecordingTrack.kind, RecordingTrack.id)
                        .with_for_update()
                    )
                ).all()
            )
            declared = {item.track_id: item for item in command.tracks}
            if len(tracks) != 2 or {item.client_track_id for item in tracks} != declared.keys():
                raise RecordingConflict("recording seal tracks do not match")

            parts = tuple(
                (
                    await self._session.scalars(
                        select(RecordingPart)
                        .where(RecordingPart.owner_id == owner_id)
                        .where(RecordingPart.recording_id == recording.id)
                        .order_by(RecordingPart.track_id, RecordingPart.sequence)
                        .with_for_update()
                    )
                ).all()
            )
            if any(item.state != "stored" for item in parts):
                raise RecordingConflict("recording still has unpersisted parts")
            by_track = {item.id: item.client_track_id for item in tracks}
            stored_hashes = {
                (str(by_track[item.track_id]), item.sequence): item.plaintext_sha256.hex()
                for item in parts
            }
            stored_descriptors = {
                (str(by_track[item.track_id]), item.sequence): (
                    item.sample_start,
                    item.sample_count,
                    item.byte_length,
                    item.plaintext_sha256.hex(),
                )
                for item in parts
            }
            declared_descriptors = {
                (str(track.track_id), part.sequence): (
                    part.sample_start,
                    part.sample_count,
                    part.byte_length,
                    part.plaintext_sha256,
                )
                for track in command.tracks
                for part in track.parts
            }
            if stored_descriptors != declared_descriptors:
                raise RecordingConflict("recording seal parts do not match stored ranges")
            if any(
                timeline_sha256(manifest) != manifest.timeline_sha256 for manifest in command.tracks
            ):
                raise RecordingConflict("recording seal timeline hash does not match")
            snapshots = tuple(
                StoredPartSnapshot(
                    track_id=by_track[item.track_id],
                    sequence=item.sequence,
                    byte_length=item.byte_length,
                    object_key=item.object_key,
                )
                for item in parts
            )

            existing_gaps = tuple(
                (
                    await self._session.scalars(
                        select(RecordingGap)
                        .where(RecordingGap.owner_id == owner_id)
                        .where(RecordingGap.recording_id == recording.id)
                        .order_by(RecordingGap.track_id, RecordingGap.sample_start)
                        .with_for_update()
                    )
                ).all()
            )
            expected_gaps = {
                (track.id, gap.sample_start): (gap.sample_count, gap.reason)
                for track in tracks
                for gap in declared[track.client_track_id].gaps
            }
            persisted_gaps = {
                (gap.track_id, gap.sample_start): (gap.sample_count, gap.reason)
                for gap in existing_gaps
            }
            if persisted_gaps and persisted_gaps != expected_gaps:
                raise RecordingConflict("recording gaps conflict with prior seal attempt")
            if not persisted_gaps:
                for track in tracks:
                    for gap in declared[track.client_track_id].gaps:
                        self._session.add(
                            RecordingGap(
                                owner_id=owner_id,
                                recording_id=recording.id,
                                track_id=track.id,
                                schema_version=command.schema_version,
                                sample_start=gap.sample_start,
                                sample_count=gap.sample_count,
                                reason=gap.reason,
                            )
                        )
            recording.state = "sealing"
            recording.seal_idempotency_key = idempotency_key
            recording.seal_request_hash = request_hash
            recording.ended_at = command.ended_at
            for track in tracks:
                manifest = declared[track.client_track_id]
                if (
                    track.kind != manifest.kind
                    or track.conversion_version != manifest.conversion_version
                    or track.channel_count != manifest.format.channel_count
                ):
                    raise RecordingConflict("recording seal track lineage does not match")
                track.state = "sealing"
            await self._session.flush()
            return SealSnapshot(
                stored_part_hashes=MappingProxyType(stored_hashes),
                parts=snapshots,
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
        async with transaction_scope(self._session):
            recording = await self._locked_recording(owner_id, command.recording_id)
            if recording.state in {"stored", "stored_with_gaps"}:
                if (
                    recording.seal_idempotency_key != idempotency_key
                    or recording.seal_request_hash != request_hash
                    or recording.seal_result_json is None
                ):
                    raise RecordingConflict("recording seal identity was reused")
                return RecordingSealResponse.model_validate(recording.seal_result_json).model_copy(
                    update={"replayed": True}
                )
            if (
                recording.state != "sealing"
                or recording.seal_idempotency_key != idempotency_key
                or recording.seal_request_hash != request_hash
            ):
                raise RecordingConflict("recording seal was not reserved")
            tracks = tuple(
                (
                    await self._session.scalars(
                        select(RecordingTrack)
                        .where(RecordingTrack.owner_id == owner_id)
                        .where(RecordingTrack.recording_id == recording.id)
                        .with_for_update()
                    )
                ).all()
            )
            declared = {item.track_id: item for item in command.tracks}
            stored_manifests = {
                track_id: (key, digest, length) for track_id, key, digest, length in manifests
            }
            if {item.client_track_id for item in tracks} != stored_manifests.keys():
                raise RecordingConflict("recording track manifests are incomplete")
            final_state = (
                "stored_with_gaps" if command.coverage_status == "stored_with_gaps" else "stored"
            )
            now = utc_now()
            for track in tracks:
                manifest = declared[track.client_track_id]
                key, digest, length = stored_manifests[track.client_track_id]
                track.state = "stored_with_gaps" if manifest.gaps else "stored"
                track.high_water_sample = manifest.total_sample_count
                track.total_sample_count = manifest.total_sample_count
                track.pcm_sha256 = bytes.fromhex(manifest.pcm_sha256)
                track.timeline_sha256 = bytes.fromhex(manifest.timeline_sha256)
                track.manifest_object_key = key
                track.manifest_sha256 = bytes.fromhex(digest)
                track.manifest_byte_length = length
                track.sealed_at = now
            ordered_digests = tuple(stored_manifests[item.track_id][1] for item in command.tracks)
            result = RecordingSealResponse(
                recording_id=command.recording_id,
                state=final_state,
                coverage_status=command.coverage_status,
                track_manifest_sha256=ordered_digests,
                audio_created_on_server=True,
                transcript_lineage_accepted=False,
                replayed=False,
            )
            recording.state = final_state
            recording.coverage_status = command.coverage_status
            recording.audio_created_on_server = True
            recording.seal_result_json = result.model_dump(mode="json")
            recording.sealed_at = now
            await self._session.flush()
            return result

    async def status(self, *, owner_id: int, recording_id: UUID) -> RecordingStatusResponse:
        recording = await self._session.scalar(
            select(Recording)
            .where(Recording.owner_id == owner_id)
            .where(Recording.client_recording_id == recording_id)
        )
        if recording is None:
            raise RecordingNotFound("recording was not found")
        tracks = tuple(
            (
                await self._session.scalars(
                    select(RecordingTrack)
                    .where(RecordingTrack.owner_id == owner_id)
                    .where(RecordingTrack.recording_id == recording.id)
                    .order_by(RecordingTrack.kind, RecordingTrack.id)
                )
            ).all()
        )
        gap_counts = {
            track.id: len(
                tuple(
                    (
                        await self._session.scalars(
                            select(RecordingGap.id)
                            .where(RecordingGap.owner_id == owner_id)
                            .where(RecordingGap.recording_id == recording.id)
                            .where(RecordingGap.track_id == track.id)
                        )
                    ).all()
                )
            )
            for track in tracks
        }
        return self._status(recording, tracks, gap_counts)

    async def pending(self, *, owner_id: int) -> tuple[RecordingStatusResponse, ...]:
        recordings = tuple(
            (
                await self._session.scalars(
                    select(Recording)
                    .where(Recording.owner_id == owner_id)
                    .where(
                        Recording.state.in_(("reserved", "uploading", "sealing", "needs_attention"))
                    )
                    .order_by(Recording.created_at, Recording.id)
                    .limit(100)
                )
            ).all()
        )
        return tuple(
            [
                await self.status(owner_id=owner_id, recording_id=item.client_recording_id)
                for item in recordings
            ]
        )

    async def _lock_owner(self, owner_id: int) -> None:
        locked = await self._session.scalar(
            select(Owner.id).where(Owner.id == owner_id).with_for_update()
        )
        if locked is None:
            raise RecordingNotFound("recording owner was not found")

    async def _locked_recording(self, owner_id: int, recording_id: UUID) -> Recording:
        recording = await self._session.scalar(
            select(Recording)
            .where(Recording.owner_id == owner_id)
            .where(Recording.client_recording_id == recording_id)
            .with_for_update()
        )
        if recording is None:
            raise RecordingNotFound("recording was not found")
        return recording

    async def _locked_track(
        self, *, owner_id: int, recording_id: UUID, track_id: UUID
    ) -> tuple[Recording, RecordingTrack]:
        recording = await self._locked_recording(owner_id, recording_id)
        track = await self._session.scalar(
            select(RecordingTrack)
            .where(RecordingTrack.owner_id == owner_id)
            .where(RecordingTrack.recording_id == recording.id)
            .where(RecordingTrack.client_track_id == track_id)
            .with_for_update()
        )
        if track is None:
            raise RecordingNotFound("recording track was not found")
        return recording, track

    @staticmethod
    def _same_part(
        part: RecordingPart,
        *,
        metadata: RecordingPartUploadMetadata,
        object_key: str,
        idempotency_key: str,
        request_hash: bytes,
    ) -> bool:
        return (
            part.sequence == metadata.sequence
            and part.sample_start == metadata.sample_start
            and part.sample_count == metadata.sample_count
            and part.byte_length == metadata.byte_length
            and part.ciphertext_byte_length == metadata.ciphertext_byte_length
            and part.plaintext_sha256.hex() == metadata.plaintext_sha256
            and part.ciphertext_sha256.hex() == metadata.ciphertext_sha256
            and part.object_key == object_key
            and part.idempotency_key == idempotency_key
            and part.request_hash == request_hash
        )

    @staticmethod
    def _reservation(
        recording: Recording, track: RecordingTrack, part: RecordingPart
    ) -> PartReservation:
        return PartReservation(
            recording_id=recording.client_recording_id,
            track_id=track.client_track_id,
            sequence=part.sequence,
            sample_start=part.sample_start,
            sample_count=part.sample_count,
            byte_length=part.byte_length,
            plaintext_sha256=part.plaintext_sha256.hex(),
            object_key=part.object_key,
            state=part.state,
            high_water_sample=track.high_water_sample,
            stored_receipt=(
                RecordingPartReceipt.model_validate(part.result_json)
                if part.result_json is not None
                else None
            ),
        )

    @staticmethod
    def _status(
        recording: Recording,
        tracks: Sequence[RecordingTrack],
        gap_counts: Mapping[int, int],
    ) -> RecordingStatusResponse:
        if len(tracks) != 2:
            raise RecordingConflict("recording track aggregate is incomplete")
        return RecordingStatusResponse(
            recording_id=recording.client_recording_id,
            state=recording.state,
            coverage_status=recording.coverage_status,
            tracks=tuple(
                RecordingTrackStatus(
                    track_id=track.client_track_id,
                    kind=track.kind,
                    high_water_sample=track.high_water_sample,
                    stored_part_count=track.stored_part_count,
                    gap_count=gap_counts.get(track.id, 0),
                    manifest_sha256=(
                        track.manifest_sha256.hex() if track.manifest_sha256 is not None else None
                    ),
                )
                for track in sorted(tracks, key=lambda item: (item.kind, item.id))
            ),
            audio_created_on_server=recording.audio_created_on_server,
            transcript_lineage_accepted=recording.transcript_lineage_accepted,
        )


__all__ = [
    "PartReservation",
    "SealSnapshot",
    "SqlAlchemyRecordingRepository",
    "StoredPartSnapshot",
]

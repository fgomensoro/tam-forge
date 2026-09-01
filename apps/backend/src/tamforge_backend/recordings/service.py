"""Bounded decrypt, immutable persistence, and exact recording seal workflow."""

from __future__ import annotations

import base64
import hashlib
import hmac
from collections.abc import AsyncIterator, Mapping
from typing import TYPE_CHECKING
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ..storage.models import ObjectStoreError, build_object_key
from ..storage.ports import ObjectStore
from .contracts import (
    canonical_json_bytes,
    part_aad_bytes,
    recording_manifest_sha256,
    timeline_sha256,
)
from .schemas import (
    RecordingCreateCommand,
    RecordingCreateResponse,
    RecordingPartReceipt,
    RecordingPartUploadMetadata,
    RecordingSealCommand,
    RecordingSealResponse,
    RecordingStatusResponse,
)

if TYPE_CHECKING:
    from .repository import PartReservation, SealSnapshot, SqlAlchemyRecordingRepository


class RecordingError(Exception):
    """Base recording failure with a message safe for server logs only."""


class RecordingInvalidRequest(RecordingError):
    """The request does not satisfy the versioned recording contract."""


class RecordingNotFound(RecordingError):
    """The owner-scoped recording or track does not exist."""


class RecordingConflict(RecordingError):
    """Immutable recording state conflicts with the request."""


class RecordingUnavailable(RecordingError):
    """Durable recording storage is temporarily unavailable."""


def _b64url_decode(value: str, *, expected_bytes: int) -> bytes:
    try:
        decoded = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except (ValueError, TypeError):
        raise RecordingInvalidRequest("recording encryption material is invalid") from None
    if len(decoded) != expected_bytes:
        raise RecordingInvalidRequest("recording encryption material is invalid")
    return decoded


def decrypt_recording_part(
    metadata: RecordingPartUploadMetadata,
    *,
    part_key: bytes,
    ciphertext: bytes,
) -> bytes:
    """Decrypt one bounded part and verify every declared integrity field."""
    if len(part_key) != 32:
        raise RecordingInvalidRequest("recording encryption material is invalid")
    if len(ciphertext) != metadata.ciphertext_byte_length:
        raise RecordingConflict("recording part ciphertext length does not match")
    ciphertext_hash = hashlib.sha256(ciphertext).hexdigest()
    if not hmac.compare_digest(ciphertext_hash, metadata.ciphertext_sha256):
        raise RecordingConflict("recording part ciphertext hash does not match")
    nonce = _b64url_decode(metadata.nonce_base64url, expected_bytes=12)
    try:
        plaintext = AESGCM(part_key).decrypt(nonce, ciphertext, part_aad_bytes(metadata))
    except InvalidTag:
        raise RecordingConflict("recording part authentication failed") from None
    if len(plaintext) != metadata.byte_length:
        raise RecordingConflict("recording part plaintext length does not match")
    plaintext_hash = hashlib.sha256(plaintext).hexdigest()
    if not hmac.compare_digest(plaintext_hash, metadata.plaintext_sha256):
        raise RecordingConflict("recording part plaintext hash does not match")
    return plaintext


def recording_part_object_key(*, owner_id: int, metadata: RecordingPartUploadMetadata) -> str:
    logical_id = f"{metadata.recording_id}-{metadata.track_id}-{metadata.sequence}"
    return build_object_key(
        artifact_class="recording-part",
        owner_id=str(owner_id),
        logical_id=logical_id,
        sha256=metadata.plaintext_sha256,
    )


def recording_manifest_object_key(
    *, owner_id: int, recording_id: UUID, track_id: UUID, sha256: str
) -> str:
    return build_object_key(
        artifact_class="recording-manifest",
        owner_id=str(owner_id),
        logical_id=f"{recording_id}-{track_id}",
        sha256=sha256,
    )


def validate_seal_manifest(
    command: RecordingSealCommand,
    *,
    stored_part_hashes: Mapping[tuple[str, int], str],
) -> None:
    """Require the manifest to name exactly the immutable uploaded parts."""
    declared = {
        (str(track.track_id), part.sequence): part.plaintext_sha256
        for track in command.tracks
        for part in track.parts
    }
    if declared.keys() != stored_part_hashes.keys():
        raise RecordingConflict("seal manifest does not match stored recording parts")
    for identity, digest in declared.items():
        if not hmac.compare_digest(digest, stored_part_hashes[identity]):
            raise RecordingConflict("seal manifest does not match stored recording parts")
    for track in command.tracks:
        if not hmac.compare_digest(timeline_sha256(track), track.timeline_sha256):
            raise RecordingConflict("seal timeline hash does not match")


async def _one_chunk(value: bytes) -> AsyncIterator[bytes]:
    yield value


class RecordingService:
    """Coordinates explicit DB transactions around immutable object writes."""

    def __init__(
        self,
        repository: SqlAlchemyRecordingRepository,
        object_store: ObjectStore,
    ) -> None:
        self._repository = repository
        self._objects = object_store

    async def create(
        self,
        *,
        owner_id: int,
        command: RecordingCreateCommand,
        idempotency_key: str,
    ) -> RecordingCreateResponse:
        request_hash = hashlib.sha256(canonical_json_bytes(command)).digest()
        return await self._repository.create(
            owner_id=owner_id,
            command=command,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )

    async def upload_part(
        self,
        *,
        owner_id: int,
        metadata: RecordingPartUploadMetadata,
        part_key: bytes,
        ciphertext: bytes,
        idempotency_key: str,
    ) -> RecordingPartReceipt:
        plaintext = decrypt_recording_part(
            metadata,
            part_key=part_key,
            ciphertext=ciphertext,
        )
        object_key = recording_part_object_key(owner_id=owner_id, metadata=metadata)
        request_hash = hashlib.sha256(canonical_json_bytes(metadata)).digest()
        reservation = await self._repository.reserve_part(
            owner_id=owner_id,
            metadata=metadata,
            object_key=object_key,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )
        if reservation.state == "stored":
            return reservation.receipt(replayed=True)
        await self._ensure_part_object(
            owner_id=owner_id,
            reservation=reservation,
            plaintext=plaintext,
        )
        return await self._repository.finalize_part(
            owner_id=owner_id,
            metadata=metadata,
            object_key=object_key,
            idempotency_key=idempotency_key,
        )

    async def _ensure_part_object(
        self,
        *,
        owner_id: int,
        reservation: PartReservation,
        plaintext: bytes,
    ) -> None:
        try:
            existing = await self._objects.stat(reservation.object_key)
            if existing is not None:
                if (
                    existing.sha256 != reservation.plaintext_sha256
                    or existing.byte_length != reservation.byte_length
                ):
                    raise RecordingConflict("immutable recording part object conflicts")
                return
            await self._objects.put_immutable(
                key=reservation.object_key,
                body=_one_chunk(plaintext),
                sha256=reservation.plaintext_sha256,
                content_type="application/vnd.tamforge.pcm-s16le",
                metadata={
                    "owner-id": str(owner_id),
                    "recording-id": str(reservation.recording_id),
                    "track-id": str(reservation.track_id),
                    "sequence": str(reservation.sequence),
                },
            )
        except RecordingError:
            raise
        except ObjectStoreError as exc:
            raise RecordingUnavailable("recording part storage is unavailable") from exc

    async def seal(
        self,
        *,
        owner_id: int,
        command: RecordingSealCommand,
        idempotency_key: str,
    ) -> RecordingSealResponse:
        request_hash = bytes.fromhex(recording_manifest_sha256(command))
        snapshot = await self._repository.prepare_seal(
            owner_id=owner_id,
            command=command,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )
        if snapshot.response is not None:
            return snapshot.response.model_copy(update={"replayed": True})
        validate_seal_manifest(command, stored_part_hashes=snapshot.stored_part_hashes)
        await self._verify_pcm_hashes(command=command, snapshot=snapshot)

        manifests: list[tuple[UUID, str, str, int]] = []
        try:
            for track in command.tracks:
                body = canonical_json_bytes(track)
                digest = hashlib.sha256(body).hexdigest()
                key = recording_manifest_object_key(
                    owner_id=owner_id,
                    recording_id=command.recording_id,
                    track_id=track.track_id,
                    sha256=digest,
                )
                await self._objects.put_immutable(
                    key=key,
                    body=_one_chunk(body),
                    sha256=digest,
                    content_type="application/vnd.tamforge.recording-track-manifest+json",
                    metadata={
                        "owner-id": str(owner_id),
                        "recording-id": str(command.recording_id),
                        "track-id": str(track.track_id),
                    },
                )
                manifests.append((track.track_id, key, digest, len(body)))
        except ObjectStoreError as exc:
            raise RecordingUnavailable("recording manifest storage is unavailable") from exc

        return await self._repository.finalize_seal(
            owner_id=owner_id,
            command=command,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            recording_manifest_sha256=recording_manifest_sha256(command),
            manifests=tuple(manifests),
        )

    async def _verify_pcm_hashes(
        self, *, command: RecordingSealCommand, snapshot: SealSnapshot
    ) -> None:
        by_track = {track.track_id: track for track in command.tracks}
        hashers = {track.track_id: hashlib.sha256() for track in command.tracks}
        try:
            for part in snapshot.parts:
                hasher = hashers.get(part.track_id)
                if hasher is None:
                    raise RecordingConflict("stored recording track is not declared")
                async with self._objects.open(part.object_key) as chunks:
                    byte_count = 0
                    async for chunk in chunks:
                        byte_count += len(chunk)
                        hasher.update(chunk)
                if byte_count != part.byte_length:
                    raise RecordingConflict("stored recording part length does not match")
        except RecordingError:
            raise
        except ObjectStoreError as exc:
            raise RecordingUnavailable("recording verification storage is unavailable") from exc
        for track_id, hasher in hashers.items():
            if not hmac.compare_digest(hasher.hexdigest(), by_track[track_id].pcm_sha256):
                raise RecordingConflict("recording PCM hash does not match stored parts")

    async def status(self, *, owner_id: int, recording_id: UUID) -> RecordingStatusResponse:
        return await self._repository.status(owner_id=owner_id, recording_id=recording_id)

    async def pending(self, *, owner_id: int) -> tuple[RecordingStatusResponse, ...]:
        return await self._repository.pending(owner_id=owner_id)


__all__ = [
    "RecordingConflict",
    "RecordingError",
    "RecordingInvalidRequest",
    "RecordingNotFound",
    "RecordingService",
    "RecordingUnavailable",
    "decrypt_recording_part",
    "recording_manifest_object_key",
    "recording_part_object_key",
    "validate_seal_manifest",
]

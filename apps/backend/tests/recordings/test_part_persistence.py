from __future__ import annotations

import base64
import hashlib
from uuid import UUID

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from tamforge_backend.recordings.contracts import part_aad_bytes
from tamforge_backend.recordings.schemas import RecordingPartUploadMetadata
from tamforge_backend.recordings.service import (
    RecordingConflict,
    decrypt_recording_part,
)


def metadata(plaintext: bytes, ciphertext: bytes) -> RecordingPartUploadMetadata:
    return RecordingPartUploadMetadata.model_validate(
        {
            "schema_version": 1,
            "recording_id": "11111111-1111-4111-8111-111111111111",
            "track_id": "22222222-2222-4222-8222-222222222222",
            "track_kind": "microphone",
            "format": {"channel_count": 1},
            "sequence": 0,
            "sample_start": 0,
            "sample_count": len(plaintext) // 2,
            "byte_length": len(plaintext),
            "ciphertext_byte_length": len(ciphertext),
            "plaintext_sha256": hashlib.sha256(plaintext).hexdigest(),
            "ciphertext_sha256": hashlib.sha256(ciphertext).hexdigest(),
            "nonce_base64url": base64.urlsafe_b64encode(b"n" * 12).rstrip(b"=").decode(),
            "encryption_version": "aes-256-gcm-hkdf-sha256-v1",
        }
    )


def encrypted_part(plaintext: bytes) -> tuple[RecordingPartUploadMetadata, bytes, bytes]:
    key = b"k" * 32
    nonce = b"n" * 12
    provisional = metadata(plaintext, b"x" * (len(plaintext) + 16))
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, part_aad_bytes(provisional))
    return metadata(plaintext, ciphertext), key, ciphertext


def test_bounded_part_decrypt_verifies_aad_lengths_and_both_hashes() -> None:
    expected = b"\x01\x00" * 8
    contract, key, ciphertext = encrypted_part(expected)

    assert decrypt_recording_part(contract, part_key=key, ciphertext=ciphertext) == expected

    with pytest.raises(RecordingConflict):
        decrypt_recording_part(contract, part_key=key, ciphertext=ciphertext[:-1] + b"x")


def test_part_metadata_fails_closed_on_track_format_or_range_mismatch() -> None:
    contract, _, _ = encrypted_part(b"\x00\x00" * 8)
    payload = contract.model_dump(mode="json")
    payload["format"]["channel_count"] = 2
    with pytest.raises(ValueError):
        RecordingPartUploadMetadata.model_validate(payload)


def test_content_addressed_part_identity_is_owner_recording_track_and_hash_scoped() -> None:
    from tamforge_backend.recordings.service import recording_part_object_key

    contract, _, _ = encrypted_part(b"\x00\x00" * 8)
    key = recording_part_object_key(owner_id=7, metadata=contract)

    assert key.startswith("recording-part/7/")
    assert str(contract.recording_id) in key
    assert str(contract.track_id) in key
    assert key.endswith(contract.plaintext_sha256)
    assert UUID(str(contract.recording_id)) == contract.recording_id

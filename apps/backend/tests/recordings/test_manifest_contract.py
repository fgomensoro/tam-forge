from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError
from tamforge_backend.recordings.contracts import (
    canonical_json_bytes,
    part_aad_bytes,
    recording_manifest_sha256,
    timeline_hash_input,
)
from tamforge_backend.recordings.schemas import (
    RecordingGap,
    RecordingPartDescriptor,
    RecordingPartUploadMetadata,
    RecordingSealCommand,
)

FIXTURES = Path(__file__).parents[1] / "fixtures" / "recordings"


def load_fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_manifest_v1_has_stable_canonical_hash_and_exact_two_tracks() -> None:
    manifest = RecordingSealCommand.model_validate(load_fixture("recording-manifest-v1.json"))

    assert [track.kind for track in manifest.tracks] == ["microphone", "system_audio"]
    assert recording_manifest_sha256(manifest) == (
        "1213d49ac5ef345bc1ffa98ade3dfa11ea7cda3d8d25f53c67d5a4c561bd89b0"
    )
    assert canonical_json_bytes(manifest).endswith(b"}")
    assert not canonical_json_bytes(manifest).endswith(b"\n")


def test_unknown_version_and_unknown_fields_fail_closed() -> None:
    with pytest.raises(ValidationError):
        RecordingSealCommand.model_validate(load_fixture("invalid-version.json"))

    payload = load_fixture("recording-manifest-v1.json")
    payload["future_field"] = True
    with pytest.raises(ValidationError):
        RecordingSealCommand.model_validate(payload)


@pytest.mark.parametrize(
    ("fixture", "model"),
    [
        ("invalid-range.json", RecordingPartDescriptor),
        ("invalid-gap.json", RecordingGap),
        ("invalid-hash.json", RecordingPartDescriptor),
    ],
)
def test_invalid_range_gap_and_hash_fixtures_fail_closed(
    fixture: str,
    model: type[RecordingPartDescriptor] | type[RecordingGap],
) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(load_fixture(fixture))


def test_manifest_rejects_missing_duplicate_or_overlapping_coverage() -> None:
    payload = load_fixture("recording-manifest-v1.json")

    missing_track = deepcopy(payload)
    missing_track["tracks"] = missing_track["tracks"][:1]  # type: ignore[index]
    with pytest.raises(ValidationError):
        RecordingSealCommand.model_validate(missing_track)

    duplicate_kind = deepcopy(payload)
    duplicate_kind["tracks"][1]["kind"] = "microphone"  # type: ignore[index]
    duplicate_kind["tracks"][1]["format"]["channel_count"] = 1  # type: ignore[index]
    with pytest.raises(ValidationError):
        RecordingSealCommand.model_validate(duplicate_kind)

    overlap = deepcopy(payload)
    overlap["tracks"][0]["parts"][1]["sample_start"] = 47000  # type: ignore[index]
    with pytest.raises(ValidationError):
        RecordingSealCommand.model_validate(overlap)

    hidden_hole = deepcopy(payload)
    hidden_hole["tracks"][0]["parts"][1]["sample_start"] = 49000  # type: ignore[index]
    with pytest.raises(ValidationError):
        RecordingSealCommand.model_validate(hidden_hole)


def test_coverage_status_cannot_hide_explicit_gaps() -> None:
    payload = load_fixture("recording-manifest-v1.json")
    payload["coverage_status"] = "complete"

    with pytest.raises(ValidationError):
        RecordingSealCommand.model_validate(payload)


def test_part_aad_and_timeline_hash_inputs_are_deterministic_and_domain_separated() -> None:
    metadata = RecordingPartUploadMetadata.model_validate(
        {
            "schema_version": 1,
            "recording_id": "11111111-1111-4111-8111-111111111111",
            "track_id": "22222222-2222-4222-8222-222222222222",
            "track_kind": "microphone",
            "format": {
                "sample_encoding": "pcm_s16le",
                "sample_rate_hz": 48000,
                "channel_count": 1,
                "interleaved": True,
            },
            "sequence": 0,
            "sample_start": 0,
            "sample_count": 48000,
            "byte_length": 96000,
            "ciphertext_byte_length": 96016,
            "plaintext_sha256": "a" * 64,
            "ciphertext_sha256": "b" * 64,
            "nonce_base64url": "AAAAAAAAAAAAAAAA",
            "encryption_version": "aes-256-gcm-hkdf-sha256-v1",
        }
    )
    manifest = RecordingSealCommand.model_validate(load_fixture("recording-manifest-v1.json"))

    first = part_aad_bytes(metadata)
    assert first == part_aad_bytes(metadata)
    assert first.startswith(b"tamforge.recording.part-aad.v1\0")
    assert b"ciphertext_sha256" not in first
    assert timeline_hash_input(manifest.tracks[0]).startswith(
        b"tamforge.recording.timeline.v1\0"
    )
    assert timeline_hash_input(manifest.tracks[0]) != first


def test_manifest_serialization_rejects_non_integer_numeric_domains() -> None:
    with pytest.raises(TypeError):
        canonical_json_bytes({"sample_start": 1.5})

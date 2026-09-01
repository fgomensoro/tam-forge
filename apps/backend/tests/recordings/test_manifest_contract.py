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
    RecordingPartCryptoHeaders,
    RecordingPartDescriptor,
    RecordingPartUploadMetadata,
    RecordingSealCommand,
    RecordingSealResponse,
    RecordingSourceLineageSegment,
    RecordingStatusResponse,
)

FIXTURES = Path(__file__).parents[1] / "fixtures" / "recordings"


def load_fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_manifest_v1_has_stable_canonical_hash_and_exact_two_tracks() -> None:
    manifest = RecordingSealCommand.model_validate(load_fixture("recording-manifest-v1.json"))

    assert [track.kind for track in manifest.tracks] == ["microphone", "system_audio"]
    assert recording_manifest_sha256(manifest) == (
        "100d3ff09dc2519ed19f030472b2fa050dbff3d98d04eac220df644f3111fa77"
    )
    assert manifest.tracks[0].source_lineage[0].source_sample_rate_hz == 44_100
    assert manifest.tracks[1].source_lineage[1].route == "display:external"
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


def test_part_sequence_order_must_match_timeline_order() -> None:
    payload = load_fixture("recording-manifest-v1.json")
    payload["tracks"][0]["parts"][0]["sample_start"] = 48_000  # type: ignore[index]
    payload["tracks"][0]["parts"][1]["sample_start"] = 0  # type: ignore[index]

    with pytest.raises(ValidationError):
        RecordingSealCommand.model_validate(payload)


def test_coverage_status_cannot_hide_explicit_gaps() -> None:
    payload = load_fixture("recording-manifest-v1.json")
    payload["coverage_status"] = "complete"

    with pytest.raises(ValidationError):
        RecordingSealCommand.model_validate(payload)


def test_source_lineage_exactly_covers_uploaded_audio_not_declared_gaps() -> None:
    payload = load_fixture("recording-manifest-v1.json")

    missing_lineage = deepcopy(payload)
    missing_lineage["tracks"][0]["source_lineage"] = []  # type: ignore[index]
    with pytest.raises(ValidationError):
        RecordingSealCommand.model_validate(missing_lineage)

    lineage_crosses_gap = deepcopy(payload)
    lineage_crosses_gap["tracks"][1]["source_lineage"][0]["sample_count"] = (  # type: ignore[index]
        52_800
    )
    with pytest.raises(ValidationError):
        RecordingSealCommand.model_validate(lineage_crosses_gap)

    unordered_lineage = deepcopy(payload)
    unordered_lineage["tracks"][1]["source_lineage"] = list(  # type: ignore[index]
        reversed(unordered_lineage["tracks"][1]["source_lineage"])
    )
    with pytest.raises(ValidationError):
        RecordingSealCommand.model_validate(unordered_lineage)

    overlapping_lineage = deepcopy(payload)
    overlapping_lineage["tracks"][1]["source_lineage"][1]["sample_start"] = (  # type: ignore[index]
        47_999
    )
    with pytest.raises(ValidationError):
        RecordingSealCommand.model_validate(overlapping_lineage)

    mismatched_conversion = deepcopy(payload)
    mismatched_conversion["tracks"][0]["source_lineage"][0][  # type: ignore[index]
        "conversion_version"
    ] = "tamforge-pcm16-v2"
    with pytest.raises(ValidationError):
        RecordingSealCommand.model_validate(mismatched_conversion)


def test_source_lineage_presentation_duration_matches_canonical_samples() -> None:
    resampled = {
        "sample_start": 0,
        "sample_count": 96_000,
        "source_sample_rate_hz": 44_100,
        "source_channel_count": 1,
        "device_id": "microphone:built-in",
        "route": "Built-in Microphone",
        "presentation_time_start": 0,
        "presentation_time_end": 88_200,
        "presentation_time_timescale": 44_100,
        "conversion_version": "tamforge-pcm16-v1",
    }
    assert RecordingSourceLineageSegment.model_validate(resampled).sample_count == 96_000

    absurd_duration = deepcopy(resampled)
    absurd_duration["presentation_time_end"] = 1
    absurd_duration["presentation_time_timescale"] = 1_000_000_000
    with pytest.raises(ValidationError):
        RecordingSourceLineageSegment.model_validate(absurd_duration)


def test_seal_timestamps_must_be_utc_and_within_recording_cap() -> None:
    payload = load_fixture("recording-manifest-v1.json")

    non_utc = deepcopy(payload)
    non_utc["started_at"] = "2026-09-01T17:00:00+01:00"
    with pytest.raises(ValidationError):
        RecordingSealCommand.model_validate(non_utc)

    over_cap = deepcopy(payload)
    over_cap["ended_at"] = "2026-09-01T18:00:01Z"
    with pytest.raises(ValidationError):
        RecordingSealCommand.model_validate(over_cap)

    at_cap = deepcopy(payload)
    at_cap["ended_at"] = "2026-09-01T18:00:00Z"
    assert (
        RecordingSealCommand.model_validate(at_cap).ended_at.isoformat()
        == "2026-09-01T18:00:00+00:00"
    )


def _status_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "recording_id": "11111111-1111-4111-8111-111111111111",
        "state": "reserved",
        "coverage_status": None,
        "tracks": [
            {
                "track_id": "22222222-2222-4222-8222-222222222222",
                "kind": "microphone",
                "high_water_sample": 0,
                "stored_part_count": 0,
                "gap_count": 0,
            },
            {
                "track_id": "33333333-3333-4333-8333-333333333333",
                "kind": "system_audio",
                "high_water_sample": 0,
                "stored_part_count": 0,
                "gap_count": 0,
            },
        ],
        "audio_created_on_server": False,
        "transcript_lineage_accepted": False,
    }


def test_recording_status_rejects_contradictory_release_gates() -> None:
    nonterminal_coverage = _status_payload()
    nonterminal_coverage["coverage_status"] = "complete"
    with pytest.raises(ValidationError):
        RecordingStatusResponse.model_validate(nonterminal_coverage)

    nonterminal_audio = _status_payload()
    nonterminal_audio["audio_created_on_server"] = True
    with pytest.raises(ValidationError):
        RecordingStatusResponse.model_validate(nonterminal_audio)

    nonterminal_transcript = _status_payload()
    nonterminal_transcript["audio_created_on_server"] = True
    nonterminal_transcript["transcript_lineage_accepted"] = True
    with pytest.raises(ValidationError):
        RecordingStatusResponse.model_validate(nonterminal_transcript)

    transcript_without_audio = _status_payload()
    transcript_without_audio["transcript_lineage_accepted"] = True
    with pytest.raises(
        ValidationError, match="transcript lineage cannot precede durable server audio"
    ):
        RecordingStatusResponse.model_validate(transcript_without_audio)

    stored = _status_payload()
    stored.update(
        state="stored",
        coverage_status="complete",
        audio_created_on_server=True,
    )
    assert RecordingStatusResponse.model_validate(stored).state == "stored"

    stored_wrong_coverage = deepcopy(stored)
    stored_wrong_coverage["coverage_status"] = "stored_with_gaps"
    with pytest.raises(ValidationError):
        RecordingStatusResponse.model_validate(stored_wrong_coverage)

    stored_without_audio = deepcopy(stored)
    stored_without_audio["audio_created_on_server"] = False
    with pytest.raises(ValidationError):
        RecordingStatusResponse.model_validate(stored_without_audio)

    accepted_transcript = deepcopy(stored)
    accepted_transcript["transcript_lineage_accepted"] = True
    assert RecordingStatusResponse.model_validate(accepted_transcript).transcript_lineage_accepted

    stored_with_gaps = deepcopy(stored)
    stored_with_gaps["state"] = "stored_with_gaps"
    stored_with_gaps["coverage_status"] = "stored_with_gaps"
    assert RecordingStatusResponse.model_validate(stored_with_gaps).state == "stored_with_gaps"

    stored_with_gaps_wrong_coverage = deepcopy(stored_with_gaps)
    stored_with_gaps_wrong_coverage["coverage_status"] = "complete"
    with pytest.raises(ValidationError):
        RecordingStatusResponse.model_validate(stored_with_gaps_wrong_coverage)

    stored_with_gaps_without_audio = deepcopy(stored_with_gaps)
    stored_with_gaps_without_audio["audio_created_on_server"] = False
    with pytest.raises(ValidationError):
        RecordingStatusResponse.model_validate(stored_with_gaps_without_audio)


def test_seal_response_state_coverage_and_transcript_gate_agree() -> None:
    response = {
        "schema_version": 1,
        "recording_id": "11111111-1111-4111-8111-111111111111",
        "state": "stored",
        "coverage_status": "complete",
        "track_manifest_sha256": ["a" * 64, "b" * 64],
        "audio_created_on_server": True,
        "transcript_lineage_accepted": False,
        "replayed": False,
    }
    assert RecordingSealResponse.model_validate(response).state == "stored"

    for required_gate in ("audio_created_on_server", "transcript_lineage_accepted"):
        missing_gate = deepcopy(response)
        missing_gate.pop(required_gate)
        with pytest.raises(ValidationError):
            RecordingSealResponse.model_validate(missing_gate)

    wrong_coverage = deepcopy(response)
    wrong_coverage["coverage_status"] = "stored_with_gaps"
    with pytest.raises(ValidationError):
        RecordingSealResponse.model_validate(wrong_coverage)

    stored_with_gaps = deepcopy(response)
    stored_with_gaps["state"] = "stored_with_gaps"
    stored_with_gaps["coverage_status"] = "stored_with_gaps"
    assert RecordingSealResponse.model_validate(stored_with_gaps).state == "stored_with_gaps"

    transcript_accepted = deepcopy(response)
    transcript_accepted["transcript_lineage_accepted"] = True
    with pytest.raises(ValidationError):
        RecordingSealResponse.model_validate(transcript_accepted)


def test_part_crypto_key_requires_exact_unpadded_base64url_and_stays_redacted() -> None:
    valid_key = "A" * 40 + "_-A"
    headers = RecordingPartCryptoHeaders.model_validate({"part_key_base64url": valid_key})

    assert headers.part_key_base64url.get_secret_value() == valid_key
    assert valid_key not in repr(headers)

    for invalid_key in (
        "A" * 42,
        "A" * 44,
        "+" + "A" * 42,
        "/" + "A" * 42,
        "A" * 42 + "=",
        "A" * 42 + "B",
    ):
        with pytest.raises(ValidationError) as error:
            RecordingPartCryptoHeaders.model_validate({"part_key_base64url": invalid_key})
        assert invalid_key not in str(error.value)


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
    assert timeline_hash_input(manifest.tracks[0]).startswith(b"tamforge.recording.timeline.v1\0")
    assert timeline_hash_input(manifest.tracks[0]) != first


def test_manifest_serialization_rejects_non_integer_numeric_domains() -> None:
    with pytest.raises(TypeError):
        canonical_json_bytes({"sample_start": 1.5})

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tamforge_backend.recordings.contracts import (
    recording_manifest_sha256,
    timeline_sha256,
)
from tamforge_backend.recordings.schemas import RecordingSealCommand
from tamforge_backend.recordings.service import RecordingConflict, validate_seal_manifest

FIXTURE = Path(__file__).parents[1] / "fixtures" / "recordings" / "recording-manifest-v1.json"


def manifest() -> RecordingSealCommand:
    return RecordingSealCommand.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))


def test_seal_requires_stored_parts_exact_gaps_and_verified_track_hashes() -> None:
    command = manifest()
    stored = {
        (str(track.track_id), part.sequence): part.plaintext_sha256
        for track in command.tracks
        for part in track.parts
    }

    validate_seal_manifest(command, stored_part_hashes=stored)

    stored[(str(command.tracks[0].track_id), 0)] = "0" * 64
    with pytest.raises(RecordingConflict):
        validate_seal_manifest(command, stored_part_hashes=stored)


def test_timeline_and_manifest_hash_domains_are_stable_and_non_circular() -> None:
    command = manifest()

    assert len(recording_manifest_sha256(command)) == 64
    assert len(timeline_sha256(command.tracks[0])) == 64
    assert timeline_sha256(command.tracks[0]) == command.tracks[0].timeline_sha256


def test_manifest_rejects_hidden_gap_or_conflicting_part_identity() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["tracks"][1]["gaps"] = []

    with pytest.raises(ValueError):
        RecordingSealCommand.model_validate(payload)

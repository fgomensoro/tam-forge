from __future__ import annotations

import pytest
from pydantic import ValidationError
from tamforge_backend.speech.schemas import TranscriptSubmitCommand

BODY = {
    "schema_version": 1,
    "track": "microphone",
    "segments": [
        {
            "text": "hello there",
            "start_ms": 0,
            "end_ms": 900,
            "words": [
                {"text": "hello", "start_ms": 0, "end_ms": 400, "probability": 0.98},
                {"text": "there", "start_ms": 400, "end_ms": 900, "probability": 0.91},
            ],
        }
    ],
    "model_identity": {
        "runtime_version": "b4938",
        "model_filename": "ggml-base.en-q5_1.bin",
        "model_sha256": "a" * 64,
        "metal_requested": True,
        "used_builtin_vad": False,
        "language": "en",
    },
    "derivation": {
        "derivation_version": "tamforge-asr16k-v1",
        "source_sample_rate": 48000,
        "source_channel_count": 1,
        "source_sample_count": 2880000,
        "output_sample_rate": 16000,
        "output_sample_count": 960000,
        "zero_filled_gaps": [],
        "source_pcm_sha256": "b" * 64,
        "derived_pcm_sha256": "c" * 64,
        "quality": {
            "version": "audio-quality-v1",
            "sample_rate": 48000,
            "channel_count": 1,
            "source_sample_count": 2880000,
            "duration_seconds": 60.0,
            "peak_absolute": 21000,
            "all_silence": False,
            "clipped_ratio": 0.0,
            "dc_offset": 0.0,
            "channel_imbalance_decibels": None,
            "discontinuity_count": 0,
            "unavailable_dimensions": [],
        },
    },
}


def test_accepts_a_complete_body() -> None:
    command = TranscriptSubmitCommand.model_validate(BODY)
    assert command.track == "microphone"
    assert command.segments[0].words[1].probability == pytest.approx(0.91)


def test_rejects_a_probability_outside_zero_to_one() -> None:
    body = {**BODY}
    body["segments"] = [
        {
            **BODY["segments"][0],
            "words": [{"text": "hi", "start_ms": 0, "end_ms": 10, "probability": 1.4}],
        }
    ]
    with pytest.raises(ValidationError):
        TranscriptSubmitCommand.model_validate(body)


def test_rejects_a_word_ending_before_it_starts() -> None:
    body = {**BODY}
    body["segments"] = [
        {
            **BODY["segments"][0],
            "words": [{"text": "hi", "start_ms": 90, "end_ms": 10, "probability": 0.5}],
        }
    ]
    with pytest.raises(ValidationError):
        TranscriptSubmitCommand.model_validate(body)


def test_rejects_an_unknown_field() -> None:
    with pytest.raises(ValidationError):
        TranscriptSubmitCommand.model_validate({**BODY, "extra": 1})

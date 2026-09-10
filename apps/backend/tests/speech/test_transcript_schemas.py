from __future__ import annotations

import pytest
from pydantic import ValidationError
from tamforge_backend.speech.schemas import (
    MAX_CORRECTION_TEXT_LENGTH,
    MAX_SEGMENTS_PER_TRANSCRIPT,
    MAX_WORDS_PER_TRANSCRIPT,
    TranscriptCorrectionCommand,
    TranscriptSegment,
    TranscriptSubmitCommand,
)

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


def test_rejects_a_body_that_passes_every_field_bound_but_exceeds_the_byte_limit() -> None:
    # 4,000 segments (the field max) x a 4,096-char text (the field max) x zero words
    # each: legal under every per-field bound, but canonicalizes to ~3.95x
    # TRANSCRIPT_BODY_LIMIT. Only validate_body_size catches this.
    body = {**BODY}
    body["segments"] = [
        {"text": "x" * 4_096, "start_ms": 0, "end_ms": 0, "words": []} for _ in range(4_000)
    ]
    with pytest.raises(ValidationError):
        TranscriptSubmitCommand.model_validate(body)


def test_rejects_a_segment_ending_before_it_starts() -> None:
    with pytest.raises(ValidationError):
        TranscriptSegment(text="x", start_ms=900, end_ms=0, words=())


def test_rejects_a_transcript_whose_total_word_count_exceeds_the_aggregate_bound() -> None:
    # Each segment individually respects the MAX_WORDS_PER_TRANSCRIPT field bound on
    # `words` (40,000 and 1), but their sum (40,001) exceeds the aggregate bound that
    # TranscriptSubmitCommand.validate_segments enforces across the whole transcript.
    def word(index: int) -> dict[str, object]:
        return {"text": "w", "start_ms": index, "end_ms": index + 1, "probability": 0.9}

    segment_a = {
        "text": "segment a",
        "start_ms": 0,
        "end_ms": MAX_WORDS_PER_TRANSCRIPT,
        "words": [word(index) for index in range(MAX_WORDS_PER_TRANSCRIPT)],
    }
    segment_b = {
        "text": "segment b",
        "start_ms": MAX_WORDS_PER_TRANSCRIPT,
        "end_ms": MAX_WORDS_PER_TRANSCRIPT + 1,
        "words": [word(MAX_WORDS_PER_TRANSCRIPT)],
    }
    body = {**BODY, "segments": [segment_a, segment_b]}
    with pytest.raises(ValidationError):
        TranscriptSubmitCommand.model_validate(body)


CORRECTION_BODY = {
    "schema_version": 1,
    "segment_index": MAX_SEGMENTS_PER_TRANSCRIPT - 1,
    "word_start_index": MAX_WORDS_PER_TRANSCRIPT - 1,
    "word_end_index": MAX_WORDS_PER_TRANSCRIPT - 1,
    "reason": "r" * 64,
}


def test_a_maxed_out_correction_command_fits_the_byte_limit() -> None:
    # Asserts the actual boundary the fix produces: MAX_CORRECTION_TEXT_LENGTH was
    # recalibrated (with headroom) so a correction maxed out on every field bound now
    # fits CORRECTION_BODY_LIMIT once canonicalized, instead of overshooting it.
    command = TranscriptCorrectionCommand.model_validate(
        {
            **CORRECTION_BODY,
            "original_text": "x" * MAX_CORRECTION_TEXT_LENGTH,
            "corrected_text": "y" * MAX_CORRECTION_TEXT_LENGTH,
        }
    )
    assert len(command.original_text) == MAX_CORRECTION_TEXT_LENGTH


def test_rejects_a_correction_within_field_bounds_but_over_the_byte_limit() -> None:
    # Multi-byte characters stay within MAX_CORRECTION_TEXT_LENGTH (a character
    # count) while blowing well past CORRECTION_BODY_LIMIT (a byte count) once
    # canonicalized, proving validate_body_size guards bytes, not characters.
    command = {
        **CORRECTION_BODY,
        "original_text": "\U0001f642" * MAX_CORRECTION_TEXT_LENGTH,
        "corrected_text": "y",
    }
    with pytest.raises(ValidationError):
        TranscriptCorrectionCommand.model_validate(command)

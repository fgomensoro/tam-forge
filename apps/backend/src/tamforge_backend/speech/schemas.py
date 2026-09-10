"""Strict wire schemas for submitted transcripts and their corrections."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Final, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..agents.hashing import canonical_bytes
from .models import (
    CORRECTION_BODY_LIMIT,
    MAX_CORRECTIONS_PER_TRANSCRIPT,
    TRANSCRIPT_BODY_LIMIT,
)

SPEECH_SCHEMA_VERSION: Final[Literal[1]] = 1

# Transcript-body bounds. "Word" here means one `TranscriptWord` entry, which is one
# whisper token, not one English word: `WhisperTranscriber.readWords` emits one entry
# per whisper BPE token (sub-word pieces and punctuation included), and English runs
# roughly 1.3 tokens per word. A 120-minute recording is roughly 18,000 *words* (see
# the transcript-lineage design doc), i.e. 23,000-27,000 of these entries, so the old
# 20,000 bound permanently rejected a supported two-hour recording. 40,000 keeps
# headroom over that (about 1.5x the worst realistic case) while still bounding the
# body: at ~80 canonical bytes per entry that is ~3.2 MB, inside the 4 MiB
# TRANSCRIPT_BODY_LIMIT with about 1 MB left for segment/model/derivation overhead.
MAX_SEGMENTS_PER_TRANSCRIPT = 4_000
MAX_WORDS_PER_TRANSCRIPT = 40_000
MAX_TEXT_LENGTH = 4_096
# Two hours (mirrors recordings.MAX_RECORDING_SECONDS) plus one minute of headroom:
# ASRAudioDeriver.finish() pads the tail past the last real sample so the final window
# is complete, so a maximum-length recording's last segment/word end_ms can land past
# the recording's nominal duration. Exact equality left zero room for that.
MAX_TRANSCRIPT_MS = 7_260_000

# Source/derivation bounds, mirroring the equivalent recordings.schemas constants.
MAX_SOURCE_SAMPLE_RATE_HZ = 384_000
MAX_SOURCE_CHANNEL_COUNT = 32
MAX_SOURCE_SAMPLE_COUNT = 48_000 * 7_200  # two hours at 48 kHz, mirrors MAX_TRACK_SAMPLES
# Two hours at the fixed 16 kHz ASR output rate, plus the same one-minute headroom as
# MAX_TRANSCRIPT_MS and for the same reason: finish()'s tail padding can push the
# derived output past the exact two-hour sample count.
MAX_OUTPUT_SAMPLE_COUNT = 16_000 * 7_260
MAX_DERIVATION_GAPS = 7_200  # at most one zero-filled gap per second of a two-hour recording
MAX_QUALITY_DIMENSIONS = 16

# Correction bodies are bounded to CORRECTION_BODY_LIMIT bytes. Splitting it evenly
# in two (// 2) was wrong: a maxed-out correction canonicalizes to 8,396 bytes, 204
# over an 8,192-byte limit, once indices, reason, and JSON punctuation are counted
# too. Quartering it leaves comfortable headroom for those other fields instead;
# validate_body_size below (not this bound) is what actually guarantees the limit.
MAX_CORRECTION_TEXT_LENGTH: Final[int] = CORRECTION_BODY_LIMIT // 4

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Track = Literal["microphone", "system_audio"]
DerivationVersion = Annotated[
    str, Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
]
DerivationGapReason = Literal[
    "callback_overflow",
    "format_change",
    "route_change",
    "source_discontinuity",
    "missing_audio",
    "corrupt_spool_record",
]
BoundedText = Annotated[str, Field(min_length=1, max_length=MAX_TEXT_LENGTH)]
Milliseconds = Annotated[int, Field(ge=0, le=MAX_TRANSCRIPT_MS)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _validate_word_index_range(start: int, end: int) -> None:
    if end < start:
        raise ValueError("word_end_index cannot precede word_start_index")


class TranscriptWord(StrictModel):
    text: BoundedText
    start_ms: Milliseconds
    end_ms: Milliseconds
    probability: Annotated[float, Field(ge=0.0, le=1.0)]

    @model_validator(mode="after")
    def validate_span(self) -> Self:
        if self.end_ms < self.start_ms:
            raise ValueError("word end_ms cannot precede start_ms")
        return self


class TranscriptSegment(StrictModel):
    text: BoundedText
    start_ms: Milliseconds
    end_ms: Milliseconds
    words: Annotated[tuple[TranscriptWord, ...], Field(max_length=MAX_WORDS_PER_TRANSCRIPT)]

    @model_validator(mode="after")
    def validate_span(self) -> Self:
        if self.end_ms < self.start_ms:
            raise ValueError("segment end_ms cannot precede start_ms")
        return self

    @model_validator(mode="after")
    def validate_words(self) -> Self:
        for word in self.words:
            if word.start_ms < self.start_ms or word.end_ms > self.end_ms:
                raise ValueError("word must be contained within its segment span")
        for previous, current in zip(self.words, self.words[1:], strict=False):
            if current.start_ms < previous.end_ms:
                raise ValueError("words must be chronological within a segment")
        return self


class TranscriptModelIdentity(StrictModel):
    runtime_version: Annotated[str, Field(min_length=1, max_length=256)]
    model_filename: Annotated[str, Field(min_length=1, max_length=256)]
    model_sha256: Sha256
    metal_requested: bool
    used_builtin_vad: bool
    language: Annotated[str, Field(min_length=1, max_length=32)]


class TranscriptDerivationGap(StrictModel):
    sample_start: Annotated[int, Field(ge=0, lt=MAX_SOURCE_SAMPLE_COUNT)]
    sample_count: Annotated[int, Field(gt=0, le=MAX_SOURCE_SAMPLE_COUNT)]
    reason: DerivationGapReason


class TranscriptAudioQuality(StrictModel):
    version: Annotated[str, Field(min_length=1, max_length=64)]
    sample_rate: Annotated[int, Field(gt=0, le=MAX_SOURCE_SAMPLE_RATE_HZ)]
    channel_count: Annotated[int, Field(ge=1, le=MAX_SOURCE_CHANNEL_COUNT)]
    source_sample_count: Annotated[int, Field(ge=0, le=MAX_SOURCE_SAMPLE_COUNT)]
    duration_seconds: Annotated[float, Field(ge=0.0, le=7_200.0)]
    peak_absolute: Annotated[int, Field(ge=0, le=32_768)]
    all_silence: bool
    clipped_ratio: Annotated[float, Field(ge=0.0, le=1.0)]
    dc_offset: Annotated[float, Field(ge=0.0, le=1.0)]
    channel_imbalance_decibels: Annotated[float, Field(ge=0.0, le=300.0)] | None = None
    discontinuity_count: Annotated[int, Field(ge=0, le=MAX_DERIVATION_GAPS)]
    unavailable_dimensions: Annotated[
        tuple[Annotated[str, Field(min_length=1, max_length=64)], ...],
        Field(max_length=MAX_QUALITY_DIMENSIONS),
    ] = ()


class TranscriptDerivation(StrictModel):
    derivation_version: DerivationVersion
    source_sample_rate: Annotated[int, Field(gt=0, le=MAX_SOURCE_SAMPLE_RATE_HZ)]
    source_channel_count: Annotated[int, Field(ge=1, le=MAX_SOURCE_CHANNEL_COUNT)]
    source_sample_count: Annotated[int, Field(ge=0, le=MAX_SOURCE_SAMPLE_COUNT)]
    output_sample_rate: Annotated[int, Field(gt=0, le=MAX_SOURCE_SAMPLE_RATE_HZ)]
    output_sample_count: Annotated[int, Field(ge=0, le=MAX_OUTPUT_SAMPLE_COUNT)]
    zero_filled_gaps: Annotated[
        tuple[TranscriptDerivationGap, ...], Field(max_length=MAX_DERIVATION_GAPS)
    ] = ()
    source_pcm_sha256: Sha256
    derived_pcm_sha256: Sha256
    quality: TranscriptAudioQuality


class TranscriptSubmitCommand(StrictModel):
    schema_version: Literal[1] = SPEECH_SCHEMA_VERSION
    track: Track
    segments: Annotated[
        tuple[TranscriptSegment, ...], Field(max_length=MAX_SEGMENTS_PER_TRANSCRIPT)
    ]
    model_identity: TranscriptModelIdentity
    derivation: TranscriptDerivation

    @model_validator(mode="after")
    def validate_segments(self) -> Self:
        for previous, current in zip(self.segments, self.segments[1:], strict=False):
            if current.start_ms < previous.end_ms:
                raise ValueError("segments must be chronological")
        total_words = sum(len(segment.words) for segment in self.segments)
        if total_words > MAX_WORDS_PER_TRANSCRIPT:
            raise ValueError("transcript exceeds the maximum word count")
        return self

    @model_validator(mode="after")
    def validate_body_size(self) -> Self:
        # The per-field bounds above are cheap early defence; this is the actual
        # guarantee. 4,000 segments of 4,096 characters each and zero words pass
        # every bound above but canonicalize to ~3.95x TRANSCRIPT_BODY_LIMIT.
        canonical_bytes(self.model_dump(mode="json"), limit=TRANSCRIPT_BODY_LIMIT)
        return self


class TranscriptCorrectionCommand(StrictModel):
    schema_version: Literal[1] = SPEECH_SCHEMA_VERSION
    segment_index: Annotated[int, Field(ge=0, lt=MAX_SEGMENTS_PER_TRANSCRIPT)]
    word_start_index: Annotated[int, Field(ge=0, lt=MAX_WORDS_PER_TRANSCRIPT)]
    word_end_index: Annotated[int, Field(ge=0, lt=MAX_WORDS_PER_TRANSCRIPT)]
    original_text: Annotated[str, Field(min_length=1, max_length=MAX_CORRECTION_TEXT_LENGTH)]
    corrected_text: Annotated[str, Field(min_length=1, max_length=MAX_CORRECTION_TEXT_LENGTH)]
    reason: Annotated[str, Field(min_length=1, max_length=64)]

    @model_validator(mode="after")
    def validate_word_range(self) -> Self:
        _validate_word_index_range(self.word_start_index, self.word_end_index)
        return self

    @model_validator(mode="after")
    def validate_body_size(self) -> Self:
        # The per-field bounds above are cheap early defence; this is the actual
        # guarantee against a maxed-out correction that would otherwise overshoot.
        canonical_bytes(self.model_dump(mode="json"), limit=CORRECTION_BODY_LIMIT)
        return self


class TranscriptCorrectionResponse(StrictModel):
    schema_version: Literal[1] = SPEECH_SCHEMA_VERSION
    correction_id: Annotated[int, Field(gt=0)]
    transcript_id: Annotated[int, Field(gt=0)]
    segment_index: Annotated[int, Field(ge=0, lt=MAX_SEGMENTS_PER_TRANSCRIPT)]
    word_start_index: Annotated[int, Field(ge=0, lt=MAX_WORDS_PER_TRANSCRIPT)]
    word_end_index: Annotated[int, Field(ge=0, lt=MAX_WORDS_PER_TRANSCRIPT)]
    original_text: Annotated[str, Field(min_length=1, max_length=MAX_CORRECTION_TEXT_LENGTH)]
    corrected_text: Annotated[str, Field(min_length=1, max_length=MAX_CORRECTION_TEXT_LENGTH)]
    reason: Annotated[str, Field(min_length=1, max_length=64)]
    created_at: datetime
    replayed: bool

    @model_validator(mode="after")
    def validate_word_range(self) -> Self:
        _validate_word_index_range(self.word_start_index, self.word_end_index)
        return self


class TranscriptResponse(StrictModel):
    schema_version: Literal[1] = SPEECH_SCHEMA_VERSION
    transcript_id: Annotated[int, Field(gt=0)]
    recording_id: UUID
    track: Track
    content_hash: Sha256
    created_at: datetime
    replayed: bool
    corrections: Annotated[
        tuple[TranscriptCorrectionResponse, ...], Field(max_length=MAX_CORRECTIONS_PER_TRANSCRIPT)
    ] = ()


class TranscriptPage(StrictModel):
    items: Annotated[tuple[TranscriptResponse, ...], Field(max_length=100)]


SPEECH_OPENAPI_MODELS: tuple[type[StrictModel], ...] = (
    TranscriptWord,
    TranscriptSegment,
    TranscriptModelIdentity,
    TranscriptDerivationGap,
    TranscriptAudioQuality,
    TranscriptDerivation,
    TranscriptSubmitCommand,
    TranscriptCorrectionCommand,
    TranscriptCorrectionResponse,
    TranscriptResponse,
    TranscriptPage,
)


__all__ = [
    "MAX_CORRECTIONS_PER_TRANSCRIPT",
    "MAX_CORRECTION_TEXT_LENGTH",
    "MAX_DERIVATION_GAPS",
    "MAX_OUTPUT_SAMPLE_COUNT",
    "MAX_QUALITY_DIMENSIONS",
    "MAX_SEGMENTS_PER_TRANSCRIPT",
    "MAX_SOURCE_CHANNEL_COUNT",
    "MAX_SOURCE_SAMPLE_COUNT",
    "MAX_SOURCE_SAMPLE_RATE_HZ",
    "MAX_TEXT_LENGTH",
    "MAX_TRANSCRIPT_MS",
    "MAX_WORDS_PER_TRANSCRIPT",
    "SPEECH_OPENAPI_MODELS",
    "SPEECH_SCHEMA_VERSION",
    "DerivationGapReason",
    "DerivationVersion",
    "Sha256",
    "Track",
    "TranscriptAudioQuality",
    "TranscriptCorrectionCommand",
    "TranscriptCorrectionResponse",
    "TranscriptDerivation",
    "TranscriptDerivationGap",
    "TranscriptModelIdentity",
    "TranscriptPage",
    "TranscriptResponse",
    "TranscriptSegment",
    "TranscriptSubmitCommand",
    "TranscriptWord",
]

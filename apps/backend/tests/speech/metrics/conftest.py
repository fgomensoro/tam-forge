"""Transcript builders for the deterministic speech-metric suites.

Word text mirrors what `WhisperTranscriber.readWords` actually emits: one entry per
whisper BPE token, with the leading space that marks a word-initial token. The metric
calculators segment words from exactly that shape, so fixtures that drop the spaces
would measure something the production pipeline never produces.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

import pytest
from tamforge_backend.speech.schemas import (
    TranscriptAudioQuality,
    TranscriptDerivation,
    TranscriptModelIdentity,
    TranscriptSegment,
    TranscriptSubmitCommand,
    TranscriptWord,
)

Token = tuple[str, int, int]

MODEL_IDENTITY = TranscriptModelIdentity(
    runtime_version="b4938",
    model_filename="ggml-base.en-q5_1.bin",
    model_sha256="a" * 64,
    metal_requested=True,
    used_builtin_vad=True,
    language="en",
)

QUALITY = TranscriptAudioQuality(
    version="tamforge-audio-quality-v1",
    sample_rate=48_000,
    channel_count=1,
    source_sample_count=480_000,
    duration_seconds=10.0,
    peak_absolute=12_000,
    all_silence=False,
    clipped_ratio=0.0,
    dc_offset=0.0,
    discontinuity_count=0,
)


def _derivation(version: str = "tamforge-asr16k-v1") -> TranscriptDerivation:
    return TranscriptDerivation(
        derivation_version=version,
        source_sample_rate=48_000,
        source_channel_count=1,
        source_sample_count=480_000,
        output_sample_rate=16_000,
        output_sample_count=160_000,
        source_pcm_sha256="b" * 64,
        derived_pcm_sha256="c" * 64,
        quality=QUALITY,
    )


def _segment(tokens: Sequence[Token]) -> TranscriptSegment:
    words = tuple(
        TranscriptWord(text=text, start_ms=start, end_ms=end, probability=0.9)
        for text, start, end in tokens
    )
    text = "".join(word.text for word in words).strip() or "silence"
    return TranscriptSegment(
        text=text,
        start_ms=words[0].start_ms if words else 0,
        end_ms=words[-1].end_ms if words else 0,
        words=words,
    )


@pytest.fixture
def build_transcript() -> Callable[..., TranscriptSubmitCommand]:
    def build(
        segments: Sequence[Sequence[Token]],
        *,
        track: str = "microphone",
        derivation_version: str = "tamforge-asr16k-v1",
        used_builtin_vad: bool = True,
    ) -> TranscriptSubmitCommand:
        return TranscriptSubmitCommand(
            track=track,  # type: ignore[arg-type]
            segments=tuple(_segment(tokens) for tokens in segments),
            model_identity=MODEL_IDENTITY.model_copy(
                update={"used_builtin_vad": used_builtin_vad}
            ),
            derivation=_derivation(derivation_version),
        )

    return build

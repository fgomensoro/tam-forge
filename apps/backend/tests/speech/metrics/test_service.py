"""The composed report: one versioned evidence stamp over every version-1 metric."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from decimal import Decimal
from uuid import UUID

import pytest
from tamforge_backend.speech.metrics import (
    METRICS_VERSION,
    MeasuredMetric,
    SpeechMetricsError,
    TranscriptSource,
    UnavailableMetric,
    calculate_speech_metrics,
)

RECORDING_ID = UUID("11111111-2222-3333-4444-555555555555")
Token = tuple[str, int, int]


def _answer_tokens(start: int = 6_000) -> list[Token]:
    tokens: list[Token] = []
    cursor = start
    for index in range(30):
        tokens.append((f" word{index}", cursor, cursor + 300))
        cursor += 400
    return tokens


def _source(
    build: Callable[..., object],
    segments: Sequence[Sequence[Token]],
    *,
    track: str = "microphone",
    transcript_id: int = 7,
    content_hash: str | None = None,
) -> TranscriptSource:
    return TranscriptSource(
        transcript_id=transcript_id,
        content_hash=content_hash or "d" * 64,
        transcript=build(segments, track=track),  # type: ignore[arg-type]
    )


def test_report_carries_every_metric_and_its_evidence(
    build_transcript: Callable[..., object],
) -> None:
    prompt = _source(
        build_transcript,
        [[(" what", 4_100, 4_500), (" happened", 4_600, 5_000)]],
        track="system_audio",
        transcript_id=9,
        content_hash="e" * 64,
    )
    report = calculate_speech_metrics(
        recording_id=RECORDING_ID,
        microphone=_source(build_transcript, [_answer_tokens()]),
        system_audio=prompt,
    )

    assert report.evidence.metrics_version == METRICS_VERSION
    assert report.evidence.recording_id == RECORDING_ID
    assert report.evidence.microphone_transcript_id == 7
    assert report.evidence.microphone_content_hash == "d" * 64
    assert report.evidence.system_audio_transcript_id == 9
    assert report.evidence.system_audio_content_hash == "e" * 64
    assert report.evidence.derivation_version == "tamforge-asr16k-v1"
    assert report.evidence.model_sha256 == "a" * 64
    assert report.evidence.used_builtin_vad is True
    assert report.evidence.recognized_word_count == 30
    assert report.evidence.token_count == 30

    assert isinstance(report.speech_rate_wpm, MeasuredMetric)
    assert isinstance(report.response_latency_ms, MeasuredMetric)
    assert report.response_latency_ms.value == Decimal(1_000)


def test_report_without_a_system_track_still_measures_the_user(
    build_transcript: Callable[..., object],
) -> None:
    report = calculate_speech_metrics(
        recording_id=RECORDING_ID,
        microphone=_source(build_transcript, [_answer_tokens(start=0)]),
    )

    assert report.evidence.system_audio_transcript_id is None
    assert report.evidence.system_audio_content_hash is None
    assert isinstance(report.response_latency_ms, UnavailableMetric)
    assert report.response_latency_ms.reason_code == "system_track_unavailable"
    assert isinstance(report.filler_count, MeasuredMetric)
    assert isinstance(report.mean_length_of_run, MeasuredMetric)


def test_tracks_must_match_their_role(build_transcript: Callable[..., object]) -> None:
    with pytest.raises(SpeechMetricsError):
        calculate_speech_metrics(
            recording_id=RECORDING_ID,
            microphone=_source(build_transcript, [_answer_tokens()], track="system_audio"),
        )

    with pytest.raises(SpeechMetricsError):
        calculate_speech_metrics(
            recording_id=RECORDING_ID,
            microphone=_source(build_transcript, [_answer_tokens()]),
            system_audio=_source(build_transcript, [_answer_tokens()], track="microphone"),
        )


def test_an_unavailable_metric_exposes_no_value(build_transcript: Callable[..., object]) -> None:
    report = calculate_speech_metrics(
        recording_id=RECORDING_ID,
        microphone=_source(build_transcript, [[(" ...", 0, 300)]]),
    )

    assert isinstance(report.speech_rate_wpm, UnavailableMetric)
    assert not hasattr(report.speech_rate_wpm, "value")
    assert report.evidence.recognized_word_count == 0

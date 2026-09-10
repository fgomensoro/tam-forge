"""Response latency across the synchronized microphone and system-audio tracks."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

from tamforge_backend.speech.metrics import (
    MeasuredMetric,
    UnavailableMetric,
    calculate_response_latency,
    segment_words,
)


def _prompt(build: Callable[..., object], *, end_ms: int = 5_000, **kwargs: object) -> object:
    tokens = [(" what", end_ms - 900, end_ms - 500), (" happened", end_ms - 400, end_ms)]
    return build([tokens], track="system_audio", **kwargs)


def _answer(build: Callable[..., object], *, start_ms: int = 5_800) -> object:
    tokens = [(" the", start_ms, start_ms + 200), (" queue", start_ms + 300, start_ms + 900)]
    return build([tokens])


def test_latency_is_prompt_end_to_first_user_word(build_transcript: Callable[..., object]) -> None:
    latency = calculate_response_latency(
        microphone=segment_words(_answer(build_transcript)),
        system_audio=segment_words(_prompt(build_transcript)),
        microphone_derivation="tamforge-asr16k-v1",
        system_audio_derivation="tamforge-asr16k-v1",
    )

    assert isinstance(latency, MeasuredMetric)
    assert latency.value == Decimal(800)
    assert latency.unit == "milliseconds"


def test_missing_system_track_is_unavailable(build_transcript: Callable[..., object]) -> None:
    latency = calculate_response_latency(
        microphone=segment_words(_answer(build_transcript)),
        system_audio=None,
        microphone_derivation="tamforge-asr16k-v1",
        system_audio_derivation=None,
    )

    assert isinstance(latency, UnavailableMetric)
    assert latency.reason_code == "system_track_unavailable"


def test_overlapping_tracks_are_unavailable(build_transcript: Callable[..., object]) -> None:
    latency = calculate_response_latency(
        microphone=segment_words(_answer(build_transcript, start_ms=4_200)),
        system_audio=segment_words(_prompt(build_transcript)),
        microphone_derivation="tamforge-asr16k-v1",
        system_audio_derivation="tamforge-asr16k-v1",
    )

    assert isinstance(latency, UnavailableMetric)
    assert latency.reason_code == "overlapping_tracks"


def test_mismatched_derivations_never_mix_clocks(build_transcript: Callable[..., object]) -> None:
    latency = calculate_response_latency(
        microphone=segment_words(_answer(build_transcript)),
        system_audio=segment_words(
            _prompt(build_transcript, derivation_version="tamforge-asr16k-v2")
        ),
        microphone_derivation="tamforge-asr16k-v1",
        system_audio_derivation="tamforge-asr16k-v2",
    )

    assert isinstance(latency, UnavailableMetric)
    assert latency.reason_code == "incompatible_timing_source"


def test_silent_prompt_is_unavailable(build_transcript: Callable[..., object]) -> None:
    silent = build_transcript([[(" ...", 0, 300)]], track="system_audio")
    latency = calculate_response_latency(
        microphone=segment_words(_answer(build_transcript)),
        system_audio=segment_words(silent),
        microphone_derivation="tamforge-asr16k-v1",
        system_audio_derivation="tamforge-asr16k-v1",
    )

    assert isinstance(latency, UnavailableMetric)
    assert latency.reason_code == "no_prompt_speech"


def test_silent_user_is_unavailable(build_transcript: Callable[..., object]) -> None:
    silent = build_transcript([[(" ...", 6_000, 6_300)]])
    latency = calculate_response_latency(
        microphone=segment_words(silent),
        system_audio=segment_words(_prompt(build_transcript)),
        microphone_derivation="tamforge-asr16k-v1",
        system_audio_derivation="tamforge-asr16k-v1",
    )

    assert isinstance(latency, UnavailableMetric)
    assert latency.reason_code == "no_user_speech"

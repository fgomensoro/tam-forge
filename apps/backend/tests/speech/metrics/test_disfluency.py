"""Version-1 filler and restart counting, published as a detected minimum."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

from tamforge_backend.speech.metrics import (
    FILLER_LEXICON_VERSION,
    MeasuredMetric,
    UnavailableMetric,
    calculate_disfluency,
    segment_words,
)


def _timed(texts: list[str]) -> list[tuple[str, int, int]]:
    return [(f" {text}", index * 400, index * 400 + 300) for index, text in enumerate(texts)]


def test_counts_hesitations_and_two_word_hedges(build_transcript: Callable[..., object]) -> None:
    transcript = build_transcript(
        [_timed(["Um", "I", "think", "you", "know", "the", "answer", "uh", "is", "clear"])]
    )
    disfluency = calculate_disfluency(segment_words(transcript))

    assert isinstance(disfluency.filler_count, MeasuredMetric)
    assert disfluency.filler_count.value == Decimal(3)
    assert disfluency.filler_count.measurement_status == "detected_minimum"
    assert disfluency.filler_lexicon_version == FILLER_LEXICON_VERSION


def test_counts_immediate_repetitions_as_restarts(build_transcript: Callable[..., object]) -> None:
    transcript = build_transcript(
        [_timed(["The", "the", "team", "wanted", "wanted", "a", "clear", "answer"])]
    )
    disfluency = calculate_disfluency(segment_words(transcript))

    assert isinstance(disfluency.restart_count, MeasuredMetric)
    assert disfluency.restart_count.value == Decimal(2)
    assert disfluency.restart_count.measurement_status == "detected_minimum"


def test_a_repeated_word_run_counts_each_repetition(
    build_transcript: Callable[..., object],
) -> None:
    transcript = build_transcript([_timed(["I", "I", "I", "disagree"])])
    disfluency = calculate_disfluency(segment_words(transcript))

    assert isinstance(disfluency.restart_count, MeasuredMetric)
    assert disfluency.restart_count.value == Decimal(2)


def test_hedges_do_not_double_count_across_an_overlap(
    build_transcript: Callable[..., object],
) -> None:
    # "kind of kind of": two non-overlapping hedges, not three overlapping ones.
    transcript = build_transcript([_timed(["It", "is", "kind", "of", "kind", "of", "slow"])])
    disfluency = calculate_disfluency(segment_words(transcript))

    assert isinstance(disfluency.filler_count, MeasuredMetric)
    assert disfluency.filler_count.value == Decimal(2)


def test_content_words_are_never_fillers(build_transcript: Callable[..., object]) -> None:
    # Version 1 stays with unambiguous hesitations, so "like", "so" and "right" count
    # as content rather than inflating the filler rate.
    transcript = build_transcript([_timed(["So", "it", "works", "like", "this", "right"])])
    disfluency = calculate_disfluency(segment_words(transcript))

    assert isinstance(disfluency.filler_count, MeasuredMetric)
    assert disfluency.filler_count.value == Decimal(0)


def test_no_recognized_words_is_unavailable(build_transcript: Callable[..., object]) -> None:
    transcript = build_transcript([[(" ...", 0, 400)]])
    disfluency = calculate_disfluency(segment_words(transcript))

    for metric in (disfluency.filler_count, disfluency.restart_count):
        assert isinstance(metric, UnavailableMetric)
        assert metric.reason_code == "no_recognized_words"

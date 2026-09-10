"""Hand-calculated version-1 fluency formulas and their unavailable cases."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from decimal import Decimal

from tamforge_backend.speech.metrics import (
    MIN_RECOGNIZED_WORDS,
    MIN_RESPONSE_SECONDS,
    MeasuredMetric,
    UnavailableMetric,
    calculate_fluency,
    segment_words,
)

Token = tuple[str, int, int]


def _tokens(gaps: Sequence[int], *, word_ms: int = 300, start: int = 0) -> list[Token]:
    """One 300 ms word per gap entry plus a leading word; gaps[i] precedes word i+1."""
    tokens: list[Token] = [(" word0", start, start + word_ms)]
    cursor = start + word_ms
    for index, gap in enumerate(gaps, start=1):
        cursor += gap
        tokens.append((f" word{index}", cursor, cursor + word_ms))
        cursor += word_ms
    return tokens


def _round(metric: object, places: str) -> Decimal:
    assert isinstance(metric, MeasuredMetric)
    return metric.value.quantize(Decimal(places))


def test_rates_over_a_continuous_run(build_transcript: Callable[..., object]) -> None:
    # 30 words of 300 ms separated by 29 gaps of 100 ms: 11.9 s wall, 9.0 s speaking.
    transcript = build_transcript([_tokens([100] * 29)])
    fluency = calculate_fluency(segment_words(transcript))

    assert _round(fluency.response_duration_seconds, "0.001") == Decimal("11.900")
    assert _round(fluency.speech_rate_wpm, "0.001") == Decimal("151.261")
    assert _round(fluency.articulation_rate_wpm, "0.001") == Decimal("200.000")
    assert _round(fluency.phonation_time_ratio, "0.001") == Decimal("0.756")
    assert _round(fluency.mean_length_of_run, "0.001") == Decimal("30.000")


def test_pause_bands_and_runs(build_transcript: Callable[..., object]) -> None:
    # Three internal pauses, one per version-1 band, and 30 words in four runs.
    transcript = build_transcript([_tokens([100] * 9 + [300, 700, 1500] + [100] * 17)])
    fluency = calculate_fluency(segment_words(transcript))

    assert _round(fluency.pause_count_250_499_ms, "1") == Decimal("1")
    assert _round(fluency.pause_count_500_999_ms, "1") == Decimal("1")
    assert _round(fluency.pause_count_1000_ms_plus, "1") == Decimal("1")
    assert _round(fluency.pause_seconds_total, "0.001") == Decimal("2.500")
    assert _round(fluency.mean_length_of_run, "0.001") == Decimal("7.500")
    assert _round(fluency.speech_rate_wpm, "0.001") == Decimal("127.660")


def test_sub_band_gaps_are_not_pauses(build_transcript: Callable[..., object]) -> None:
    transcript = build_transcript([_tokens([249] * 29)])
    fluency = calculate_fluency(segment_words(transcript))

    assert _round(fluency.pause_count_250_499_ms, "1") == Decimal("0")
    assert _round(fluency.pause_seconds_total, "0.001") == Decimal("0.000")
    assert _round(fluency.mean_length_of_run, "0.001") == Decimal("30.000")


def test_pauses_span_segment_boundaries(build_transcript: Callable[..., object]) -> None:
    first = _tokens([100] * 14)
    resume = first[-1][2] + 1_200
    second = _tokens([100] * 14, start=resume)
    fluency = calculate_fluency(segment_words(build_transcript([first, second])))

    assert _round(fluency.pause_count_1000_ms_plus, "1") == Decimal("1")
    assert _round(fluency.mean_length_of_run, "0.001") == Decimal("15.000")


def test_short_response_is_unavailable_not_zero(build_transcript: Callable[..., object]) -> None:
    assert MIN_RESPONSE_SECONDS == Decimal("10")
    # 30 words inside 8.7 s clears the word minimum but not the duration minimum.
    transcript = build_transcript([_tokens([0] * 29, word_ms=290)])
    fluency = calculate_fluency(segment_words(transcript))

    for metric in (
        fluency.speech_rate_wpm,
        fluency.articulation_rate_wpm,
        fluency.phonation_time_ratio,
        fluency.mean_length_of_run,
    ):
        assert isinstance(metric, UnavailableMetric)
        assert metric.reason_code == "insufficient_sample"
    assert isinstance(fluency.response_duration_seconds, MeasuredMetric)
    assert isinstance(fluency.pause_count_250_499_ms, MeasuredMetric)


def test_too_few_words_is_unavailable(build_transcript: Callable[..., object]) -> None:
    assert MIN_RECOGNIZED_WORDS == 20
    transcript = build_transcript([_tokens([700] * 18)])
    fluency = calculate_fluency(segment_words(transcript))

    assert isinstance(fluency.speech_rate_wpm, UnavailableMetric)
    assert fluency.speech_rate_wpm.reason_code == "insufficient_sample"


def test_no_recognized_words_is_unavailable(build_transcript: Callable[..., object]) -> None:
    transcript = build_transcript([[(" ...", 0, 400), (" ?!", 400, 900)]])
    fluency = calculate_fluency(segment_words(transcript))

    for metric in (
        fluency.response_duration_seconds,
        fluency.speech_rate_wpm,
        fluency.pause_count_250_499_ms,
        fluency.pause_seconds_total,
    ):
        assert isinstance(metric, UnavailableMetric)
        assert metric.reason_code == "no_recognized_words"


def test_zero_speaking_time_never_divides_by_zero(build_transcript: Callable[..., object]) -> None:
    # Every word has zero duration, so articulation rate and phonation ratio have no
    # denominator; the wall-clock rate still does.
    tokens = [(f" word{index}", index * 800, index * 800) for index in range(30)]
    fluency = calculate_fluency(segment_words(build_transcript([tokens])))

    assert isinstance(fluency.articulation_rate_wpm, UnavailableMetric)
    assert fluency.articulation_rate_wpm.reason_code == "no_speaking_time"
    assert isinstance(fluency.phonation_time_ratio, UnavailableMetric)
    assert isinstance(fluency.speech_rate_wpm, MeasuredMetric)


def test_words_join_their_continuation_and_punctuation_tokens(
    build_transcript: Callable[..., object],
) -> None:
    tokens = [
        (" trans", 0, 200),
        ("cription", 200, 600),
        (",", 600, 620),
        (" works", 700, 1_100),
        (".", 1_100, 1_120),
    ]
    words = segment_words(build_transcript([tokens]))

    assert [word.text for word in words] == ["transcription", "works"]
    assert (words[0].start_ms, words[0].end_ms) == (0, 620)

"""Version-1 pace, pause, and run calculators over word timings.

Word timings stand in for a voice-activity timeline here, because they are the only
speech boundaries the persisted transcript carries. `MetricEvidence.used_builtin_vad`
records whether whisper's own detector shaped them, so a consumer can tell which
timeline produced a number instead of assuming a validated VAD gate it never had.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from .models import (
    LONG_PAUSE_FLOOR_MS,
    MILLISECONDS_PER_SECOND,
    MIN_RECOGNIZED_WORDS,
    MIN_RESPONSE_SECONDS,
    PAUSE_FLOOR_MS,
    SECONDS_PER_MINUTE,
    SHORT_PAUSE_CEILING_MS,
    MeasuredMetric,
    Metric,
    UnavailableMetric,
    Unit,
)
from .words import RecognizedWord

_UNITS: dict[str, Unit] = {
    "response_duration_seconds": "seconds",
    "speech_rate_wpm": "words_per_minute",
    "articulation_rate_wpm": "words_per_minute",
    "phonation_time_ratio": "ratio",
    "mean_length_of_run": "words",
    "pause_count_250_499_ms": "count",
    "pause_count_500_999_ms": "count",
    "pause_count_1000_ms_plus": "count",
    "pause_seconds_total": "seconds",
}


@dataclass(frozen=True, slots=True)
class FluencyMetrics:
    response_duration_seconds: Metric
    speech_rate_wpm: Metric
    articulation_rate_wpm: Metric
    phonation_time_ratio: Metric
    mean_length_of_run: Metric
    pause_count_250_499_ms: Metric
    pause_count_500_999_ms: Metric
    pause_count_1000_ms_plus: Metric
    pause_seconds_total: Metric


def _measured(name: str, value: Decimal) -> MeasuredMetric:
    return MeasuredMetric(name=name, unit=_UNITS[name], value=value)


def _unavailable(name: str, reason_code: str) -> UnavailableMetric:
    return UnavailableMetric(name=name, unit=_UNITS[name], reason_code=reason_code)


def calculate_fluency(words: Sequence[RecognizedWord]) -> FluencyMetrics:
    """Return version-1 fluency metrics, each measured or explicitly unavailable."""
    if not words:
        return FluencyMetrics(
            **{name: _unavailable(name, "no_recognized_words") for name in _UNITS}
        )

    duration_seconds = Decimal(words[-1].end_ms - words[0].start_ms) / MILLISECONDS_PER_SECOND
    speaking_seconds = (
        Decimal(sum(word.end_ms - word.start_ms for word in words)) / MILLISECONDS_PER_SECOND
    )
    gaps = tuple(
        max(0, later.start_ms - earlier.end_ms)
        for earlier, later in zip(words, words[1:], strict=False)
    )
    pauses = tuple(gap for gap in gaps if gap >= PAUSE_FLOOR_MS)
    word_count = Decimal(len(words))

    # A rate needs enough sample to describe the speaker rather than the clip. The
    # direct measurements below are not gated: they are what they are at any length.
    sampled = duration_seconds >= MIN_RESPONSE_SECONDS and len(words) >= MIN_RECOGNIZED_WORDS
    speech_rate: Metric
    mean_run: Metric
    articulation: Metric
    phonation: Metric
    if not sampled:
        speech_rate = _unavailable("speech_rate_wpm", "insufficient_sample")
        mean_run = _unavailable("mean_length_of_run", "insufficient_sample")
        articulation = _unavailable("articulation_rate_wpm", "insufficient_sample")
        phonation = _unavailable("phonation_time_ratio", "insufficient_sample")
    else:
        speech_rate = _measured(
            "speech_rate_wpm", word_count / (duration_seconds / SECONDS_PER_MINUTE)
        )
        mean_run = _measured("mean_length_of_run", word_count / Decimal(len(pauses) + 1))
        if speaking_seconds > 0:
            articulation = _measured(
                "articulation_rate_wpm", word_count / (speaking_seconds / SECONDS_PER_MINUTE)
            )
            phonation = _measured("phonation_time_ratio", speaking_seconds / duration_seconds)
        else:
            articulation = _unavailable("articulation_rate_wpm", "no_speaking_time")
            phonation = _unavailable("phonation_time_ratio", "no_speaking_time")

    return FluencyMetrics(
        response_duration_seconds=_measured("response_duration_seconds", duration_seconds),
        speech_rate_wpm=speech_rate,
        articulation_rate_wpm=articulation,
        phonation_time_ratio=phonation,
        mean_length_of_run=mean_run,
        pause_count_250_499_ms=_measured(
            "pause_count_250_499_ms",
            Decimal(sum(1 for pause in pauses if pause < SHORT_PAUSE_CEILING_MS)),
        ),
        pause_count_500_999_ms=_measured(
            "pause_count_500_999_ms",
            Decimal(
                sum(1 for pause in pauses if SHORT_PAUSE_CEILING_MS <= pause < LONG_PAUSE_FLOOR_MS)
            ),
        ),
        pause_count_1000_ms_plus=_measured(
            "pause_count_1000_ms_plus",
            Decimal(sum(1 for pause in pauses if pause >= LONG_PAUSE_FLOOR_MS)),
        ),
        pause_seconds_total=_measured(
            "pause_seconds_total", Decimal(sum(pauses)) / MILLISECONDS_PER_SECOND
        ),
    )


__all__ = ["FluencyMetrics", "calculate_fluency"]

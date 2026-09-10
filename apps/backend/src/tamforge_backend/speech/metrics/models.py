"""Versioned speech-metric values that report unavailable instead of a made-up number.

A metric is one of two shapes and never a third: `MeasuredMetric` carries a value,
`UnavailableMetric` carries a reason code and has no value attribute at all. That is
deliberate. A single class with an optional value invites a caller to read `or 0` and
publish a fabricated zero for a response that was never measurable.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import ClassVar, Final, Literal
from uuid import UUID

METRICS_VERSION: Final = "speech-metrics-v1"
FILLER_LEXICON_VERSION: Final = "fillers-v1"

# Under either bound a rate describes the sample rather than the speaker, so version 1
# reports it unavailable instead of dividing anyway. Direct measurements (duration,
# pause counts) are not gated: they are what they are at any length.
MIN_RESPONSE_SECONDS: Final = Decimal("10")
MIN_RECOGNIZED_WORDS: Final = 20

# Version-1 pause bands, in milliseconds. A gap shorter than the first band is
# articulation, not a pause, and never reaches a band or the pause total.
PAUSE_FLOOR_MS: Final = 250
SHORT_PAUSE_CEILING_MS: Final = 500
LONG_PAUSE_FLOOR_MS: Final = 1_000

MILLISECONDS_PER_SECOND: Final = Decimal(1_000)
SECONDS_PER_MINUTE: Final = Decimal(60)

Unit = Literal["words_per_minute", "seconds", "ratio", "words", "count", "milliseconds"]
MeasurementStatus = Literal["validated", "detected_minimum"]


class SpeechMetricsError(ValueError):
    """Inputs cannot produce a version-1 report; the message never carries transcript text."""


@dataclass(frozen=True, slots=True)
class MeasuredMetric:
    name: str
    unit: Unit
    value: Decimal
    measurement_status: MeasurementStatus = "validated"
    availability: ClassVar[Literal["measured"]] = "measured"


@dataclass(frozen=True, slots=True)
class UnavailableMetric:
    name: str
    unit: Unit
    reason_code: str
    availability: ClassVar[Literal["unavailable"]] = "unavailable"


Metric = MeasuredMetric | UnavailableMetric


@dataclass(frozen=True, slots=True)
class MetricEvidence:
    """Everything needed to recompute or discard a report without reading transcript text."""

    metrics_version: str
    filler_lexicon_version: str
    recording_id: UUID
    microphone_transcript_id: int
    microphone_content_hash: str
    derivation_version: str
    model_sha256: str
    used_builtin_vad: bool
    token_count: int
    recognized_word_count: int
    system_audio_transcript_id: int | None = None
    system_audio_content_hash: str | None = None


@dataclass(frozen=True, slots=True)
class SpeechMetricsReport:
    evidence: MetricEvidence
    response_duration_seconds: Metric
    speech_rate_wpm: Metric
    articulation_rate_wpm: Metric
    phonation_time_ratio: Metric
    mean_length_of_run: Metric
    pause_count_250_499_ms: Metric
    pause_count_500_999_ms: Metric
    pause_count_1000_ms_plus: Metric
    pause_seconds_total: Metric
    filler_count: Metric
    restart_count: Metric
    response_latency_ms: Metric


__all__ = [
    "FILLER_LEXICON_VERSION",
    "LONG_PAUSE_FLOOR_MS",
    "METRICS_VERSION",
    "MILLISECONDS_PER_SECOND",
    "MIN_RECOGNIZED_WORDS",
    "MIN_RESPONSE_SECONDS",
    "PAUSE_FLOOR_MS",
    "SECONDS_PER_MINUTE",
    "SHORT_PAUSE_CEILING_MS",
    "MeasuredMetric",
    "MeasurementStatus",
    "Metric",
    "MetricEvidence",
    "SpeechMetricsError",
    "SpeechMetricsReport",
    "UnavailableMetric",
    "Unit",
]

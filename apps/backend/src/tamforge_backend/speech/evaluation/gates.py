"""Decision-grade gates: what speech evidence must clear before a decision may rest on it.

A transcript's timing is decision-grade when every word has a span, the spans never run
backwards or overlap, and they cover the recording rather than a fragment of it. Pauses
are decision-grade when the version-1 pause metrics were measured, not reported
unavailable. Pronunciation is decision-grade only when the calibrated pipeline produced a
measured assessment. Anything short of that is `unavailable` with the gate that failed
named, and unavailable is a state a decision must show, never a zero it may quietly use.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

from ..metrics import MeasuredMetric, SpeechMetricsReport
from ..pronunciation.pipeline import PronunciationAssessment
from ..schemas import TranscriptWord

MIN_TIMING_COVERAGE: Final = 0.60

GateStatus = Literal["decision_grade", "unavailable"]


@dataclass(frozen=True, slots=True)
class GateVerdict:
    gate: Literal["timing", "pauses", "pronunciation"]
    status: GateStatus
    reason: str | None


def timing_gate(words: tuple[TranscriptWord, ...], *, duration_ms: int) -> GateVerdict:
    if not words:
        return GateVerdict("timing", "unavailable", "no words")
    if duration_ms <= 0:
        return GateVerdict("timing", "unavailable", "no duration")
    previous_end = 0
    covered = 0
    for word in words:
        if word.start_ms < previous_end:
            return GateVerdict("timing", "unavailable", "word spans overlap or run backwards")
        if word.end_ms > duration_ms:
            return GateVerdict("timing", "unavailable", "a word ends after the recording")
        covered += word.end_ms - word.start_ms
        previous_end = word.end_ms
    span = words[-1].end_ms - words[0].start_ms
    if span / duration_ms < MIN_TIMING_COVERAGE:
        return GateVerdict("timing", "unavailable", "timed words cover too little of the recording")
    return GateVerdict("timing", "decision_grade", None)


def pause_gate(report: SpeechMetricsReport) -> GateVerdict:
    metrics = (
        report.pause_count_250_499_ms,
        report.pause_count_500_999_ms,
        report.pause_count_1000_ms_plus,
        report.pause_seconds_total,
    )
    for metric in metrics:
        if not isinstance(metric, MeasuredMetric):
            return GateVerdict("pauses", "unavailable", f"{metric.name}: {metric.reason_code}")
    return GateVerdict("pauses", "decision_grade", None)


def pronunciation_gate(assessment: PronunciationAssessment) -> GateVerdict:
    if assessment.availability != "measured":
        return GateVerdict("pronunciation", "unavailable", assessment.reason_code or "not_measured")
    if assessment.measured_words == 0:
        return GateVerdict("pronunciation", "unavailable", "every word was excluded")
    return GateVerdict("pronunciation", "decision_grade", None)


@dataclass(frozen=True, slots=True)
class DecisionGrade:
    timing: GateVerdict
    pauses: GateVerdict
    pronunciation: GateVerdict

    @property
    def available(self) -> frozenset[str]:
        return frozenset(
            v.gate
            for v in (self.timing, self.pauses, self.pronunciation)
            if v.status == "decision_grade"
        )

    @property
    def unavailable(self) -> dict[str, str]:
        return {
            v.gate: v.reason or "unavailable"
            for v in (self.timing, self.pauses, self.pronunciation)
            if v.status != "decision_grade"
        }


def decision_grade(
    *,
    words: tuple[TranscriptWord, ...],
    duration_ms: int,
    report: SpeechMetricsReport,
    pronunciation: PronunciationAssessment,
) -> DecisionGrade:
    return DecisionGrade(
        timing=timing_gate(words, duration_ms=duration_ms),
        pauses=pause_gate(report),
        pronunciation=pronunciation_gate(pronunciation),
    )


__all__ = [
    "MIN_TIMING_COVERAGE",
    "DecisionGrade",
    "GateVerdict",
    "decision_grade",
    "pause_gate",
    "pronunciation_gate",
    "timing_gate",
]

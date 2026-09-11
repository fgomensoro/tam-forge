"""Pronunciation stays `not_measured` until a calibration says otherwise, and never scores accent.

A pronunciation assessment is per word: how intelligible the word was, how sure the
pipeline is, and what correction, if any, it proposes. It is produced only when a
`Calibration` record exists for the aligner in use, on the private gold set, with an
agreement against human labels at or above the approved floor. Without that record the
assessment is `not_measured` for every word, with the reason stated, and nothing downstream
may treat the absence as a score.

Spans the system track flagged as contaminated by echo or crosstalk are excluded rather
than rewritten. There is no accent field, no nativeness, no country: the vocabulary is
intelligibility, uncertainty and correction, and the type has no place to put anything else.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal

from ..schemas import TranscriptWord

CALIBRATION_FLOOR: Final = 0.80

Intelligibility = Literal["clear", "unclear", "not_measured"]


class PronunciationError(ValueError):
    """An assessment that would score without calibration or on a contaminated span."""


@dataclass(frozen=True, slots=True)
class Calibration:
    """Evidence that one aligner's scores agree with human labels on the private gold set."""

    aligner_key: str
    gold_set_sha256: str
    labelled_words: int
    agreement: float
    calibrated_at: datetime

    def __post_init__(self) -> None:
        if not 0.0 <= self.agreement <= 1.0:
            raise PronunciationError("agreement is a proportion")
        if self.labelled_words < 1:
            raise PronunciationError("a calibration rests on labelled words")

    @property
    def passed(self) -> bool:
        return self.agreement >= CALIBRATION_FLOOR


@dataclass(frozen=True, slots=True)
class WordAssessment:
    text: str
    start_ms: int
    end_ms: int
    intelligibility: Intelligibility
    uncertainty: float
    correction: str | None
    excluded_reason: Literal["crosstalk", "echo"] | None = None


@dataclass(frozen=True, slots=True)
class PronunciationAssessment:
    aligner_key: str | None
    availability: Literal["measured", "not_measured"]
    reason_code: str | None
    words: tuple[WordAssessment, ...]

    @property
    def measured_words(self) -> int:
        return sum(1 for w in self.words if w.intelligibility != "not_measured")


@dataclass(frozen=True, slots=True)
class ContaminatedSpan:
    start_ms: int
    end_ms: int
    reason: Literal["crosstalk", "echo"]


def _overlaps(word: TranscriptWord, span: ContaminatedSpan) -> bool:
    return word.start_ms < span.end_ms and span.start_ms < word.end_ms


def assess(
    words: tuple[TranscriptWord, ...],
    *,
    calibration: Calibration | None,
    aligner_key: str,
    contaminated: tuple[ContaminatedSpan, ...] = (),
    scorer: object | None = None,
) -> PronunciationAssessment:
    """Per-word intelligibility only when calibrated; otherwise every word is not_measured."""
    if calibration is None or calibration.aligner_key != aligner_key or not calibration.passed:
        reason = "pronunciation_not_measured"
        return PronunciationAssessment(
            aligner_key=None,
            availability="not_measured",
            reason_code=reason,
            words=tuple(
                WordAssessment(w.text.strip(), w.start_ms, w.end_ms, "not_measured", 1.0, None)
                for w in words
            ),
        )
    if scorer is None or not callable(scorer):
        raise PronunciationError("a calibrated assessment needs the aligner's scorer")
    assessed: list[WordAssessment] = []
    for word in words:
        span = next((s for s in contaminated if _overlaps(word, s)), None)
        if span is not None:
            assessed.append(
                WordAssessment(
                    word.text.strip(),
                    word.start_ms,
                    word.end_ms,
                    "not_measured",
                    1.0,
                    None,
                    span.reason,
                )
            )
            continue
        score, uncertainty, correction = scorer(word)
        if not 0.0 <= score <= 1.0 or not 0.0 <= uncertainty <= 1.0:
            raise PronunciationError("scores and uncertainty are proportions")
        assessed.append(
            WordAssessment(
                word.text.strip(),
                word.start_ms,
                word.end_ms,
                "clear" if score >= 0.5 else "unclear",
                round(uncertainty, 3),
                correction,
            )
        )
    return PronunciationAssessment(
        aligner_key=aligner_key, availability="measured", reason_code=None, words=tuple(assessed)
    )


__all__ = [
    "CALIBRATION_FLOOR",
    "Calibration",
    "ContaminatedSpan",
    "Intelligibility",
    "PronunciationAssessment",
    "PronunciationError",
    "WordAssessment",
    "assess",
]

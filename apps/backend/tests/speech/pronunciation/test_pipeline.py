"""Pronunciation is not_measured until calibrated, excludes contaminated spans, has no accent."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from tamforge_backend.speech.pronunciation.pipeline import (
    CALIBRATION_FLOOR,
    Calibration,
    ContaminatedSpan,
    PronunciationAssessment,
    PronunciationError,
    WordAssessment,
    assess,
)
from tamforge_backend.speech.schemas import TranscriptWord

WORDS = (
    TranscriptWord(text=" the", start_ms=0, end_ms=200, probability=0.9),
    TranscriptWord(text=" churn", start_ms=250, end_ms=700, probability=0.6),
    TranscriptWord(text=" cohort", start_ms=800, end_ms=1200, probability=0.4),
)
PASSED = Calibration("mfa", "a" * 64, 500, 0.86, datetime(2026, 9, 20, tzinfo=UTC))
FAILED = Calibration("mfa", "a" * 64, 500, 0.61, datetime(2026, 9, 20, tzinfo=UTC))


def scorer(word: TranscriptWord) -> tuple[float, float, str | None]:
    return (
        word.probability,
        round(1 - word.probability, 3),
        "cohort" if word.text.strip() == "cohort" else None,
    )


def test_without_a_calibration_every_word_is_not_measured_with_the_reason() -> None:
    result = assess(WORDS, calibration=None, aligner_key="mfa")
    assert (
        result.availability == "not_measured" and result.reason_code == "pronunciation_not_measured"
    )
    assert all(w.intelligibility == "not_measured" for w in result.words)
    assert result.measured_words == 0


def test_a_failed_or_foreign_calibration_does_not_unlock_scoring() -> None:
    assert FAILED.passed is False and CALIBRATION_FLOOR == 0.80
    assert (
        assess(WORDS, calibration=FAILED, aligner_key="mfa", scorer=scorer).availability
        == "not_measured"
    )
    other = Calibration("wav2vec2-ctc", "a" * 64, 500, 0.9, datetime(2026, 9, 20, tzinfo=UTC))
    assert (
        assess(WORDS, calibration=other, aligner_key="mfa", scorer=scorer).availability
        == "not_measured"
    )


def test_a_passed_calibration_yields_intelligibility_uncertainty_and_corrections() -> None:
    result = assess(WORDS, calibration=PASSED, aligner_key="mfa", scorer=scorer)
    assert result.availability == "measured" and result.aligner_key == "mfa"
    assert [w.intelligibility for w in result.words] == ["clear", "clear", "unclear"]
    assert result.words[2].correction == "cohort" and result.words[2].uncertainty == 0.6
    assert result.measured_words == 3


def test_contaminated_spans_are_excluded_never_rewritten() -> None:
    result = assess(
        WORDS,
        calibration=PASSED,
        aligner_key="mfa",
        scorer=scorer,
        contaminated=(ContaminatedSpan(240, 720, "crosstalk"),),
    )
    churn = result.words[1]
    assert churn.intelligibility == "not_measured" and churn.excluded_reason == "crosstalk"
    assert churn.text == "churn" and result.measured_words == 2


def test_the_assessment_has_no_place_for_accent_or_nativeness() -> None:
    fields = set(WordAssessment.__dataclass_fields__) | set(
        PronunciationAssessment.__dataclass_fields__
    )
    for forbidden in ("accent", "nativeness", "native", "country", "l1"):
        assert not any(forbidden in f for f in fields)


def test_a_calibrated_assessment_refuses_a_missing_or_out_of_range_scorer() -> None:
    with pytest.raises(PronunciationError, match="scorer"):
        assess(WORDS, calibration=PASSED, aligner_key="mfa")
    with pytest.raises(PronunciationError, match="proportions"):
        assess(WORDS, calibration=PASSED, aligner_key="mfa", scorer=lambda w: (1.5, 0.1, None))


def test_a_calibration_needs_labelled_words_and_a_proportion() -> None:
    with pytest.raises(PronunciationError):
        Calibration("mfa", "a" * 64, 0, 0.9, datetime(2026, 9, 20, tzinfo=UTC))
    with pytest.raises(PronunciationError):
        Calibration("mfa", "a" * 64, 10, 1.4, datetime(2026, 9, 20, tzinfo=UTC))

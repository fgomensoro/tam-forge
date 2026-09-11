"""PCM16 stays unless a blinded evaluation shows a gain larger than its own uncertainty."""

from __future__ import annotations

import pytest
from tamforge_backend.speech.evaluation.pcm_format import (
    BYTES_PER_HOUR,
    DEFAULT_FORMAT,
    BlindedEvaluation,
    OutcomeMeasurement,
    PcmDecisionError,
    decide,
    fits_the_spool,
)

SHA = "c" * 64


def test_the_default_is_pcm16_at_about_one_gigabyte_per_hour() -> None:
    assert DEFAULT_FORMAT == "pcm_s16le"
    assert round(BYTES_PER_HOUR["pcm_s16le"] / 1e9, 2) == 1.04
    assert round(BYTES_PER_HOUR["pcm_s24le"] / 1e9, 2) == 1.56


def test_without_an_evaluation_the_decision_is_pcm16_and_says_so() -> None:
    decision = decide(None)
    assert decision.chosen == "pcm_s16le" and "no blinded evaluation" in decision.reason
    assert decision.extra_bytes_per_hour == 0


def test_a_gain_inside_the_uncertainty_does_not_change_the_format() -> None:
    evaluation = BlindedEvaluation(
        SHA, True, (OutcomeMeasurement("critical_word_recovery", 0.91, 0.92, 0.02),)
    )
    decision = decide(evaluation)
    assert decision.chosen == "pcm_s16le" and decision.material_outcomes == ()


def test_a_gain_beyond_the_uncertainty_in_one_primary_outcome_switches_to_pcm24() -> None:
    evaluation = BlindedEvaluation(
        SHA,
        True,
        (
            OutcomeMeasurement("critical_word_recovery", 0.91, 0.92, 0.02),
            OutcomeMeasurement("alignment_reliability", 0.80, 0.88, 0.03),
        ),
    )
    decision = decide(evaluation)
    assert decision.chosen == "pcm_s24le" and decision.material_outcomes == (
        "alignment_reliability",
    )
    assert (
        decision.extra_bytes_per_hour == BYTES_PER_HOUR["pcm_s24le"] - BYTES_PER_HOUR["pcm_s16le"]
    )


def test_an_unblinded_or_empty_evaluation_cannot_decide() -> None:
    with pytest.raises(PcmDecisionError, match="blinded"):
        BlindedEvaluation(SHA, False, (OutcomeMeasurement("human_intelligibility", 3.0, 3.9, 0.1),))
    with pytest.raises(PcmDecisionError, match="at least one"):
        BlindedEvaluation(SHA, True, ())


def test_two_hours_of_pcm16_fit_the_spool_cap_and_pcm24_does_not() -> None:
    assert fits_the_spool(minutes=120, fmt="pcm_s16le")
    assert not fits_the_spool(minutes=120, fmt="pcm_s24le")
    assert not fits_the_spool(minutes=121, fmt="pcm_s16le")

"""The class analysis role: half points, verbatim examples, honest comparison, no claims."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from tamforge_backend.agents.roles.class_analysis import (
    ClassAnalysisRequest,
    ClassRecord,
    PreviousClass,
    render_class_analysis_prompt,
    validate_class_analysis,
    vocabulary_metrics,
)

TRANSCRIPT = (
    "[0] Teacher: How was your week?\n"
    "[2100] Learner: It was good, I have worked on the webhook runbook."
)


def _payload(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "fluency": {"score": "3.0", "rationale": "Keeps going.", "evidence": "I have worked"},
        "vocabulary": {"score": "2.5", "rationale": "Precise.", "evidence": "webhook runbook"},
        "recurring_errors": [
            {
                "pattern": "present perfect for finished past",
                "example": "I have worked on the webhook runbook",
                "correction": "I worked on the webhook runbook",
            }
        ],
        "progress_direction": "up",
        "progress_statement": "Half a point up on fluency.",
        "next_focus": "Simple past narration.",
    }
    base.update(overrides)
    return base


def test_a_quoted_half_point_analysis_passes_and_the_comparison_must_match_history() -> None:
    assert validate_class_analysis(_payload(), transcript=TRANSCRIPT, previous_count=1) == ()
    first = _payload(progress_direction="first_class")
    assert validate_class_analysis(first, transcript=TRANSCRIPT, previous_count=0) == ()
    assert (
        "first_class"
        in validate_class_analysis(_payload(), transcript=TRANSCRIPT, previous_count=0)[0]
    )
    assert "previous" in validate_class_analysis(first, transcript=TRANSCRIPT, previous_count=1)[0]


def test_quarter_points_invented_examples_and_claims_are_refused() -> None:
    quarter = _payload(fluency={"score": "2.75", "rationale": "x", "evidence": "webhook"})
    assert (
        "half points"
        in validate_class_analysis(quarter, transcript=TRANSCRIPT, previous_count=1)[0]
    )
    invented = _payload(vocabulary={"score": "2.5", "rationale": "x", "evidence": "we lost money"})
    assert (
        "verbatim" in validate_class_analysis(invented, transcript=TRANSCRIPT, previous_count=1)[0]
    )
    bad_example = _payload(
        recurring_errors=[{"pattern": "articles", "example": "I go to office", "correction": "x"}]
    )
    assert (
        "example"
        in validate_class_analysis(bad_example, transcript=TRANSCRIPT, previous_count=1)[0]
    )
    claim = _payload(next_focus="I scheduled the next class.")
    assert "claim" in validate_class_analysis(claim, transcript=TRANSCRIPT, previous_count=1)[0]
    shape = _payload(recurring_errors=[])
    assert validate_class_analysis(shape, transcript=TRANSCRIPT, previous_count=1)[0].startswith(
        "analysis "
    )


def test_vocabulary_metrics_count_types_and_tokens() -> None:
    metrics = vocabulary_metrics("The webhook runbook explains retries; the runbook is short.")
    assert metrics["learner_words"] == 9 and metrics["unique_words"] == 7
    assert metrics["type_token_ratio"] == round(7 / 9, 3)
    assert metrics["long_word_types"] == 1
    assert vocabulary_metrics("")["type_token_ratio"] == 0.0


def test_the_prompt_carries_the_record_measures_history_and_transcript() -> None:
    request = ClassAnalysisRequest(
        record=ClassRecord("Maria", datetime(2026, 9, 18, 18, tzinfo=UTC), 60, "Past tense."),
        transcript=TRANSCRIPT,
        speech_metrics={"speech_rate_wpm": 118},
        vocabulary_metrics={"unique_words": 7},
        previous=(
            PreviousClass(
                datetime(2026, 9, 11, 18, tzinfo=UTC), Decimal("2.5"), Decimal("2"), ("articles",)
            ),
        ),
        repair_errors=("fluency must be scored in half points",),
    )
    prompt = render_class_analysis_prompt(request)
    assert "English class with Maria on 2026-09-18, 60 minutes planned." in prompt
    assert "Teacher notes:\nPast tense." in prompt
    assert "- speech_rate_wpm: 118" in prompt and "- unique_words: 7" in prompt
    assert "- 2026-09-11: fluency 2.5, vocabulary 2; errors: articles" in prompt
    assert "fix these:\n- fluency must be scored" in prompt
    alone = render_class_analysis_prompt(
        ClassAnalysisRequest(
            record=request.record, transcript=TRANSCRIPT, speech_metrics={}, vocabulary_metrics={}
        )
    )
    assert "progress_direction is first_class" in alone

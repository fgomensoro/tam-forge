from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from tamforge_backend.evidence.confidence import (
    SkillEvidence,
    classify_confidence,
    classify_recency,
)
from tamforge_backend.evidence.config_loader import load_config_bundle
from tamforge_backend.evidence.trend import calculate_trend

CONFIG_DIR = Path(__file__).parents[5] / "config"
NOW = datetime(2026, 8, 28, 12, tzinfo=UTC)


def item(
    event_id: int,
    score: str,
    *,
    weight: str = "1",
    exercise: str = "exercise_a",
    mode: str = "independent_practice",
    days_ago: int = 0,
    reviewed: bool = False,
    recording: bool = False,
) -> SkillEvidence:
    return SkillEvidence(
        event_id=event_id,
        performance_score=Decimal(score),
        effective_weight=Decimal(weight),
        qualifying_for_level=True,
        exercise_type=exercise,
        scenario_key=f"scenario-{event_id}",
        occurred_at=NOW - timedelta(days=days_ago, seconds=100 - event_id),
        practice_mode=mode,
        attempt_kind="attempt_a",
        reviewed_artifact=reviewed,
        scored_recording=recording,
    )


def test_confidence_is_evaluated_high_then_medium_then_low() -> None:
    formula = load_config_bundle(CONFIG_DIR).formula
    high_events = tuple(
        item(
            index,
            "3",
            exercise=f"exercise_{index % 3}",
            mode="mock_interview" if index == 1 else "independent_practice",
            reviewed=index == 1,
        )
        for index in range(1, 8)
    )
    medium_events = (
        item(1, "3", exercise="a"),
        item(2, "3", exercise="b"),
        item(3, "3", exercise="a"),
    )

    high = classify_confidence(high_events, formula=formula, as_of=NOW)
    medium = classify_confidence(medium_events, formula=formula, as_of=NOW)
    low = classify_confidence(medium_events[:1], formula=formula, as_of=NOW)
    assert (high.code, high.basis_code) == ("high", "high_weight_diversity_recency")
    assert (medium.code, medium.basis_code) == ("medium", "medium_weight_diversity")
    assert (low.code, low.basis_code) == ("low", "low_weight")


def test_trend_uses_latest_three_vs_preceding_three_and_versioned_delta() -> None:
    formula = load_config_bundle(CONFIG_DIR).formula
    improving = tuple(item(index, "1" if index <= 3 else "2") for index in range(1, 7))
    declining = tuple(item(index, "3" if index <= 3 else "2") for index in range(1, 7))
    stable = tuple(item(index, "2.0" if index <= 3 else "2.1") for index in range(1, 7))

    assert calculate_trend(improving, rules=formula.trend).code == "improving"
    assert calculate_trend(declining, rules=formula.trend).code == "declining"
    assert calculate_trend(stable, rules=formula.trend).code == "stable"
    assert calculate_trend(improving[:5], rules=formula.trend).code == "insufficient_evidence"


def test_recency_is_separate_and_absence_never_becomes_decline() -> None:
    rules = load_config_bundle(CONFIG_DIR).formula.recency
    assert classify_recency((item(1, "3", days_ago=7),), rules=rules, as_of=NOW).code == "fresh"
    assert classify_recency((item(1, "3", days_ago=8),), rules=rules, as_of=NOW).code == "aging"
    assert classify_recency((item(1, "3", days_ago=22),), rules=rules, as_of=NOW).code == "stale"
    empty_trend = calculate_trend((), rules=load_config_bundle(CONFIG_DIR).formula.trend)
    assert empty_trend.code == "insufficient_evidence"

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from tamforge_backend.evidence.confidence import SkillEvidence, estimate_skill
from tamforge_backend.evidence.config_loader import load_config_bundle

CONFIG_DIR = Path(__file__).parents[5] / "config"
NOW = datetime(2026, 8, 28, 12, tzinfo=UTC)


def event(
    event_id: int,
    *,
    score: str = "3",
    weight: str = "1",
    days_ago: int = 0,
    exercise: str = "troubleshooting_case",
    scenario: str = "scenario-a",
    qualifying: bool = True,
) -> SkillEvidence:
    return SkillEvidence(
        event_id=event_id,
        performance_score=Decimal(score),
        effective_weight=Decimal(weight),
        qualifying_for_level=qualifying,
        exercise_type=exercise,
        scenario_key=scenario,
        occurred_at=NOW - timedelta(days=days_ago, seconds=100 - event_id),
        practice_mode="independent_practice",
        attempt_kind="attempt_a",
        reviewed_artifact=False,
        scored_recording=False,
    )


def test_estimator_uses_prior_latest_twelve_and_inspectable_exclusions() -> None:
    formula = load_config_bundle(CONFIG_DIR).formula
    events = tuple(
        event(
            item,
            score=str((item % 4) + 1),
            days_ago=13 - item,
            exercise=f"exercise_{item % 3}",
            scenario=f"scenario-{item}",
        )
        for item in range(1, 14)
    ) + (event(99, qualifying=False),)
    result = estimate_skill(
        baseline=Decimal("1"),
        month_one_target=Decimal("2"),
        final_target=Decimal("3"),
        events=events,
        formula=formula,
        as_of=NOW,
    )

    assert result.formula_version == "seed-v1"
    assert len(result.contributing_event_ids) == 12
    assert 1 in result.excluded_event_ids
    assert 99 in result.excluded_event_ids
    assert result.qualifying_event_count == 12
    assert result.estimate == (
        (Decimal("1") * Decimal("2") + sum(
            item.performance_score * item.effective_weight for item in events[1:13]
        ))
        / Decimal("14")
    ).quantize(Decimal("0.001"))
    assert result.month_one_target_gap == Decimal("2") - result.estimate
    assert result.final_target_gap == Decimal("3") - result.estimate


def test_equivalent_same_day_repetition_is_discounted_after_two_events() -> None:
    result = estimate_skill(
        baseline=Decimal("2"),
        month_one_target=Decimal("3"),
        final_target=Decimal("3.5"),
        events=(event(1), event(2), event(3)),
        formula=load_config_bundle(CONFIG_DIR).formula,
        as_of=NOW,
    )

    assert result.discounted_event_ids == (3,)
    weights = {item.event_id: item.used_weight for item in result.weight_manifest}
    assert weights == {
        1: Decimal("1.000000"),
        2: Decimal("1.000000"),
        3: Decimal("0.250000"),
    }
    assert result.total_effective_weight == Decimal("2.250000")


def test_one_event_cannot_create_mastery_or_collapse_an_established_level() -> None:
    formula = load_config_bundle(CONFIG_DIR).formula
    rising = estimate_skill(
        baseline=Decimal("1"),
        month_one_target=Decimal("2"),
        final_target=Decimal("3"),
        events=(event(1, score="4", weight="1.15"),),
        formula=formula,
        as_of=NOW,
    )
    falling = estimate_skill(
        baseline=Decimal("4"),
        month_one_target=Decimal("3"),
        final_target=Decimal("3"),
        events=(event(1, score="0", weight="1.15"),),
        formula=formula,
        as_of=NOW,
    )
    assert rising.estimate < Decimal("3")
    assert falling.estimate > Decimal("2")


def test_historical_estimate_excludes_events_after_as_of() -> None:
    future = event(2)
    future = SkillEvidence(
        event_id=future.event_id,
        performance_score=Decimal("4"),
        effective_weight=future.effective_weight,
        qualifying_for_level=True,
        exercise_type=future.exercise_type,
        scenario_key="future-scenario",
        occurred_at=NOW + timedelta(days=1),
        practice_mode=future.practice_mode,
        attempt_kind=future.attempt_kind,
        reviewed_artifact=False,
        scored_recording=False,
    )
    result = estimate_skill(
        baseline=Decimal("2"),
        month_one_target=Decimal("3"),
        final_target=Decimal("3.5"),
        events=(event(1, score="3"), future),
        formula=load_config_bundle(CONFIG_DIR).formula,
        as_of=NOW,
    )

    assert result.contributing_event_ids == (1,)
    assert result.excluded_event_ids == (2,)

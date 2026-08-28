from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st
from tamforge_backend.evidence.confidence import SkillEvidence, estimate_skill
from tamforge_backend.evidence.config_loader import load_config_bundle
from tamforge_backend.evidence.scoring import (
    DimensionScoreInput,
    calculate_performance_score,
)

CONFIG_DIR = Path(__file__).parents[5] / "config"
FORMULA = load_config_bundle(CONFIG_DIR).formula
NOW = datetime(2026, 8, 28, tzinfo=UTC)


@given(
    scores=st.lists(
        st.decimals(min_value=0, max_value=4, places=3, allow_nan=False),
        min_size=1,
        max_size=12,
    ),
    weights=st.lists(
        st.decimals(min_value=Decimal("0.001"), max_value=1, places=3, allow_nan=False),
        min_size=1,
        max_size=12,
    ),
)
def test_weighted_scores_never_escape_zero_to_four(
    scores: list[Decimal],
    weights: list[Decimal],
) -> None:
    size = min(len(scores), len(weights))
    result = calculate_performance_score(
        tuple(
            DimensionScoreInput(f"dimension_{index}", scores[index], weights[index])
            for index in range(size)
        )
    )
    assert Decimal("0") <= result.score <= Decimal("4")


@given(
    baseline=st.decimals(min_value=0, max_value=4, places=3, allow_nan=False),
    event_scores=st.lists(
        st.decimals(min_value=0, max_value=4, places=3, allow_nan=False),
        min_size=0,
        max_size=20,
    ),
)
def test_skill_estimate_is_bounded_and_deterministic_under_input_permutation(
    baseline: Decimal,
    event_scores: list[Decimal],
) -> None:
    events = tuple(
        SkillEvidence(
            event_id=index + 1,
            performance_score=score,
            effective_weight=Decimal("0.75"),
            qualifying_for_level=True,
            exercise_type=f"exercise_{index % 4}",
            scenario_key=f"scenario-{index}",
            occurred_at=NOW - timedelta(days=len(event_scores) - index),
            practice_mode="independent_practice",
            attempt_kind="attempt_a",
            reviewed_artifact=False,
            scored_recording=False,
        )
        for index, score in enumerate(event_scores)
    )
    forward = estimate_skill(
        baseline=baseline,
        month_one_target=Decimal("3"),
        final_target=Decimal("3.5"),
        events=events,
        formula=FORMULA,
        as_of=NOW,
    )
    reversed_result = estimate_skill(
        baseline=baseline,
        month_one_target=Decimal("3"),
        final_target=Decimal("3.5"),
        events=tuple(reversed(events)),
        formula=FORMULA,
        as_of=NOW,
    )
    assert Decimal("0") <= forward.estimate <= Decimal("4")
    assert forward == reversed_result

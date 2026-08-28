from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from tamforge_backend.evidence.config_loader import load_config_bundle
from tamforge_backend.evidence.scoring import (
    DimensionScoreInput,
    ScoringError,
    calculate_effective_weight,
    calculate_performance_score,
    resolve_skill_impact,
)

CONFIG_DIR = Path(__file__).parents[5] / "config"


def test_weighted_performance_score_is_decimal_and_stays_on_zero_to_four() -> None:
    result = calculate_performance_score(
        (
            DimensionScoreInput("correctness", Decimal("4"), Decimal("0.60")),
            DimensionScoreInput("clarity", Decimal("2"), Decimal("0.40")),
        )
    )

    assert result.score == Decimal("3.200")
    assert result.weighted_sum == Decimal("3.20")
    assert result.weight_sum == Decimal("1.00")
    assert all(isinstance(value, Decimal) for value in (result.score, result.weight_sum))


@pytest.mark.parametrize(
    "dimensions",
    [
        (),
        (DimensionScoreInput("bad", Decimal("5"), Decimal("1")),),
        (DimensionScoreInput("bad", Decimal("2"), Decimal("0")),),
    ],
)
def test_performance_score_rejects_empty_invalid_or_zero_weight_input(
    dimensions: tuple[DimensionScoreInput, ...],
) -> None:
    with pytest.raises(ScoringError):
        calculate_performance_score(dimensions)


def test_effective_weight_uses_selected_formula_and_caps_outliers_deterministically() -> None:
    formula = load_config_bundle(CONFIG_DIR).formula
    standard = calculate_effective_weight(
        skill_impact=Decimal("1"),
        practice_mode="mock_interview",
        assistance="ai_after_committed_attempt",
        evaluator="ai_rubric_reviewer",
        difficulty="advanced",
        formula=formula,
    )
    capped_formula = formula.model_copy(
        update={"maximum_effective_weight_per_event": Decimal("0.80")}
    )
    capped = calculate_effective_weight(
        skill_impact=Decimal("1"),
        practice_mode="mock_interview",
        assistance="ai_after_committed_attempt",
        evaluator="explicit_interviewer_feedback",
        difficulty="advanced",
        formula=capped_formula,
    )

    assert standard.factors.assistance == Decimal("1.00")
    assert standard.raw_weight == Decimal("0.862500")
    assert standard.effective_weight == Decimal("0.862500")
    assert standard.capped is False
    assert capped.raw_weight == Decimal("1.150000")
    assert capped.effective_weight == Decimal("0.800000")
    assert capped.capped is True


def test_exposure_has_zero_weight_and_unknown_factor_names_fail_closed() -> None:
    formula = load_config_bundle(CONFIG_DIR).formula
    exposure = calculate_effective_weight(
        skill_impact=Decimal("1"),
        practice_mode="exposure_only",
        assistance="no_ai",
        evaluator="human_coach",
        difficulty="standard",
        formula=formula,
    )
    assert exposure.effective_weight == Decimal("0.000000")

    with pytest.raises(ScoringError, match="unknown"):
        calculate_effective_weight(
            skill_impact=Decimal("1"),
            practice_mode="invented",
            assistance="no_ai",
            evaluator="human_coach",
            difficulty="standard",
            formula=formula,
        )


def test_dynamic_impact_requires_reviewed_precommit_allowlist_selection() -> None:
    bundle = load_config_bundle(CONFIG_DIR)
    exercise = bundle.exercise("audience_switching_explanation")

    selected = resolve_skill_impact(
        exercise=exercise,
        skill_slug="sql_reconciliation",
        conditions_met={"spoken_or_written_english"},
        selected_competency="sql_reconciliation",
        selector_committed_before_attempt=True,
    )
    assert selected.weight == Decimal("0.30")
    assert selected.source == "precommit_selector"

    for value, committed in (("unknown_skill", True), ("sql_reconciliation", False)):
        with pytest.raises(ScoringError, match="precommit"):
            resolve_skill_impact(
                exercise=exercise,
                skill_slug=value,
                conditions_met={"spoken_or_written_english"},
                selected_competency=value,
                selector_committed_before_attempt=committed,
            )

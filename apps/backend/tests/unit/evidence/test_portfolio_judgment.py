from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from tamforge_backend.evidence.config_loader import load_config_bundle
from tamforge_backend.evidence.portfolio import (
    PortfolioHistoryItem,
    PortfolioScoringError,
    map_portfolio_skill_evidence,
    score_portfolio_judgment,
    validate_gauntlet_children,
)

CONFIG_DIR = Path(__file__).parents[5] / "config"


def components() -> dict[str, Decimal]:
    return {
        "impact_risk_assessment": Decimal("4"),
        "explicit_prioritization": Decimal("3"),
        "delegation_ownership": Decimal("3"),
        "communication_control": Decimal("3"),
        "proactive_work_protection": Decimal("2"),
        "evidence_based_reprioritization": Decimal("3"),
        "english_clarity": Decimal("2"),
    }


def test_portfolio_is_separate_zero_to_twenty_composite_not_fifteenth_skill() -> None:
    bundle = load_config_bundle(CONFIG_DIR)
    score = score_portfolio_judgment(
        component_scores=components(),
        rubric=bundle.portfolio,
        formula_version=bundle.formula.version,
        exercise_type="portfolio_triage",
        mapping_version=bundle.exercise("portfolio_triage").mapping_version,
    )
    assert score.metric_slug == "portfolio_judgment"
    assert score.total_score == Decimal("20.000")
    assert score.trend.code == "first_score"
    assert score.metric_slug not in {skill.slug for skill in bundle.skills}
    assert tuple(item.slug for item in score.components) == tuple(components())

    invalid = components()
    invalid["english_clarity"] = Decimal("2.1")
    with pytest.raises(PortfolioScoringError, match="maximum"):
        score_portfolio_judgment(
            component_scores=invalid,
            rubric=bundle.portfolio,
            formula_version=bundle.formula.version,
            exercise_type="portfolio_triage",
            mapping_version="seed-v1",
        )


def test_portfolio_attempt_requires_independent_underlying_skill_scores() -> None:
    bundle = load_config_bundle(CONFIG_DIR)
    exercise = bundle.exercise("portfolio_triage")
    skill_scores = {
        slug: Decimal("3")
        for slug in exercise.skill_impacts
        if slug != "tam_english"
    }
    skill_scores["tam_english"] = Decimal("2.5")
    mapped = map_portfolio_skill_evidence(
        exercise=exercise,
        skill_scores=skill_scores,
        conditions_met={"spoken_or_written_english"},
    )

    assert {item.skill_slug for item in mapped} == set(exercise.skill_impacts)
    assert {item.performance_score for item in mapped} == {Decimal("3"), Decimal("2.5")}
    assert all(item.exercise_type == "portfolio_triage" for item in mapped)

    with pytest.raises(PortfolioScoringError, match="independent score"):
        map_portfolio_skill_evidence(
            exercise=exercise,
            skill_scores={"portfolio_judgment": Decimal("4")},
            conditions_met={"spoken_or_written_english"},
        )


def test_gauntlet_accepts_only_concrete_versioned_child_exercises() -> None:
    bundle = load_config_bundle(CONFIG_DIR)
    gauntlet = bundle.exercise("full_tam_gauntlet")
    known = {(item.slug, item.mapping_version): item for item in bundle.exercise_types}
    children = validate_gauntlet_children(gauntlet=gauntlet, known_exercises=known)
    assert len(children) == 9
    assert all(child.slug != "full_tam_gauntlet" for child in children)

    with pytest.raises(PortfolioScoringError, match="concrete"):
        validate_gauntlet_children(gauntlet=gauntlet, known_exercises={})


def test_portfolio_history_has_its_own_trend() -> None:
    now = datetime(2026, 8, 28, tzinfo=UTC)
    history = tuple(
        PortfolioHistoryItem(
            score_id=index,
            total_score=Decimal("8") if index <= 3 else Decimal("12"),
            scored_at=now - timedelta(days=7 - index),
        )
        for index in range(1, 7)
    )
    result = score_portfolio_judgment(
        component_scores=components(),
        rubric=load_config_bundle(CONFIG_DIR).portfolio,
        formula_version="seed-v1",
        exercise_type="portfolio_triage",
        mapping_version="seed-v1",
        history=history,
    )
    assert result.trend.code == "improving"
    assert result.trend.event_ids == (1, 2, 3, 4, 5, 6)


def test_portfolio_trend_rejects_unknown_formula_versions() -> None:
    with pytest.raises(PortfolioScoringError, match="formula version"):
        score_portfolio_judgment(
            component_scores=components(),
            rubric=load_config_bundle(CONFIG_DIR).portfolio,
            formula_version="future-v99",
            exercise_type="portfolio_triage",
            mapping_version="seed-v1",
        )

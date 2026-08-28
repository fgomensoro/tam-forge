"""Portfolio Judgment composite and underlying skill mapping."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from .config_models import ExerciseTypeConfig, RubricConfig, TrendRules
from .trend import TrendResult, calculate_trend

SCORE_QUANTUM = Decimal("0.001")
_PORTFOLIO_TREND_RULES_BY_FORMULA = {
    "seed-v1": TrendRules(
        recent_event_count=3,
        preceding_event_count=3,
        minimum_delta=Decimal("1.25"),
    )
}


class PortfolioScoringError(ValueError):
    """Portfolio evidence is incomplete or violates its versioned contract."""


@dataclass(frozen=True, slots=True)
class PortfolioHistoryItem:
    score_id: int | str
    total_score: Decimal
    scored_at: datetime

    def __post_init__(self) -> None:
        if (
            not isinstance(self.total_score, Decimal)
            or not self.total_score.is_finite()
            or not Decimal("0") <= self.total_score <= Decimal("20")
        ):
            raise PortfolioScoringError("portfolio history score must be from 0 to 20")
        if self.scored_at.tzinfo is None or self.scored_at.utcoffset() is None:
            raise PortfolioScoringError("scored_at must be timezone-aware")

    @property
    def event_id(self) -> int | str:
        return self.score_id

    @property
    def performance_score(self) -> Decimal:
        return self.total_score

    @property
    def effective_weight(self) -> Decimal:
        return Decimal("1")

    @property
    def occurred_at(self) -> datetime:
        return self.scored_at


@dataclass(frozen=True, slots=True)
class PortfolioComponentScore:
    slug: str
    score: Decimal
    maximum: Decimal


@dataclass(frozen=True, slots=True)
class PortfolioScoreResult:
    metric_slug: str
    total_score: Decimal
    components: tuple[PortfolioComponentScore, ...]
    rubric_version: str
    formula_version: str
    exercise_type: str
    mapping_version: str
    trend: TrendResult


@dataclass(frozen=True, slots=True)
class PortfolioSkillEvidence:
    skill_slug: str
    performance_score: Decimal
    impact: Decimal
    exercise_type: str
    mapping_version: str


def score_portfolio_judgment(
    *,
    component_scores: Mapping[str, Decimal],
    rubric: RubricConfig,
    formula_version: str,
    exercise_type: str,
    mapping_version: str,
    history: tuple[PortfolioHistoryItem, ...] = (),
) -> PortfolioScoreResult:
    if rubric.slug != "portfolio_judgment" or rubric.scale_max != Decimal("20"):
        raise PortfolioScoringError("portfolio rubric must use the fixed 0 to 20 scale")
    try:
        trend_rules = _PORTFOLIO_TREND_RULES_BY_FORMULA[formula_version]
    except KeyError as exc:
        raise PortfolioScoringError("unknown portfolio formula version") from exc
    expected = tuple(item.slug for item in rubric.dimensions)
    if set(component_scores) != set(expected):
        raise PortfolioScoringError("every portfolio component requires an independent score")
    components: list[PortfolioComponentScore] = []
    for dimension in rubric.dimensions:
        value = component_scores[dimension.slug]
        if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
            raise PortfolioScoringError("component score must be a nonnegative Decimal")
        if value > dimension.maximum:
            raise PortfolioScoringError(
                f"{dimension.slug} exceeds its maximum {dimension.maximum}"
            )
        components.append(
            PortfolioComponentScore(dimension.slug, value, dimension.maximum)
        )
    total = sum((item.score for item in components), Decimal("0")).quantize(
        SCORE_QUANTUM, rounding=ROUND_HALF_UP
    )
    if not rubric.scale_min <= total <= rubric.scale_max:
        raise PortfolioScoringError("portfolio total escaped its configured scale")
    if not history:
        trend = TrendResult("first_score", None, None, None, ())
    else:
        trend = calculate_trend(history, rules=trend_rules)
    return PortfolioScoreResult(
        metric_slug="portfolio_judgment",
        total_score=total,
        components=tuple(components),
        rubric_version=rubric.version,
        formula_version=formula_version,
        exercise_type=exercise_type,
        mapping_version=mapping_version,
        trend=trend,
    )


def map_portfolio_skill_evidence(
    *,
    exercise: ExerciseTypeConfig,
    skill_scores: Mapping[str, Decimal],
    conditions_met: set[str] | frozenset[str],
) -> tuple[PortfolioSkillEvidence, ...]:
    if "portfolio_judgment" not in exercise.composite_metric_weights:
        raise PortfolioScoringError("exercise is not a portfolio-scored exercise")
    applicable = tuple(
        impact
        for impact in exercise.impacts
        if impact.condition == "always" or impact.condition in conditions_met
    )
    expected = {impact.skill_slug for impact in applicable}
    if set(skill_scores) != expected:
        raise PortfolioScoringError(
            "every applicable mapped skill requires an independent score"
        )
    mapped: list[PortfolioSkillEvidence] = []
    for impact in applicable:
        score = skill_scores[impact.skill_slug]
        if (
            not isinstance(score, Decimal)
            or not score.is_finite()
            or not Decimal("0") <= score <= Decimal("4")
        ):
            raise PortfolioScoringError("independent skill score must be from 0 to 4")
        mapped.append(
            PortfolioSkillEvidence(
                skill_slug=impact.skill_slug,
                performance_score=score,
                impact=impact.weight,
                exercise_type=exercise.slug,
                mapping_version=exercise.mapping_version,
            )
        )
    return tuple(mapped)


def validate_gauntlet_children(
    *,
    gauntlet: ExerciseTypeConfig,
    known_exercises: Mapping[tuple[str, str], ExerciseTypeConfig],
) -> tuple[ExerciseTypeConfig, ...]:
    if not gauntlet.component_scoring_required or not gauntlet.child_exercise_type_refs:
        raise PortfolioScoringError("gauntlet requires concrete versioned child exercises")
    children: list[ExerciseTypeConfig] = []
    for reference in gauntlet.child_exercise_type_refs:
        child = known_exercises.get((reference.exercise_type, reference.mapping_version))
        if child is None or child.slug == gauntlet.slug:
            raise PortfolioScoringError("gauntlet child must be a concrete versioned exercise")
        children.append(child)
    return tuple(children)

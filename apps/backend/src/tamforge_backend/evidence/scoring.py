"""Pure, versioned evidence scoring calculations."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from .config_models import ExerciseTypeConfig, FormulaConfig

SCORE_QUANTUM = Decimal("0.001")
WEIGHT_QUANTUM = Decimal("0.000001")


class ScoringError(ValueError):
    """The supplied evidence cannot be scored safely."""


def _decimal(value: object, *, name: str) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ScoringError(f"{name} must be a finite Decimal")
    return value


@dataclass(frozen=True, slots=True)
class DimensionScoreInput:
    slug: str
    score: Decimal
    weight: Decimal


@dataclass(frozen=True, slots=True)
class PerformanceScoreResult:
    score: Decimal
    weighted_sum: Decimal
    weight_sum: Decimal


@dataclass(frozen=True, slots=True)
class EffectiveWeightFactors:
    skill_impact: Decimal
    practice_mode: Decimal
    assistance: Decimal
    evaluator: Decimal
    difficulty: Decimal


@dataclass(frozen=True, slots=True)
class EffectiveWeightResult:
    factors: EffectiveWeightFactors
    raw_weight: Decimal
    effective_weight: Decimal
    capped: bool


@dataclass(frozen=True, slots=True)
class SkillImpactResult:
    weight: Decimal
    source: str


def calculate_performance_score(
    dimensions: tuple[DimensionScoreInput, ...],
) -> PerformanceScoreResult:
    if not dimensions:
        raise ScoringError("at least one rubric dimension is required")
    weighted_sum = Decimal("0")
    weight_sum = Decimal("0")
    seen: set[str] = set()
    for dimension in dimensions:
        if not dimension.slug.strip() or dimension.slug in seen:
            raise ScoringError("dimension slugs must be nonblank and unique")
        seen.add(dimension.slug)
        score = _decimal(dimension.score, name="dimension score")
        weight = _decimal(dimension.weight, name="dimension weight")
        if not Decimal("0") <= score <= Decimal("4"):
            raise ScoringError("dimension score must be between 0 and 4")
        if weight <= 0:
            raise ScoringError("dimension weight must be greater than zero")
        weighted_sum += score * weight
        weight_sum += weight
    if weight_sum <= 0:
        raise ScoringError("dimension weight denominator must be greater than zero")
    score = (weighted_sum / weight_sum).quantize(
        SCORE_QUANTUM, rounding=ROUND_HALF_UP
    )
    if not Decimal("0") <= score <= Decimal("4"):
        raise ScoringError("performance score escaped the configured scale")
    return PerformanceScoreResult(
        score=score,
        weighted_sum=weighted_sum,
        weight_sum=weight_sum,
    )


def _factor(group: object, name: str, *, category: str) -> Decimal:
    try:
        value = getattr(group, name)
    except AttributeError as exc:
        raise ScoringError(f"unknown {category} factor {name!r}") from exc
    return _decimal(value, name=f"{category} factor")


def calculate_effective_weight(
    *,
    skill_impact: Decimal,
    practice_mode: str,
    assistance: str,
    evaluator: str,
    difficulty: str,
    formula: FormulaConfig,
) -> EffectiveWeightResult:
    impact = _decimal(skill_impact, name="skill impact")
    if not Decimal("0") <= impact <= Decimal("1"):
        raise ScoringError("skill impact must be between 0 and 1")
    if practice_mode == "pipeline_only":
        practice_factor = Decimal("0")
    else:
        practice_factor = _factor(
            formula.practice_mode_factors, practice_mode, category="practice mode"
        )
    factors = EffectiveWeightFactors(
        skill_impact=impact,
        practice_mode=practice_factor,
        assistance=_factor(
            formula.assistance_factors, assistance, category="assistance"
        ),
        evaluator=_factor(formula.evaluator_factors, evaluator, category="evaluator"),
        difficulty=_factor(
            formula.difficulty_factors, difficulty, category="difficulty"
        ),
    )
    raw = (
        factors.skill_impact
        * factors.practice_mode
        * factors.assistance
        * factors.evaluator
        * factors.difficulty
    ).quantize(WEIGHT_QUANTUM, rounding=ROUND_HALF_UP)
    maximum = formula.maximum_effective_weight_per_event.quantize(
        WEIGHT_QUANTUM, rounding=ROUND_HALF_UP
    )
    effective = min(raw, maximum)
    return EffectiveWeightResult(
        factors=factors,
        raw_weight=raw,
        effective_weight=effective,
        capped=raw > maximum,
    )


def resolve_skill_impact(
    *,
    exercise: ExerciseTypeConfig,
    skill_slug: str,
    conditions_met: set[str] | frozenset[str],
    selected_competency: str | None = None,
    selector_committed_before_attempt: bool = False,
) -> SkillImpactResult:
    if selected_competency is not None:
        allowed = set(exercise.allowed_selected_competencies)
        if (
            exercise.required_precommit_field is None
            or not selector_committed_before_attempt
            or selected_competency not in allowed
        ):
            raise ScoringError("dynamic impact requires a valid precommit selection")
        if skill_slug == selected_competency:
            if exercise.selected_impact is None:
                raise ScoringError("dynamic impact has no configured weight")
            return SkillImpactResult(exercise.selected_impact, "precommit_selector")

    impact = exercise.skill_impacts.get(skill_slug)
    if impact is None:
        return SkillImpactResult(Decimal("0"), "unmapped")
    if impact.condition != "always" and impact.condition not in conditions_met:
        return SkillImpactResult(Decimal("0"), "condition_not_met")
    return SkillImpactResult(impact.weight, "exercise_mapping")

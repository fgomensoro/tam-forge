"""Inspectable skill estimates, confidence, and recency."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from .config_models import FormulaConfig, RecencyRules
from .trend import TrendResult, calculate_trend

SCORE_QUANTUM = Decimal("0.001")
WEIGHT_QUANTUM = Decimal("0.000001")


class EvidenceEstimateError(ValueError):
    """Evidence cannot be used to create a reliable estimate."""


@dataclass(frozen=True, slots=True)
class SkillEvidence:
    event_id: int | str
    performance_score: Decimal
    effective_weight: Decimal
    qualifying_for_level: bool
    exercise_type: str
    scenario_key: str
    occurred_at: datetime
    practice_mode: str
    attempt_kind: str
    reviewed_artifact: bool
    scored_recording: bool

    def __post_init__(self) -> None:
        if (
            not isinstance(self.performance_score, Decimal)
            or not self.performance_score.is_finite()
            or not Decimal("0") <= self.performance_score <= Decimal("4")
        ):
            raise EvidenceEstimateError("performance_score must be a Decimal from 0 to 4")
        if (
            not isinstance(self.effective_weight, Decimal)
            or not self.effective_weight.is_finite()
            or self.effective_weight < 0
        ):
            raise EvidenceEstimateError("effective_weight must be a nonnegative Decimal")
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise EvidenceEstimateError("occurred_at must be timezone-aware")
        if not self.exercise_type.strip() or not self.scenario_key.strip():
            raise EvidenceEstimateError("exercise_type and scenario_key must not be blank")


@dataclass(frozen=True, slots=True)
class ConfidenceResult:
    code: str
    basis_code: str
    effective_weight: Decimal
    exercise_type_count: int
    event_ids: tuple[int | str, ...]


@dataclass(frozen=True, slots=True)
class RecencyResult:
    code: str
    latest_evidence_at: datetime | None
    age_days: int | None


@dataclass(frozen=True, slots=True)
class EvidenceWeightManifestItem:
    event_id: int | str
    raw_weight: Decimal
    used_weight: Decimal
    inclusion: str


@dataclass(frozen=True, slots=True)
class SkillEstimateResult:
    formula_version: str
    estimate: Decimal
    contributing_event_ids: tuple[int | str, ...]
    excluded_event_ids: tuple[int | str, ...]
    discounted_event_ids: tuple[int | str, ...]
    qualifying_event_count: int
    weight_manifest: tuple[EvidenceWeightManifestItem, ...]
    total_effective_weight: Decimal
    month_one_target_gap: Decimal
    final_target_gap: Decimal
    confidence: ConfidenceResult
    trend: TrendResult
    recency: RecencyResult
    last_strong_evidence_at: datetime | None


def _validate_as_of(as_of: datetime) -> None:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise EvidenceEstimateError("as_of must be timezone-aware")


def _event_key(item: SkillEvidence) -> tuple[datetime, str]:
    return item.occurred_at, str(item.event_id)


def classify_confidence(
    events: tuple[SkillEvidence, ...], *, formula: FormulaConfig, as_of: datetime
) -> ConfidenceResult:
    _validate_as_of(as_of)
    qualifying = tuple(
        sorted(
            (
                item
                for item in events
                if item.qualifying_for_level and item.occurred_at <= as_of
            ),
            key=_event_key,
        )
    )
    total_weight = sum(
        (item.effective_weight for item in qualifying), Decimal("0")
    ).quantize(WEIGHT_QUANTUM, rounding=ROUND_HALF_UP)
    exercise_count = len({item.exercise_type for item in qualifying})
    assessment_cutoff = as_of - timedelta(days=formula.confidence.high_recent_assessment_days)
    has_recent_assessment = any(
        item.practice_mode in {"timed_assessment", "mock_interview"}
        and assessment_cutoff <= item.occurred_at <= as_of
        for item in qualifying
    )
    has_reviewed_output = any(
        item.reviewed_artifact or item.scored_recording for item in qualifying
    )
    high = (
        total_weight >= formula.confidence.high_minimum_effective_weight
        and exercise_count >= formula.confidence.high_minimum_exercise_types
        and has_recent_assessment
        and (
            has_reviewed_output
            or not formula.confidence.high_requires_reviewed_artifact_or_recording
        )
    )
    has_independent_attempt = any(
        item.practice_mode == "independent_practice"
        and item.attempt_kind == "attempt_a"
        for item in qualifying
    )
    medium = (
        total_weight >= formula.confidence.medium_minimum_effective_weight
        and exercise_count >= formula.confidence.medium_minimum_exercise_types
        and (
            has_independent_attempt
            or not formula.confidence.medium_requires_independent_attempt
        )
    )
    if high:
        code, basis = "high", "high_weight_diversity_recency"
    elif medium:
        code, basis = "medium", "medium_weight_diversity"
    else:
        code, basis = "low", "low_weight"
    return ConfidenceResult(
        code=code,
        basis_code=basis,
        effective_weight=total_weight,
        exercise_type_count=exercise_count,
        event_ids=tuple(item.event_id for item in qualifying),
    )


def classify_recency(
    events: tuple[SkillEvidence, ...], *, rules: RecencyRules, as_of: datetime
) -> RecencyResult:
    _validate_as_of(as_of)
    qualifying = tuple(
        item
        for item in events
        if item.qualifying_for_level and item.occurred_at <= as_of
    )
    if not qualifying:
        return RecencyResult("no_evidence", None, None)
    latest = max(item.occurred_at for item in qualifying)
    seconds = max(Decimal("0"), Decimal(str((as_of - latest).total_seconds())))
    age_days = int(seconds // Decimal("86400"))
    if age_days <= rules.fresh_max_days:
        code = "fresh"
    elif age_days <= rules.aging_max_days:
        code = "aging"
    else:
        code = "stale"
    return RecencyResult(code, latest, age_days)


def estimate_skill(
    *,
    baseline: Decimal,
    month_one_target: Decimal,
    final_target: Decimal,
    events: tuple[SkillEvidence, ...],
    formula: FormulaConfig,
    as_of: datetime,
) -> SkillEstimateResult:
    _validate_as_of(as_of)
    for name, value in (
        ("baseline", baseline),
        ("month_one_target", month_one_target),
        ("final_target", final_target),
    ):
        if (
            not isinstance(value, Decimal)
            or not value.is_finite()
            or not Decimal("0") <= value <= Decimal("4")
        ):
            raise EvidenceEstimateError(f"{name} must be a Decimal from 0 to 4")
    if len({item.event_id for item in events}) != len(events):
        raise EvidenceEstimateError("event IDs must be unique")

    for item in events:
        if item.effective_weight > formula.maximum_effective_weight_per_event:
            raise EvidenceEstimateError(
                "effective_weight exceeds the configured per-event maximum"
            )
    qualifying = sorted(
        (
            item
            for item in events
            if item.qualifying_for_level and item.occurred_at <= as_of
        ),
        key=_event_key,
    )
    selected = qualifying[-formula.latest_qualifying_events :]
    selected_ids = {item.event_id for item in selected}
    excluded = tuple(
        sorted(
            (item for item in events if item.event_id not in selected_ids),
            key=_event_key,
        )
    )

    group_counts: dict[tuple[str, str, object], int] = {}
    adjusted: list[SkillEvidence] = []
    manifest: list[EvidenceWeightManifestItem] = []
    discounted_ids: list[int | str] = []
    for item in selected:
        group = (item.exercise_type, item.scenario_key, item.occurred_at.date())
        rank = group_counts.get(group, 0) + 1
        group_counts[group] = rank
        raw_weight = item.effective_weight.quantize(
            WEIGHT_QUANTUM, rounding=ROUND_HALF_UP
        )
        discounted = rank > formula.full_weight_same_day_limit
        used_weight = raw_weight
        if discounted:
            used_weight = (raw_weight * formula.same_day_repetition_factor).quantize(
                WEIGHT_QUANTUM, rounding=ROUND_HALF_UP
            )
            discounted_ids.append(item.event_id)
        adjusted.append(replace(item, effective_weight=used_weight))
        manifest.append(
            EvidenceWeightManifestItem(
                event_id=item.event_id,
                raw_weight=raw_weight,
                used_weight=used_weight,
                inclusion="discounted_same_day" if discounted else "included",
            )
        )

    adjusted_events = tuple(adjusted)
    total_weight = sum(
        (item.effective_weight for item in adjusted_events), Decimal("0")
    ).quantize(WEIGHT_QUANTUM, rounding=ROUND_HALF_UP)
    denominator = formula.prior_weight + total_weight
    numerator = baseline * formula.prior_weight + sum(
        (item.performance_score * item.effective_weight for item in adjusted_events),
        Decimal("0"),
    )
    estimate = (numerator / denominator).quantize(
        SCORE_QUANTUM, rounding=ROUND_HALF_UP
    )
    strong_modes = {"timed_assessment", "mock_interview", "real_interview"}
    strong_dates = [
        item.occurred_at for item in adjusted_events if item.practice_mode in strong_modes
    ]
    return SkillEstimateResult(
        formula_version=formula.version,
        estimate=estimate,
        contributing_event_ids=tuple(item.event_id for item in adjusted_events),
        excluded_event_ids=tuple(item.event_id for item in excluded),
        discounted_event_ids=tuple(discounted_ids),
        qualifying_event_count=len(adjusted_events),
        weight_manifest=tuple(manifest),
        total_effective_weight=total_weight,
        month_one_target_gap=month_one_target - estimate,
        final_target_gap=final_target - estimate,
        confidence=classify_confidence(adjusted_events, formula=formula, as_of=as_of),
        trend=calculate_trend(adjusted_events, rules=formula.trend),
        recency=classify_recency(adjusted_events, rules=formula.recency, as_of=as_of),
        last_strong_evidence_at=max(strong_dates) if strong_dates else None,
    )

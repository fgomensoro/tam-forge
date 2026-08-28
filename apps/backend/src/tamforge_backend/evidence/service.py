"""Transactional evidence orchestration over pure versioned calculators."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from .config_models import (
    ExerciseTypeConfig,
    FormulaConfig,
    RubricConfig,
)
from .qualification import EvidenceCandidate, qualify_evidence
from .schemas import (
    EvidenceEvaluationCommand,
    EvidenceEventPage,
    PortfolioHistoryResponse,
    RecordEvaluationResponse,
    SkillListResponse,
    SkillSummaryResponse,
)
from .scoring import (
    DimensionScoreInput,
    calculate_effective_weight,
    calculate_performance_score,
    resolve_skill_impact,
)

_SAFE_IDEMPOTENCY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class EvidenceError(Exception):
    """Base safe evidence workflow error."""


class EvidenceNotFound(EvidenceError):
    """Owner-scoped evidence lineage was not found."""


class EvidenceConflict(EvidenceError):
    """Immutable evidence lineage or command state conflicts."""


class EvidenceInvalidRequest(EvidenceError):
    """Evidence command is structurally invalid."""


@dataclass(frozen=True, slots=True)
class PersistedDimension:
    id: int
    slug: str
    weight: Decimal
    maximum: Decimal


@dataclass(frozen=True, slots=True)
class PersistedSkill:
    id: int
    slug: str
    baseline: Decimal
    month_one_target: Decimal
    final_target: Decimal


@dataclass(frozen=True, slots=True)
class EvaluationContext:
    config_seed_version_id: int
    config_version_key: str
    formula: FormulaConfig
    exercise: ExerciseTypeConfig
    exercise_type_version_id: int
    rubric: RubricConfig
    rubric_version_id: int
    dimensions: tuple[PersistedDimension, ...]
    skills: Mapping[str, PersistedSkill]
    activity_id: int
    attempt_id: int
    attempt_kind: str
    attempt_assistance_mode: str
    attempt_committed_at: datetime
    self_review_submitted_at: datetime
    prompt: str
    selected_competency: str | None
    selector_field: str | None
    selector_committed_in_attempt: bool
    self_score: int
    linked_artifact_classes: Mapping[int, str]
    written_output_available: bool = False


@dataclass(frozen=True, slots=True)
class PreparedDimensionScore:
    dimension_id: int
    dimension_slug: str
    availability: str
    score: Decimal | None
    weight: Decimal | None
    artifact_ids: tuple[int, ...]
    observation_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class PreparedSkillEvent:
    skill_id: int
    skill_slug: str
    dimension_slugs: tuple[str, ...]
    performance_score: Decimal
    raw_score_numerator: Decimal
    raw_score_denominator: Decimal
    skill_impact: Decimal
    impact_source: str
    practice_mode_factor: Decimal
    assistance_factor: Decimal
    evaluator_factor: Decimal
    difficulty_factor: Decimal
    raw_effective_weight: Decimal
    effective_weight: Decimal
    qualifying_for_level: bool
    qualification_reason: str
    summary_code: str
    discount_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PreparedEvaluation:
    config_seed_version_id: int
    activity_id: int
    attempt_id: int
    exercise_type_version_id: int
    rubric_version_id: int
    formula: FormulaConfig
    exercise: ExerciseTypeConfig
    rubric: RubricConfig
    evaluator: str
    difficulty: str
    assistance: str
    evaluated_at: datetime
    input_artifact_ids: tuple[int, ...]
    input_observation_ids: tuple[int, ...]
    reviewed_artifact: bool
    scored_recording: bool
    scenario_key: str
    self_score: int
    dimensions: tuple[PreparedDimensionScore, ...]
    skill_events: tuple[PreparedSkillEvent, ...]
    portfolio_components: Mapping[str, Decimal] | None
    skills: Mapping[str, PersistedSkill]


class EvidenceStore(Protocol):
    async def record_atomic(
        self,
        *,
        owner_id: int,
        idempotency_key: str,
        request_hash: bytes,
        command: EvidenceEvaluationCommand,
        prepare: Callable[[EvaluationContext], PreparedEvaluation],
    ) -> RecordEvaluationResponse: ...


class EvidenceReader(Protocol):
    async def list_skills(self, *, owner_id: int) -> SkillListResponse: ...

    async def get_skill(
        self, *, owner_id: int, skill_slug: str
    ) -> SkillSummaryResponse: ...

    async def list_skill_evidence(
        self,
        *,
        owner_id: int,
        skill_slug: str,
        cursor: int | None,
        limit: int,
    ) -> EvidenceEventPage: ...

    async def list_activity_evidence(
        self,
        *,
        owner_id: int,
        activity_id: int,
        cursor: int | None,
        limit: int,
    ) -> EvidenceEventPage: ...

    async def portfolio_history(
        self,
        *,
        owner_id: int,
        cursor: int | None,
        limit: int,
    ) -> PortfolioHistoryResponse: ...


def _qualification_reason(reason: str) -> str:
    return {
        "qualifies": "qualifies",
        "nonqualifying_mode": "nonqualifying_mode",
        "nonqualifying_assistance": "assisted_during_attempt",
        "attempt_b": "attempt_b",
        "independent_requires_attempt_a": "excluded_by_formula",
    }.get(reason, "excluded_by_formula")


def _summary_code(mode: str, qualifying: bool) -> str:
    if not qualifying:
        return "excluded_evidence"
    return {
        "independent_practice": "independent_scored_evidence",
        "timed_assessment": "assessment_evidence",
        "mock_interview": "mock_evidence",
        "real_interview": "real_interview_evidence",
    }.get(mode, "preparation_evidence")


class EvidenceService:
    """Validate worker evaluations and delegate one atomic append-only write."""

    def __init__(self, store: EvidenceStore) -> None:
        self._store = store

    async def record(
        self,
        *,
        owner_id: int,
        command: EvidenceEvaluationCommand,
        idempotency_key: str,
    ) -> RecordEvaluationResponse:
        if owner_id <= 0:
            raise EvidenceInvalidRequest("owner is invalid")
        if _SAFE_IDEMPOTENCY.fullmatch(idempotency_key) is None:
            raise EvidenceInvalidRequest("Idempotency-Key is invalid")
        payload = command.model_dump(mode="json")
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        request_hash = hashlib.sha256(encoded).digest()
        return await self._store.record_atomic(
            owner_id=owner_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            command=command,
            prepare=lambda context: self.prepare_evaluation(
                context=context, command=command
            ),
        )

    @staticmethod
    def prepare_evaluation(
        *,
        context: EvaluationContext,
        command: EvidenceEvaluationCommand,
    ) -> PreparedEvaluation:
        EvidenceService._validate_lineage(context=context, command=command)
        dimensions_by_slug = {item.slug: item for item in context.dimensions}
        inputs_by_slug = {item.dimension_slug: item for item in command.dimensions}
        if set(inputs_by_slug) != set(dimensions_by_slug):
            raise EvidenceConflict("rubric dimensions do not match the immutable version")

        prepared_dimensions: list[PreparedDimensionScore] = []
        for persisted in context.dimensions:
            supplied = inputs_by_slug[persisted.slug]
            if supplied.score is not None and supplied.score > persisted.maximum:
                raise EvidenceInvalidRequest(
                    f"dimension {persisted.slug} exceeds its configured maximum"
                )
            prepared_dimensions.append(
                PreparedDimensionScore(
                    dimension_id=persisted.id,
                    dimension_slug=persisted.slug,
                    availability=supplied.availability,
                    score=supplied.score,
                    weight=(
                        persisted.weight if supplied.availability == "scored" else None
                    ),
                    artifact_ids=supplied.evidence_artifact_ids,
                    observation_ids=supplied.evidence_observation_ids,
                )
            )

        conditions = EvidenceService._conditions(context=context, command=command)
        impact_by_skill = EvidenceService._applicable_impacts(
            context=context, conditions=conditions
        )
        subset_by_skill = {
            item.skill_slug: item.dimension_slugs
            for item in command.skill_dimension_subsets
        }
        expected_skill_slugs = (
            set() if context.attempt_kind == "attempt_b" else set(impact_by_skill)
        )
        if set(subset_by_skill) != expected_skill_slugs:
            raise EvidenceConflict(
                "skill dimension subsets do not match the applicable mapped skills"
            )
        assigned_dimensions = tuple(
            slug for values in subset_by_skill.values() for slug in values
        )
        if len(assigned_dimensions) != len(set(assigned_dimensions)):
            raise EvidenceInvalidRequest(
                "each mapped skill requires its own dimension subset"
            )

        skill_events: list[PreparedSkillEvent] = []
        if context.attempt_kind != "attempt_b":
            for skill_slug, (impact, impact_source) in impact_by_skill.items():
                dimension_slugs = subset_by_skill[skill_slug]
                score_inputs: list[DimensionScoreInput] = []
                for slug in dimension_slugs:
                    score_input = inputs_by_slug.get(slug)
                    resolved_dimension = dimensions_by_slug.get(slug)
                    if (
                        score_input is None
                        or resolved_dimension is None
                        or score_input.availability != "scored"
                        or score_input.score is None
                    ):
                        raise EvidenceInvalidRequest(
                            "skill evidence may reference only scored rubric dimensions"
                        )
                    if score_input.score > Decimal("4"):
                        raise EvidenceInvalidRequest(
                            "skill evidence dimensions must remain on the 0 to 4 scale"
                        )
                    score_inputs.append(
                        DimensionScoreInput(
                            slug,
                            score_input.score,
                            resolved_dimension.weight,
                        )
                    )
                performance = calculate_performance_score(tuple(score_inputs))
                weight = calculate_effective_weight(
                    skill_impact=impact,
                    practice_mode=command.practice_mode,
                    assistance=command.assistance,
                    evaluator=command.evaluator,
                    difficulty=command.difficulty,
                    formula=context.formula,
                )
                qualification = qualify_evidence(
                    EvidenceCandidate(
                        event_id=f"pending:{skill_slug}",
                        rubric_scored=True,
                        practice_mode=command.practice_mode,
                        assistance=command.assistance,
                        evaluator=command.evaluator,
                        attempt_kind=context.attempt_kind,
                        exercise_type=command.exercise_type,
                        mapping_version=command.mapping_version,
                        scenario_key=hashlib.sha256(context.prompt.encode()).hexdigest(),
                        occurred_at=command.evaluated_at,
                        ai_role=command.ai_role,
                        required_precommit_field=context.exercise.required_precommit_field,
                        selected_competency=context.selected_competency,
                        allowed_selected_competencies=frozenset(
                            context.exercise.allowed_selected_competencies
                        ),
                        selector_committed_before_attempt=(
                            context.selector_committed_in_attempt
                        ),
                    ),
                    formula=context.formula,
                )
                reason = _qualification_reason(qualification.reason)
                skill = context.skills[skill_slug]
                skill_events.append(
                    PreparedSkillEvent(
                        skill_id=skill.id,
                        skill_slug=skill_slug,
                        dimension_slugs=dimension_slugs,
                        performance_score=performance.score,
                        raw_score_numerator=performance.weighted_sum,
                        raw_score_denominator=performance.weight_sum,
                        skill_impact=impact,
                        impact_source=impact_source,
                        practice_mode_factor=weight.factors.practice_mode,
                        assistance_factor=weight.factors.assistance,
                        evaluator_factor=weight.factors.evaluator,
                        difficulty_factor=weight.factors.difficulty,
                        raw_effective_weight=weight.raw_weight,
                        effective_weight=weight.effective_weight,
                        qualifying_for_level=qualification.qualifying_for_level,
                        qualification_reason=reason,
                        summary_code=_summary_code(
                            command.practice_mode,
                            qualification.qualifying_for_level,
                        ),
                        discount_codes=("outlier_cap",) if weight.capped else (),
                    )
                )

        portfolio_components: Mapping[str, Decimal] | None = None
        if (
            context.attempt_kind != "attempt_b"
            and "portfolio_judgment" in context.exercise.composite_metric_weights
        ):
            values: dict[str, Decimal] = {}
            for dimension in prepared_dimensions:
                if dimension.score is None:
                    raise EvidenceInvalidRequest(
                        "Portfolio Judgment requires every component score"
                    )
                values[dimension.dimension_slug] = dimension.score
            portfolio_components = values

        scenario_key = hashlib.sha256(context.prompt.encode()).hexdigest()
        referenced_artifacts = set(command.artifact_ids)
        dimension_artifacts = {
            item for value in prepared_dimensions for item in value.artifact_ids
        }
        return PreparedEvaluation(
            config_seed_version_id=context.config_seed_version_id,
            activity_id=context.activity_id,
            attempt_id=context.attempt_id,
            exercise_type_version_id=context.exercise_type_version_id,
            rubric_version_id=context.rubric_version_id,
            formula=context.formula,
            exercise=context.exercise,
            rubric=context.rubric,
            evaluator=command.evaluator,
            difficulty=command.difficulty,
            assistance=command.assistance,
            evaluated_at=command.evaluated_at,
            input_artifact_ids=command.artifact_ids,
            input_observation_ids=command.observation_ids,
            reviewed_artifact=bool(referenced_artifacts | dimension_artifacts),
            scored_recording=command.scored_recording,
            scenario_key=scenario_key,
            self_score=context.self_score,
            dimensions=tuple(prepared_dimensions),
            skill_events=tuple(skill_events),
            portfolio_components=portfolio_components,
            skills=context.skills,
        )

    @staticmethod
    def _validate_lineage(
        *, context: EvaluationContext, command: EvidenceEvaluationCommand
    ) -> None:
        if command.activity_id != context.activity_id or command.attempt_id != context.attempt_id:
            raise EvidenceConflict("committed attempt lineage does not match")
        if command.config_version_key != context.config_version_key:
            raise EvidenceConflict("configuration version does not match")
        if command.formula_version != context.formula.version:
            raise EvidenceConflict("formula version does not match immutable configuration")
        if (
            command.exercise_type != context.exercise.slug
            or command.mapping_version != context.exercise.mapping_version
        ):
            raise EvidenceConflict("exercise mapping version does not match")
        if (
            command.rubric_slug != context.rubric.slug
            or command.rubric_version != context.rubric.version
        ):
            raise EvidenceConflict("rubric version does not match immutable configuration")
        if command.practice_mode != context.exercise.evidence_mode:
            raise EvidenceConflict("practice mode does not match the exercise mapping")
        if command.evaluated_at < max(
            context.attempt_committed_at, context.self_review_submitted_at
        ):
            raise EvidenceConflict("evaluation predates committed learner evidence")
        linked_ids = set(context.linked_artifact_classes)
        if not set(command.artifact_ids).issubset(linked_ids):
            raise EvidenceConflict("evaluation artifact is not linked to the attempt")
        dimension_artifact_ids = {
            artifact_id
            for dimension in command.dimensions
            for artifact_id in dimension.evidence_artifact_ids
        }
        if not dimension_artifact_ids.issubset(set(command.artifact_ids)):
            raise EvidenceConflict("dimension artifact is absent from the input manifest")
        classes = {
            context.linked_artifact_classes[item] for item in command.artifact_ids
        }
        if command.transcript_available and "transcript" not in classes:
            raise EvidenceConflict("transcript availability lacks immutable evidence")
        if command.audio_available and "original_audio" not in classes:
            raise EvidenceConflict("audio availability lacks immutable evidence")
        if command.scored_recording and not any(
            context.linked_artifact_classes[item] == "original_audio"
            for item in dimension_artifact_ids
        ):
            raise EvidenceConflict("scored recording lacks dimension-level audio evidence")
        if command.written_english_available and not context.written_output_available:
            raise EvidenceConflict("written English availability lacks committed output")
        if context.attempt_assistance_mode == "hint_ladder":
            if command.assistance != "ai_hints_during_attempt":
                raise EvidenceConflict("assistance does not match the committed attempt")
        elif command.assistance in {
            "ai_hints_during_attempt",
            "ai_co_created",
            "ai_generated",
        }:
            raise EvidenceConflict("assistance does not match the committed attempt")
        if (
            command.evaluator == "ai_rubric_reviewer"
            and command.assistance == "no_ai"
        ):
            raise EvidenceConflict("AI review must be recorded after commitment")

    @staticmethod
    def _conditions(
        *, context: EvaluationContext, command: EvidenceEvaluationCommand
    ) -> frozenset[str]:
        conditions: set[str] = set()
        if command.transcript_available or command.written_english_available:
            conditions.add("spoken_or_written_english")
        if command.audio_available and command.transcript_available:
            conditions.add("explained_aloud_in_english")
        if context.selector_committed_in_attempt:
            conditions.add("reviewed_dynamic_impact")
        return frozenset(conditions)

    @staticmethod
    def _applicable_impacts(
        *, context: EvaluationContext, conditions: frozenset[str]
    ) -> dict[str, tuple[Decimal, str]]:
        exercise = context.exercise
        if exercise.required_precommit_field is not None:
            if (
                not context.selector_committed_in_attempt
                or context.selector_field != exercise.required_precommit_field
                or context.selected_competency is None
                or context.selected_competency
                not in exercise.allowed_selected_competencies
            ):
                raise EvidenceConflict("required precommit selector is missing or invalid")
        impacts: dict[str, tuple[Decimal, str]] = {}
        for impact in exercise.impacts:
            resolved = resolve_skill_impact(
                exercise=exercise,
                skill_slug=impact.skill_slug,
                conditions_met=conditions,
                selected_competency=context.selected_competency,
                selector_committed_before_attempt=context.selector_committed_in_attempt,
            )
            if resolved.weight > 0:
                impacts[impact.skill_slug] = (resolved.weight, resolved.source)
        if context.selected_competency is not None:
            resolved = resolve_skill_impact(
                exercise=exercise,
                skill_slug=context.selected_competency,
                conditions_met=conditions,
                selected_competency=context.selected_competency,
                selector_committed_before_attempt=context.selector_committed_in_attempt,
            )
            if resolved.weight > 0:
                impacts[context.selected_competency] = (
                    resolved.weight,
                    resolved.source,
                )
        missing = set(impacts) - set(context.skills)
        if missing:
            raise EvidenceConflict("mapped skill is absent from immutable configuration")
        return impacts


class EvidenceQueryService:
    """Owner-scoped read facade with bounded pagination."""

    def __init__(self, reader: EvidenceReader) -> None:
        self._reader = reader

    @staticmethod
    def _page(cursor: int | None, limit: int) -> None:
        if cursor is not None and cursor <= 0:
            raise EvidenceInvalidRequest("cursor is invalid")
        if not 1 <= limit <= 100:
            raise EvidenceInvalidRequest("page limit is invalid")

    async def list_skills(self, *, owner_id: int) -> SkillListResponse:
        return await self._reader.list_skills(owner_id=owner_id)

    async def get_skill(
        self, *, owner_id: int, skill_slug: str
    ) -> SkillSummaryResponse:
        if not skill_slug.strip():
            raise EvidenceInvalidRequest("skill slug is invalid")
        return await self._reader.get_skill(owner_id=owner_id, skill_slug=skill_slug)

    async def list_skill_evidence(
        self,
        *,
        owner_id: int,
        skill_slug: str,
        cursor: int | None,
        limit: int,
    ) -> EvidenceEventPage:
        self._page(cursor, limit)
        return await self._reader.list_skill_evidence(
            owner_id=owner_id,
            skill_slug=skill_slug,
            cursor=cursor,
            limit=limit,
        )

    async def list_activity_evidence(
        self,
        *,
        owner_id: int,
        activity_id: int,
        cursor: int | None,
        limit: int,
    ) -> EvidenceEventPage:
        self._page(cursor, limit)
        if activity_id <= 0:
            raise EvidenceInvalidRequest("activity ID is invalid")
        return await self._reader.list_activity_evidence(
            owner_id=owner_id,
            activity_id=activity_id,
            cursor=cursor,
            limit=limit,
        )

    async def portfolio_history(
        self,
        *,
        owner_id: int,
        cursor: int | None,
        limit: int,
    ) -> PortfolioHistoryResponse:
        self._page(cursor, limit)
        return await self._reader.portfolio_history(
            owner_id=owner_id,
            cursor=cursor,
            limit=limit,
        )

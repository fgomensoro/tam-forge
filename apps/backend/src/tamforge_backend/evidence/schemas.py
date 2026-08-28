"""Strict write and read contracts for the inspectable evidence ledger."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Slug = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
VersionKey = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")]
PositiveId = Annotated[int, Field(gt=0)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DimensionEvaluationInput(StrictModel):
    dimension_slug: Slug
    availability: Literal["scored", "not_applicable", "unavailable"]
    score: Annotated[Decimal | None, Field(ge=0, le=20, decimal_places=3)] = None
    evidence_artifact_ids: Annotated[tuple[PositiveId, ...], Field(max_length=64)] = ()
    evidence_observation_ids: Annotated[tuple[PositiveId, ...], Field(max_length=64)] = ()

    @model_validator(mode="after")
    def validate_score_availability(self) -> DimensionEvaluationInput:
        if (self.availability == "scored") != (self.score is not None):
            raise ValueError("scored availability requires exactly one score")
        for values in (self.evidence_artifact_ids, self.evidence_observation_ids):
            if len(values) != len(set(values)):
                raise ValueError("evidence references must be unique")
        return self


class SkillDimensionSubsetInput(StrictModel):
    skill_slug: Slug
    dimension_slugs: Annotated[tuple[Slug, ...], Field(min_length=1, max_length=64)]

    @field_validator("dimension_slugs")
    @classmethod
    def unique_dimensions(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("skill dimension slugs must be unique")
        return value


class EvidenceEvaluationCommand(StrictModel):
    activity_id: PositiveId
    attempt_id: PositiveId
    config_version_key: VersionKey
    exercise_type: Slug
    mapping_version: VersionKey
    formula_version: VersionKey
    rubric_slug: Slug
    rubric_version: VersionKey
    practice_mode: Literal[
        "exposure_only",
        "guided_practice",
        "independent_practice",
        "timed_assessment",
        "mock_interview",
        "real_interview",
        "pipeline_only",
    ]
    assistance: Literal[
        "no_ai",
        "ai_after_committed_attempt",
        "ai_hints_during_attempt",
        "ai_co_created",
        "ai_generated",
    ]
    evaluator: Literal[
        "self",
        "ai_rubric_reviewer",
        "peer",
        "human_coach",
        "explicit_interviewer_feedback",
    ]
    difficulty: Literal["introductory", "standard", "advanced"]
    ai_role: Literal[
        "none", "planner", "tutor", "coach", "interviewer", "reviewer", "analyst"
    ]
    evaluated_at: datetime
    artifact_ids: Annotated[tuple[PositiveId, ...], Field(max_length=64)] = ()
    observation_ids: Annotated[tuple[PositiveId, ...], Field(max_length=64)] = ()
    transcript_available: bool
    audio_available: bool
    written_english_available: bool
    scored_recording: bool
    dimensions: Annotated[
        tuple[DimensionEvaluationInput, ...], Field(min_length=1, max_length=64)
    ]
    skill_dimension_subsets: Annotated[
        tuple[SkillDimensionSubsetInput, ...], Field(max_length=32)
    ] = ()

    @model_validator(mode="after")
    def validate_unique_inputs(self) -> EvidenceEvaluationCommand:
        if self.evaluated_at.tzinfo is None or self.evaluated_at.utcoffset() is None:
            raise ValueError("evaluated_at must be timezone-aware")
        for values in (self.artifact_ids, self.observation_ids):
            if len(values) != len(set(values)):
                raise ValueError("evaluation references must be unique")
        dimension_slugs = tuple(item.dimension_slug for item in self.dimensions)
        skill_slugs = tuple(item.skill_slug for item in self.skill_dimension_subsets)
        if len(dimension_slugs) != len(set(dimension_slugs)):
            raise ValueError("evaluation dimensions must be unique")
        if len(skill_slugs) != len(set(skill_slugs)):
            raise ValueError("skill subsets must be unique")
        if self.scored_recording and not self.audio_available:
            raise ValueError("a scored recording requires audio availability")
        return self


class RecordEvaluationResponse(StrictModel):
    evaluation_id: PositiveId
    activity_id: PositiveId
    attempt_id: PositiveId
    evidence_event_ids: tuple[PositiveId, ...]
    snapshot_ids: tuple[PositiveId, ...]
    portfolio_score_id: PositiveId | None
    replayed: bool


class SnapshotManifestItem(StrictModel):
    event_id: PositiveId
    effective_weight: Decimal
    inclusion_code: Literal[
        "included",
        "discounted_same_day",
        "excluded_nonqualifying",
        "excluded_outside_window",
    ]


class SkillSnapshotResponse(StrictModel):
    id: PositiveId
    formula_version: str
    snapshot_date: date
    estimated_level: Decimal
    confidence: str
    trend: str
    recency: str
    baseline_target_gap: Decimal
    month_one_target_gap: Decimal
    final_target_gap: Decimal
    total_effective_weight: Decimal
    qualifying_event_count: int
    exercise_type_count: int
    last_strong_evidence_date: date | None
    manifest: tuple[SnapshotManifestItem, ...]
    confidence_basis: dict[str, object]
    trend_basis: dict[str, object]


class SkillSummaryResponse(StrictModel):
    slug: str
    name: str
    baseline: Decimal
    month_one_target: Decimal
    final_target: Decimal
    latest_snapshot: SkillSnapshotResponse | None


class SkillListResponse(StrictModel):
    items: tuple[SkillSummaryResponse, ...]


class EvidenceEventResponse(StrictModel):
    id: PositiveId
    activity_id: PositiveId
    attempt_id: PositiveId | None
    skill_slug: str
    exercise_type: str
    mapping_version: str
    formula_version: str
    rubric_slug: str
    rubric_version: str
    evaluator: str
    practice_mode: str
    assistance: str
    difficulty: str
    performance_score: Decimal
    skill_impact: Decimal
    effective_weight: Decimal
    qualifying_for_level: bool
    qualification_reason: str
    raw_dimension_scores: dict[str, object]
    occurred_at: datetime


class EvidenceEventPage(StrictModel):
    items: tuple[EvidenceEventResponse, ...]
    next_cursor: PositiveId | None


class PortfolioComponentResponse(StrictModel):
    slug: str
    score: Decimal


class PortfolioScoreResponse(StrictModel):
    id: PositiveId
    activity_id: PositiveId
    attempt_id: PositiveId
    formula_version: str
    rubric_version: str
    total_score: Decimal
    components: tuple[PortfolioComponentResponse, ...]
    trend_basis: dict[str, object]
    scored_at: datetime


class PortfolioHistoryResponse(StrictModel):
    items: tuple[PortfolioScoreResponse, ...]
    next_cursor: PositiveId | None

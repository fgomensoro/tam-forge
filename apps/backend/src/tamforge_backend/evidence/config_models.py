"""Strict immutable models for checked-in scoring configuration."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from types import MappingProxyType
from typing import Annotated, Any, Literal, cast

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

Slug = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
VersionKey = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")]
Score = Annotated[Decimal, Field(ge=0, le=4, max_digits=4, decimal_places=3)]
Weight = Annotated[Decimal, Field(gt=0, le=1, max_digits=7, decimal_places=6)]
Factor = Annotated[Decimal, Field(ge=0, le=1.15, max_digits=7, decimal_places=6)]


def _bounded_text(value: str, *, maximum_bytes: int) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    if len(value.encode("utf-8")) > maximum_bytes:
        raise ValueError(f"must not exceed {maximum_bytes} UTF-8 bytes")
    return value


Text128 = Annotated[str, AfterValidator(lambda value: _bounded_text(value, maximum_bytes=128))]
Text512 = Annotated[str, AfterValidator(lambda value: _bounded_text(value, maximum_bytes=512))]
Text1024 = Annotated[
    str, AfterValidator(lambda value: _bounded_text(value, maximum_bytes=1024))
]
Text2048 = Annotated[
    str, AfterValidator(lambda value: _bounded_text(value, maximum_bytes=2048))
]
Text4096 = Annotated[
    str, AfterValidator(lambda value: _bounded_text(value, maximum_bytes=4096))
]

EvidenceMode = Literal[
    "exposure_only",
    "guided_practice",
    "independent_practice",
    "timed_assessment",
    "mock_interview",
    "real_interview",
    "pipeline_only",
]
ConditionCode = Literal[
    "always",
    "spoken_or_written_english",
    "explained_aloud_in_english",
    "reviewed_dynamic_impact",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SkillConfig(StrictModel):
    slug: Slug
    name: Text128
    baseline: Score
    month_one_target: Score
    final_target: Score


class SkillsFile(StrictModel):
    schema_version: Annotated[int, Field(gt=0)]
    config_version: VersionKey
    skills: tuple[SkillConfig, ...]


class SkillImpactConfig(StrictModel):
    skill_slug: Slug
    weight: Weight
    condition: ConditionCode = "always"


class ChildExerciseRef(StrictModel):
    exercise_type: Slug
    mapping_version: VersionKey


class CompositeMetricConfig(StrictModel):
    metric_slug: Slug
    weight: Weight


class ExerciseTypeConfig(StrictModel):
    slug: Slug
    mapping_version: VersionKey
    evidence_mode: EvidenceMode
    impacts: tuple[SkillImpactConfig, ...] = Field(alias="skill_impacts")
    tags: tuple[Slug, ...] = ()
    condition_note: Text512 | None = None
    required_precommit_field: Literal[
        "domain_competency_slug", "story_competency_slug"
    ] | None = None
    allowed_domain_competencies: tuple[Slug, ...] = ()
    allowed_story_competencies: tuple[Slug, ...] = ()
    selected_impact: Weight | None = None
    composite_metrics: tuple[CompositeMetricConfig, ...] = ()
    component_scoring_required: bool = False
    child_exercise_type_refs: tuple[ChildExerciseRef, ...] = ()

    @field_validator("impacts", mode="before")
    @classmethod
    def convert_impact_mapping(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        return tuple(
            ({"skill_slug": slug, **details} if isinstance(details, dict) else {
                "skill_slug": slug,
                "weight": details,
            })
            for slug, details in value.items()
        )

    @field_validator("composite_metrics", mode="before")
    @classmethod
    def convert_composite_mapping(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        return tuple(
            {"metric_slug": slug, "weight": weight} for slug, weight in value.items()
        )

    @model_validator(mode="after")
    def validate_selector_shape(self) -> ExerciseTypeConfig:
        selector_values = (
            self.required_precommit_field,
            bool(self.allowed_selected_competencies),
            self.selected_impact,
        )
        if any(value not in (None, False) for value in selector_values) and not all(
            value not in (None, False) for value in selector_values
        ):
            raise ValueError("dynamic selector requires field, allowlist, and selected impact")
        if self.allowed_domain_competencies and self.allowed_story_competencies:
            raise ValueError("dynamic selector must use exactly one allowlist")
        if self.required_precommit_field == "domain_competency_slug" and not (
            self.allowed_domain_competencies
        ):
            raise ValueError("domain selector requires domain competency allowlist")
        if self.required_precommit_field == "story_competency_slug" and not (
            self.allowed_story_competencies
        ):
            raise ValueError("story selector requires story competency allowlist")
        if self.component_scoring_required != bool(self.child_exercise_type_refs):
            raise ValueError("component scoring and child exercise references must agree")
        return self

    @property
    def skill_impacts(self) -> Mapping[str, SkillImpactConfig]:
        return MappingProxyType({impact.skill_slug: impact for impact in self.impacts})

    @property
    def allowed_selected_competencies(self) -> tuple[str, ...]:
        return self.allowed_domain_competencies or self.allowed_story_competencies

    @property
    def composite_metric_weights(self) -> Mapping[str, Decimal]:
        return MappingProxyType(
            {metric.metric_slug: metric.weight for metric in self.composite_metrics}
        )


class ExerciseTypesFile(StrictModel):
    schema_version: Annotated[int, Field(gt=0)]
    mapping_version: VersionKey
    supporting_tags: frozenset[Slug]
    exercise_types: tuple[ExerciseTypeConfig, ...]

    @model_validator(mode="before")
    @classmethod
    def inherit_mapping_version(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        mapping_version = value.get("mapping_version")
        exercises = value.get("exercise_types")
        if isinstance(exercises, list):
            for exercise in exercises:
                if isinstance(exercise, dict):
                    exercise.setdefault("mapping_version", mapping_version)
        return value


class PracticeModeFactors(StrictModel):
    exposure_only: Factor
    guided_practice: Factor
    independent_practice: Factor
    timed_assessment: Factor
    mock_interview: Factor
    real_interview: Factor


class AssistanceFactors(StrictModel):
    no_ai: Factor
    ai_after_committed_attempt: Factor
    ai_hints_during_attempt: Factor
    ai_co_created: Factor
    ai_generated: Factor


class EvaluatorFactors(StrictModel):
    self: Factor
    ai_rubric_reviewer: Factor
    peer: Factor
    human_coach: Factor
    explicit_interviewer_feedback: Factor


class DifficultyFactors(StrictModel):
    introductory: Factor
    standard: Factor
    advanced: Factor


class ConfidenceRules(StrictModel):
    high_minimum_effective_weight: Decimal
    high_minimum_exercise_types: Annotated[int, Field(gt=0)]
    high_recent_assessment_days: Annotated[int, Field(gt=0)]
    high_requires_reviewed_artifact_or_recording: bool
    medium_minimum_effective_weight: Decimal
    medium_minimum_exercise_types: Annotated[int, Field(gt=0)]
    medium_requires_independent_attempt: bool


class RecencyRules(StrictModel):
    fresh_max_days: Annotated[int, Field(ge=0)]
    aging_max_days: Annotated[int, Field(gt=0)]


class FormulaConfig(StrictModel):
    version: VersionKey
    prior_weight: Annotated[Decimal, Field(gt=0)]
    latest_qualifying_events: Annotated[int, Field(gt=0)]
    full_weight_same_day_limit: Annotated[int, Field(gt=0)]
    performance_scale_min: Decimal
    performance_scale_max: Decimal
    practice_mode_factors: PracticeModeFactors
    assistance_factors: AssistanceFactors
    evaluator_factors: EvaluatorFactors
    difficulty_factors: DifficultyFactors
    qualifying_modes: frozenset[EvidenceMode]
    qualifying_assistance: frozenset[
        Literal["no_ai", "ai_after_committed_attempt"]
    ]
    requires_rubric_score: bool
    independent_practice_requires_attempt_a: bool
    attempt_b_qualifies: bool
    confidence: ConfidenceRules
    recency: RecencyRules

    @model_validator(mode="after")
    def validate_scale(self) -> FormulaConfig:
        if self.performance_scale_min < 0 or self.performance_scale_max > 4:
            raise ValueError("performance scale must remain within 0 and 4")
        if self.performance_scale_max <= self.performance_scale_min:
            raise ValueError("performance scale maximum must be greater than minimum")
        return self


class RubricDimensionConfig(StrictModel):
    slug: Slug
    name: Text128
    maximum: Annotated[Decimal, Field(gt=0, le=20)]
    weight: Weight
    availability_rule: Literal[
        "always", "monologue_not_applicable", "requires_audio", "requires_interaction"
    ] = "always"


class RubricConfig(StrictModel):
    slug: Slug
    version: VersionKey
    name: Text128
    scope: Literal["tam", "english", "portfolio", "exercise"]
    scale_min: Decimal
    scale_max: Decimal
    dimensions: tuple[RubricDimensionConfig, ...]

    @model_validator(mode="after")
    def validate_scale(self) -> RubricConfig:
        if self.scale_min < 0 or self.scale_max > 20:
            raise ValueError("rubric scale must remain within 0 and 20")
        if self.scale_max <= self.scale_min:
            raise ValueError("scale maximum must be greater than minimum")
        return self


class RubricsFile(StrictModel):
    schema_version: Annotated[int, Field(gt=0)]
    config_version: VersionKey
    formula: FormulaConfig
    rubrics: tuple[RubricConfig, ...]


class RoadmapTaskConfig(StrictModel):
    stable_id: Annotated[str, Field(pattern=r"^m1-w[1-4]-d[0-9]{2}-[a-z0-9-]+$")]
    month: Literal[1]
    week: Annotated[int, Field(ge=1, le=4)]
    day: Annotated[int, Field(ge=1, le=24)]
    block: Literal[
        "sql",
        "technical_learning",
        "career_pipeline",
        "correction_warmup",
        "tam_case",
        "communication_spoken",
        "daily_close",
        "saturday_assessment",
    ]
    order: Annotated[int, Field(gt=0)]
    source_path: Text2048
    source_heading: Text512
    exercise_type: Slug
    mapping_version: VersionKey
    required: bool
    timebox_minutes: Annotated[int, Field(gt=0, le=255)]
    objective: Text4096
    required_output: Annotated[
        tuple[Text1024, ...], Field(min_length=1)
    ]
    pass_criteria: Annotated[
        tuple[Text1024, ...], Field(min_length=1)
    ]
    evidence_requirements: Annotated[
        tuple[Text1024, ...], Field(min_length=1)
    ]
    procedure: Annotated[tuple[TaskContractStepConfig, ...], Field(min_length=1)]
    constraints: Annotated[tuple[Text1024, ...], Field(min_length=1)]
    correction_selection: CorrectionSelectionConfig | None = None
    allowed_ai_role: Literal[
        "none", "planner", "tutor", "coach", "interviewer", "reviewer", "analyst"
    ]

    @model_validator(mode="after")
    def validate_correction_shape(self) -> RoadmapTaskConfig:
        if (self.block == "correction_warmup") != (self.correction_selection is not None):
            raise ValueError(
                "correction selection is required only for correction warm-up tasks"
            )
        return self


class TaskContractStepConfig(StrictModel):
    phase: Slug
    minutes: Annotated[int, Field(gt=0, le=255)] | None = None
    requirement: Text1024


class CorrectionSelectionConfig(StrictModel):
    source: Literal["due_corrections"]
    maximum_items: Literal[1]
    allowed_kinds: frozenset[
        Literal["spoken_attempt_b", "written_attempt_b", "targeted_sql_correction"]
    ]
    inherits_core_prompt: bool
    no_attempt_c: bool
    skill_level_effect: Literal["none"]


class TaskContractConfig(StrictModel):
    required_output: Annotated[
        tuple[Text1024, ...], Field(min_length=1)
    ]
    pass_criteria: Annotated[
        tuple[Text1024, ...], Field(min_length=1)
    ]
    evidence_requirements: Annotated[
        tuple[Text1024, ...], Field(min_length=1)
    ]
    procedure: Annotated[tuple[TaskContractStepConfig, ...], Field(min_length=1)]
    constraints: Annotated[tuple[Text1024, ...], Field(min_length=1)]
    correction_selection: CorrectionSelectionConfig | None = None


class RoadmapReconciliationConfig(StrictModel):
    slug: Slug
    reviewed: Literal[True]
    target_task_id: Annotated[
        str, Field(pattern=r"^m1-w[1-4]-d[0-9]{2}-[a-z0-9-]+$")
    ]
    source_path: Text2048
    source_heading: Text512
    original_source_text: Text1024
    executable_text: Text1024
    what_changed: Text1024
    why_changed: Text1024
    evidence: Text1024
    roadmap_objective: Text1024
    affects_time: bool
    affects_required_coverage: bool


class RoadmapTaskMapFile(StrictModel):
    schema_version: Annotated[int, Field(gt=0)]
    roadmap_version: VersionKey
    mapping_version: VersionKey
    month: Literal[1]
    default_required: bool
    contracts: dict[Slug, TaskContractConfig]
    reconciliations: tuple[RoadmapReconciliationConfig, ...] = ()
    tasks: tuple[RoadmapTaskConfig, ...]

    @model_validator(mode="before")
    @classmethod
    def inherit_mapping_version(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        mapping_version = value.get("mapping_version")
        contracts = value.get("contracts")
        month = value.get("month")
        required = value.get("default_required")
        days = value.pop("days", None)
        tasks = value.get("tasks")
        if isinstance(days, list):
            tasks = []
            for day in days:
                if not isinstance(day, dict):
                    raise ValueError("each roadmap day must be a mapping")
                allowed_day_fields = {
                    "week",
                    "day",
                    "source_path",
                    "source_heading",
                    "tasks",
                }
                unexpected = set(day) - allowed_day_fields
                if unexpected:
                    field_name = sorted(unexpected)[0]
                    raise ValueError(
                        f"roadmap day field {field_name!r} is not permitted"
                    )
                day_tasks = day.get("tasks")
                if not isinstance(day_tasks, list):
                    raise ValueError("each roadmap day must contain a task list")
                for task in day_tasks:
                    if not isinstance(task, dict):
                        raise ValueError("each roadmap task must be a mapping")
                    for key in ("week", "day", "source_path", "source_heading"):
                        task.setdefault(key, day.get(key))
                    tasks.append(task)
            value["tasks"] = tasks
        if isinstance(tasks, list):
            for task in tasks:
                if isinstance(task, dict):
                    task.setdefault("month", month)
                    task.setdefault("required", required)
                    task.setdefault("mapping_version", mapping_version)
                    contract_key = task.pop("contract", None)
                    if contract_key is not None:
                        if not isinstance(contract_key, str):
                            raise ValueError("task contract reference must be a string")
                        if not isinstance(contracts, dict) or contract_key not in contracts:
                            raise ValueError(f"unknown task contract {contract_key!r}")
                        contract = contracts[contract_key]
                        if not isinstance(contract, dict):
                            raise ValueError(f"task contract {contract_key!r} must be a mapping")
                        for key, item in contract.items():
                            task.setdefault(key, item)
        return value


class CanonicalConfigPayload(StrictModel):
    skills: SkillsFile
    exercise_types: ExerciseTypesFile
    rubrics: RubricsFile
    roadmap_tasks: RoadmapTaskMapFile


@dataclass(frozen=True, slots=True)
class ConfigBundle:
    schema_version: int
    config_version: str
    skills: tuple[SkillConfig, ...]
    exercise_types: tuple[ExerciseTypeConfig, ...]
    formula: FormulaConfig
    rubrics: tuple[RubricConfig, ...]
    roadmap_version: str
    roadmap_contracts: Mapping[str, TaskContractConfig]
    reconciliations: tuple[RoadmapReconciliationConfig, ...]
    roadmap_tasks: tuple[RoadmapTaskConfig, ...]
    content_hash: bytes
    version_key: str
    _skills_by_slug: Mapping[str, SkillConfig] = field(repr=False)
    _exercises_by_slug: Mapping[str, ExerciseTypeConfig] = field(repr=False)
    _rubrics_by_slug: Mapping[str, RubricConfig] = field(repr=False)
    _canonical_payload_json: str = field(repr=False)

    def skill(self, slug: str) -> SkillConfig:
        return self._skills_by_slug[slug]

    def exercise(self, slug: str) -> ExerciseTypeConfig:
        return self._exercises_by_slug[slug]

    def rubric(self, slug: str) -> RubricConfig:
        return self._rubrics_by_slug[slug]

    @property
    def portfolio(self) -> RubricConfig:
        return self.rubric("portfolio_judgment")

    @property
    def canonical_payload(self) -> dict[str, Any]:
        """Return a detached reconstructable copy of the canonical seed payload."""
        return cast(dict[str, Any], json.loads(self._canonical_payload_json))


def immutable_index(items: tuple[Any, ...], attribute: str) -> Mapping[str, Any]:
    return MappingProxyType({str(getattr(item, attribute)): item for item in items})

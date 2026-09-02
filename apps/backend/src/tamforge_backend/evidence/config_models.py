"""Strict immutable models for checked-in scoring configuration."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
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
EffectiveWeight = Annotated[Decimal, Field(ge=0, le=1000, max_digits=10, decimal_places=6)]
PriorWeight = Annotated[Decimal, Field(gt=0, le=1000, max_digits=10, decimal_places=6)]
DiscountFactor = Annotated[Decimal, Field(gt=0, lt=1, max_digits=7, decimal_places=6)]
MaximumEventWeight = Annotated[Decimal, Field(gt=0, le=1.15, max_digits=7, decimal_places=6)]


def _bounded_text(value: str, *, maximum_bytes: int) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    if len(value.encode("utf-8")) > maximum_bytes:
        raise ValueError(f"must not exceed {maximum_bytes} UTF-8 bytes")
    return value


Text128 = Annotated[str, AfterValidator(lambda value: _bounded_text(value, maximum_bytes=128))]
Text512 = Annotated[str, AfterValidator(lambda value: _bounded_text(value, maximum_bytes=512))]
Text1024 = Annotated[str, AfterValidator(lambda value: _bounded_text(value, maximum_bytes=1024))]
Text2048 = Annotated[str, AfterValidator(lambda value: _bounded_text(value, maximum_bytes=2048))]
Text4096 = Annotated[str, AfterValidator(lambda value: _bounded_text(value, maximum_bytes=4096))]

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
    required_precommit_field: Literal["domain_competency_slug", "story_competency_slug"] | None = (
        None
    )
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
            (
                {"skill_slug": slug, **details}
                if isinstance(details, dict)
                else {
                    "skill_slug": slug,
                    "weight": details,
                }
            )
            for slug, details in value.items()
        )

    @field_validator("composite_metrics", mode="before")
    @classmethod
    def convert_composite_mapping(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        return tuple({"metric_slug": slug, "weight": weight} for slug, weight in value.items())

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
    high_minimum_effective_weight: EffectiveWeight
    high_minimum_exercise_types: Annotated[int, Field(gt=0, le=1000)]
    high_recent_assessment_days: Annotated[int, Field(gt=0, le=3650)]
    high_requires_reviewed_artifact_or_recording: bool
    medium_minimum_effective_weight: EffectiveWeight
    medium_minimum_exercise_types: Annotated[int, Field(gt=0, le=1000)]
    medium_requires_independent_attempt: bool

    @model_validator(mode="after")
    def validate_threshold_order(self) -> ConfidenceRules:
        if self.high_minimum_effective_weight < self.medium_minimum_effective_weight:
            raise ValueError("high confidence threshold must be at least medium")
        if self.high_minimum_exercise_types < self.medium_minimum_exercise_types:
            raise ValueError("high confidence exercise count must be at least medium")
        return self


class RecencyRules(StrictModel):
    fresh_max_days: Annotated[int, Field(ge=0, le=3650)]
    aging_max_days: Annotated[int, Field(gt=0, le=3650)]

    @model_validator(mode="after")
    def validate_window_order(self) -> RecencyRules:
        if self.fresh_max_days > self.aging_max_days:
            raise ValueError("fresh recency must not exceed aging recency")
        return self


class TrendRules(StrictModel):
    recent_event_count: Annotated[int, Field(gt=0, le=1000)]
    preceding_event_count: Annotated[int, Field(gt=0, le=1000)]
    minimum_delta: Annotated[Decimal, Field(gt=0, le=4, decimal_places=3)]


class FormulaConfig(StrictModel):
    version: VersionKey
    prior_weight: PriorWeight
    latest_qualifying_events: Annotated[int, Field(gt=0, le=1000)]
    full_weight_same_day_limit: Annotated[int, Field(gt=0, le=1000)]
    same_day_repetition_factor: DiscountFactor
    maximum_effective_weight_per_event: MaximumEventWeight
    performance_scale_min: Decimal
    performance_scale_max: Decimal
    practice_mode_factors: PracticeModeFactors
    assistance_factors: AssistanceFactors
    evaluator_factors: EvaluatorFactors
    difficulty_factors: DifficultyFactors
    qualifying_modes: frozenset[EvidenceMode]
    qualifying_assistance: frozenset[
        Literal[
            "no_ai",
            "ai_after_committed_attempt",
            "ai_hints_during_attempt",
            "ai_co_created",
            "ai_generated",
        ]
    ]
    requires_rubric_score: Literal[True]
    independent_practice_requires_attempt_a: Literal[True]
    attempt_b_qualifies: Literal[False]
    confidence: ConfidenceRules
    trend: TrendRules
    recency: RecencyRules

    @model_validator(mode="after")
    def validate_scale(self) -> FormulaConfig:
        expected_modes = {
            "independent_practice",
            "timed_assessment",
            "mock_interview",
            "real_interview",
        }
        if self.qualifying_modes != expected_modes:
            raise ValueError("qualifying modes are fixed by the scoring contract")
        expected_assistance = {"no_ai", "ai_after_committed_attempt"}
        if self.qualifying_assistance != expected_assistance:
            raise ValueError("qualifying assistance is fixed by the scoring contract")
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
    exercise_type: Slug | None = None
    mapping_version: VersionKey | None = None
    required: bool
    timebox_minutes: Annotated[int, Field(gt=0, le=255)]
    objective: Text4096
    required_output: Annotated[tuple[Text1024, ...], Field(min_length=1)]
    pass_criteria: Annotated[tuple[Text1024, ...], Field(min_length=1)]
    evidence_requirements: Annotated[tuple[Text1024, ...], Field(min_length=1)]
    procedure: Annotated[tuple[TaskContractStepConfig, ...], Field(min_length=1)]
    constraints: Annotated[tuple[Text1024, ...], Field(min_length=1)]
    correction_selection: CorrectionSelectionConfig | None = None
    allowed_ai_role: Literal[
        "none", "planner", "tutor", "coach", "interviewer", "reviewer", "analyst"
    ]

    @model_validator(mode="after")
    def validate_correction_shape(self) -> RoadmapTaskConfig:
        is_correction = self.block == "correction_warmup"
        if is_correction != (self.correction_selection is not None):
            raise ValueError("correction selection is required only for correction warm-up tasks")
        if is_correction:
            if self.exercise_type is not None or self.mapping_version is not None:
                raise ValueError(
                    "correction warm-up inherits exercise and mapping from the due correction"
                )
            if self.required:
                raise ValueError("correction warm-up must be conditional, not required")
        elif self.exercise_type is None or self.mapping_version is None:
            raise ValueError("non-correction tasks require exercise and mapping version")
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
    inherits_core_prompt: Literal[True]
    inherits_original_exercise: Literal[True]
    inherits_original_mapping_version: Literal[True]
    no_attempt_c: Literal[True]
    skill_level_effect: Literal["none"]

    @model_validator(mode="after")
    def validate_allowed_kinds(self) -> CorrectionSelectionConfig:
        expected = {
            "spoken_attempt_b",
            "written_attempt_b",
            "targeted_sql_correction",
        }
        if self.allowed_kinds != expected:
            raise ValueError("correction kinds are fixed by the learning contract")
        return self


class TaskContractConfig(StrictModel):
    required_output: Annotated[tuple[Text1024, ...], Field(min_length=1)]
    pass_criteria: Annotated[tuple[Text1024, ...], Field(min_length=1)]
    evidence_requirements: Annotated[tuple[Text1024, ...], Field(min_length=1)]
    procedure: Annotated[tuple[TaskContractStepConfig, ...], Field(min_length=1)]
    constraints: Annotated[tuple[Text1024, ...], Field(min_length=1)]
    correction_selection: CorrectionSelectionConfig | None = None


class RoadmapReconciliationConfig(StrictModel):
    slug: Slug
    reviewed: Literal[True]
    target_task_id: Annotated[str, Field(pattern=r"^m1-w[1-4]-d[0-9]{2}-[a-z0-9-]+$")]
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
                    raise ValueError(f"roadmap day field {field_name!r} is not permitted")
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
                    if task.get("block") != "correction_warmup":
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


class RoadmapProgramConfig(StrictModel):
    program_key: Literal["tam_phase_1"]
    display_name: Literal["TAM Study Phase 1"]
    target_label: Literal["Phase 1 target — six weeks"]
    nominal_weeks: Literal[6]


class RoadmapLineageConfig(StrictModel):
    predecessor_roadmap_version: VersionKey
    legacy_task_map_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    compatibility_month: Literal[1]


class RoadmapCalendarConfig(StrictModel):
    anchor_date: date
    nominal_end_date: date
    weekday_minutes: int
    saturday_minutes: int
    sunday_minutes: int
    ordinary_interview_minutes: int
    pipeline_minutes: int
    roadmap_minutes: int
    close_minutes: int

    @model_validator(mode="after")
    def validate_phase1_calendar(self) -> RoadmapCalendarConfig:
        if self.anchor_date >= self.nominal_end_date:
            raise ValueError("calendar anchor date must precede nominal end date")
        if self.weekday_minutes != 180:
            raise ValueError("weekday minutes must equal 180")
        if (self.saturday_minutes, self.sunday_minutes) != (120, 0):
            raise ValueError("weekend minutes must equal 120/0")
        if (
            self.ordinary_interview_minutes,
            self.pipeline_minutes,
            self.roadmap_minutes,
            self.close_minutes,
        ) != (60, 30, 75, 15):
            raise ValueError("weekday component minutes must equal 60/30/75/15")
        return self


class Week7PolicyConfig(StrictModel):
    available: Literal[True]
    starts_on: date
    ends_on: date
    completion_only: Literal[True]
    variance_trigger_percent: Literal[15]
    provisional_trigger_codes: tuple[Literal["actual_variance_above_threshold"], ...]
    activation_trigger_codes: tuple[Slug, ...]

    @model_validator(mode="after")
    def validate_week7_contract(self) -> Week7PolicyConfig:
        if self.starts_on >= self.ends_on:
            raise ValueError("Week 7 start must precede end")
        if self.provisional_trigger_codes != ("actual_variance_above_threshold",):
            raise ValueError("Week 7 provisional trigger codes are fixed")
        expected = (
            "coverage_incomplete",
            "exit_not_assessed",
            "exit_assessed_not_demonstrated",
        )
        if self.activation_trigger_codes != expected:
            raise ValueError("Week 7 activation trigger codes are fixed")
        return self


EnglishDimensionKey = Literal[
    "communication_effectiveness",
    "fluency",
    "accuracy",
    "vocabulary",
    "pronunciation_intelligibility",
    "listening",
]
EnglishModality = Literal["written", "spoken", "spoken_audio", "interactive_spoken"]


class EnglishDimensionConfig(StrictModel):
    dimension_key: EnglishDimensionKey
    weight: Weight
    modalities: Annotated[tuple[EnglishModality, ...], Field(min_length=1)]


class EnglishDimensionPolicyConfig(StrictModel):
    policy_version: Literal["phase-1-english-v1"]
    aggregate_skill_slug: Literal["tam_english"]
    scale_min: Literal[0]
    scale_max: Literal[4]
    unavailable_state: Literal["not_assessed"]
    accent_scored: Literal[False]
    dimensions: tuple[EnglishDimensionConfig, ...]

    @model_validator(mode="after")
    def validate_dimensions(self) -> EnglishDimensionPolicyConfig:
        expected = {
            "communication_effectiveness": (Decimal("0.30"), ("written", "spoken")),
            "fluency": (Decimal("0.25"), ("spoken_audio",)),
            "accuracy": (Decimal("0.15"), ("written", "spoken")),
            "vocabulary": (Decimal("0.10"), ("written", "spoken")),
            "pronunciation_intelligibility": (Decimal("0.10"), ("spoken_audio",)),
            "listening": (Decimal("0.10"), ("interactive_spoken",)),
        }
        actual = {item.dimension_key: (item.weight, item.modalities) for item in self.dimensions}
        if len(self.dimensions) != 6 or actual != expected:
            raise ValueError("exactly six English dimensions are required")
        return self


class InterviewQueueItemConfig(StrictModel):
    ordinal: Annotated[int, Field(ge=1, le=30)]
    segment: Annotated[int, Field(ge=1, le=6)]
    question_key: Slug
    selection_mode: Literal["ordered", "fixed_event"]
    fixed_local_date: date | None = None
    prompt: Text1024

    @model_validator(mode="after")
    def validate_selection(self) -> InterviewQueueItemConfig:
        if self.segment != ((self.ordinal - 1) // 5) + 1:
            raise ValueError("interview queue segment must match its five-item band")
        if self.ordinal == 30:
            if self.selection_mode != "fixed_event" or self.fixed_local_date != date(2026, 10, 2):
                raise ValueError("Q30 must be the fixed October 2 event")
        elif self.selection_mode != "ordered" or self.fixed_local_date is not None:
            raise ValueError("Q1-Q29 must be ordered without fixed dates")
        return self


class InterviewProcedureStepConfig(StrictModel):
    step_key: Slug
    minutes: Annotated[int, Field(gt=0, le=60)]
    assistance: Literal["none", "coach_after_attempt_a", "analyst"]
    fresh_codex_task: bool = False
    after_coach_handoff: bool = False


class AttemptBContractConfig(StrictModel):
    separate_from_coach_task: Literal[True]
    same_question_as_attempt_a: Literal[True]
    qualifying_for_level: Literal[False]


class CoachHandoffConfig(StrictModel):
    required_before_attempt_b: Literal[True]
    coach_must_not_claim_attempt_b: Literal[True]


class OrdinaryInterviewContractConfig(StrictModel):
    kind: Literal["ordinary_interview"]
    total_minutes: Literal[60]
    steps: tuple[InterviewProcedureStepConfig, ...]
    attempt_b: AttemptBContractConfig
    coach_handoff: CoachHandoffConfig

    @model_validator(mode="after")
    def validate_procedure(self) -> OrdinaryInterviewContractConfig:
        expected = (
            ("frame", 5, "none"),
            ("independent_attempt_a", 15, "none"),
            ("self_review", 5, "none"),
            ("codex_coaching", 20, "coach_after_attempt_a"),
            ("separate_attempt_b", 5, "none"),
            ("save_handoff_and_notes", 10, "analyst"),
        )
        actual = tuple((step.step_key, step.minutes, step.assistance) for step in self.steps)
        if actual != expected:
            raise ValueError("ordinary interview procedure must equal 5/15/5/20/5/10")
        coaching = self.steps[3]
        attempt_b = self.steps[4]
        if not coaching.fresh_codex_task or coaching.after_coach_handoff:
            raise ValueError("Codex coaching requires a fresh task after Attempt A")
        if not attempt_b.after_coach_handoff or attempt_b.fresh_codex_task:
            raise ValueError("Attempt B must be separate and after the coach handoff")
        if any(step.fresh_codex_task for step in self.steps[:3] + self.steps[4:]):
            raise ValueError("only the Codex coaching step may create a fresh task")
        return self


class SealedFinalMockContractConfig(StrictModel):
    kind: Literal["sealed_final_mock"]
    total_minutes: Literal[60]
    queue_ordinal: Literal[30]
    fixed_local_date: date
    steps: tuple[InterviewProcedureStepConfig, ...]
    coaching_allowed: Literal[False]
    attempt_b_allowed: Literal[False]

    @model_validator(mode="after")
    def validate_sealed_mock(self) -> SealedFinalMockContractConfig:
        expected = (("setup", 5), ("sealed_mock", 45), ("save_and_self_review", 10))
        actual = tuple((step.step_key, step.minutes) for step in self.steps)
        if self.fixed_local_date != date(2026, 10, 2) or actual != expected:
            raise ValueError("sealed final mock must equal October 2 and 5/45/10")
        if any(step.assistance != "none" for step in self.steps):
            raise ValueError("sealed final mock cannot use assistance")
        return self


class PipelineContractConfig(StrictModel):
    kind: Literal["multi_action_pipeline"]
    output_contract_version: Literal[2]
    weekly_quality_target: Literal[10]
    default_weekday_actions: Literal[2]
    daily_pass_fail: Literal[False]
    action_types: tuple[Literal["application", "recruiter_reply"], ...]
    required_fields: tuple[Slug, ...]
    nonqualifying_reasons: tuple[
        Literal["simple_acknowledgement", "research_without_required_artifact"], ...
    ]
    conversion_stages: tuple[
        Literal[
            "applied",
            "recruiter_contact",
            "recruiter_screen",
            "hiring_manager_interview",
            "next_round",
            "offer",
            "rejected",
            "no_response",
            "withdrawn",
        ],
        ...,
    ]

    @model_validator(mode="after")
    def validate_pipeline(self) -> PipelineContractConfig:
        required = {
            "company",
            "role",
            "context_snapshot_ref",
            "relevance",
            "known_gap",
            "resume_or_story_version",
            "completed_action",
            "completed_on",
            "current_stage",
            "next_action",
        }
        if self.action_types != ("application", "recruiter_reply"):
            raise ValueError("pipeline action types are fixed and ordered")
        if self.nonqualifying_reasons != (
            "simple_acknowledgement",
            "research_without_required_artifact",
        ):
            raise ValueError("pipeline nonqualifying reasons are fixed and ordered")
        if set(self.required_fields) != required or len(self.required_fields) != len(required):
            raise ValueError("pipeline required fields are fixed")
        expected_stages = {
            "applied",
            "recruiter_contact",
            "recruiter_screen",
            "hiring_manager_interview",
            "next_round",
            "offer",
            "rejected",
            "no_response",
            "withdrawn",
        }
        if set(self.conversion_stages) != expected_stages or len(self.conversion_stages) != len(
            expected_stages
        ):
            raise ValueError("pipeline conversion stages are fixed")
        return self


class RoadmapContractsConfig(StrictModel):
    interview_cycle: OrdinaryInterviewContractConfig
    sealed_final_mock: SealedFinalMockContractConfig
    pipeline: PipelineContractConfig


class CoverageRequirementConfig(StrictModel):
    requirement_key: Text128
    kind: Literal[
        "task", "canonical_assessment", "resource", "exit_criterion", "next_phase_priorities"
    ]
    legacy_stable_id: Text128 | None = None
    source_path: Text2048
    source_heading: Text512


class CoverageAssignmentConfig(StrictModel):
    requirement_key: Text128
    phase_task_ids: tuple[Text128, ...] = ()
    completion_owner_task_id: Text128
    treatment: Literal["transition_import", "scheduled", "closure_gate"]
    reconciliation_note: Text1024

    @model_validator(mode="after")
    def validate_owner(self) -> CoverageAssignmentConfig:
        if not self.phase_task_ids and self.treatment != "transition_import":
            raise ValueError("coverage assignment requires phase tasks or transition import")
        if self.phase_task_ids and self.completion_owner_task_id not in self.phase_task_ids:
            raise ValueError("coverage completion owner must be one of its phase tasks")
        return self


class CoverageConfig(StrictModel):
    requirements: tuple[CoverageRequirementConfig, ...]
    assignments: tuple[CoverageAssignmentConfig, ...]

    @model_validator(mode="after")
    def validate_ownership(self) -> CoverageConfig:
        requirement_keys = [item.requirement_key for item in self.requirements]
        assignment_keys = [item.requirement_key for item in self.assignments]
        if len(set(requirement_keys)) != len(requirement_keys):
            raise ValueError("coverage requirement keys must be unique")
        if sorted(requirement_keys) != sorted(assignment_keys):
            raise ValueError("each coverage requirement must have exactly one assignment")
        return self


class RoadmapTaskV2Config(StrictModel):
    stable_id: Annotated[
        str, Field(pattern=r"^p1-w0[1-7]-d(?:0[1-9]|[1-3][0-9]|4[0-2])-[a-z0-9-]+$")
    ]
    week: Annotated[int, Field(ge=1, le=7)]
    day: Annotated[int, Field(ge=1, le=42)]
    source_path: Text2048
    source_heading: Text512
    block: Literal[
        "communication_spoken",
        "career_pipeline",
        "technical_learning",
        "daily_close",
        "saturday_assessment",
    ]
    order: Annotated[int, Field(ge=1, le=20)]
    exercise_type: Slug
    timebox_minutes: Annotated[int, Field(gt=0, le=180)]
    contract: Slug
    allowed_ai_role: Literal[
        "none", "planner", "tutor", "coach", "interviewer", "reviewer", "analyst"
    ]


class RoadmapTaskMapV2File(StrictModel):
    schema_version: Literal[2]
    roadmap_version: Literal["phase-1-six-week-v1"]
    mapping_version: Literal["seed-v1"]
    month: Literal[1]
    default_required: Literal[True]
    program: RoadmapProgramConfig
    lineage: RoadmapLineageConfig
    calendar: RoadmapCalendarConfig
    week7: Week7PolicyConfig
    interview_queue: tuple[InterviewQueueItemConfig, ...]
    english_dimensions: EnglishDimensionPolicyConfig
    coverage: CoverageConfig
    contracts: RoadmapContractsConfig
    reconciliations: tuple[RoadmapReconciliationConfig, ...] = ()
    tasks: tuple[RoadmapTaskV2Config, ...]

    @model_validator(mode="before")
    @classmethod
    def flatten_days(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        value = dict(value)
        days = value.pop("days", None)
        if days is None:
            return value
        if not isinstance(days, list):
            raise ValueError("roadmap days must be a list")
        tasks: list[object] = []
        for day in days:
            if not isinstance(day, dict):
                raise ValueError("each roadmap day must be a mapping")
            unexpected = set(day) - {"week", "day", "source_path", "source_heading", "tasks"}
            if unexpected:
                raise ValueError(f"roadmap day field {sorted(unexpected)[0]!r} is not permitted")
            for task in day.get("tasks", []):
                if not isinstance(task, dict):
                    raise ValueError("each roadmap task must be a mapping")
                task = dict(task)
                for key in ("week", "day", "source_path", "source_heading"):
                    task.setdefault(key, day.get(key))
                tasks.append(task)
        value["tasks"] = tasks
        return value

    @model_validator(mode="after")
    def validate_phase1_release(self) -> RoadmapTaskMapV2File:
        if (
            self.calendar.anchor_date != date(2026, 8, 24)
            or self.calendar.nominal_end_date != date(2026, 10, 3)
            or self.week7.starts_on != date(2026, 10, 5)
            or self.week7.ends_on != date(2026, 10, 10)
        ):
            raise ValueError("Phase 1 calendar and Week 7 dates are fixed")
        if len(self.interview_queue) != 30:
            raise ValueError("interview queue must contain exactly 30 items")
        if tuple(item.ordinal for item in self.interview_queue) != tuple(range(1, 31)):
            raise ValueError("interview queue ordinals must be ordered 1-30")
        keys = [item.question_key for item in self.interview_queue]
        if len(set(keys)) != 30:
            raise ValueError("interview queue question keys must be unique")
        task_ids = [task.stable_id for task in self.tasks]
        if len(set(task_ids)) != len(task_ids):
            raise ValueError("Phase 1 task IDs must be unique")
        return self


class CanonicalConfigPayload(StrictModel):
    skills: SkillsFile
    exercise_types: ExerciseTypesFile
    rubrics: RubricsFile
    roadmap_tasks: RoadmapTaskMapFile


@dataclass(frozen=True, slots=True)
class ConfigBundle:
    schema_version: int
    roadmap_schema_version: int
    config_version: str
    skills: tuple[SkillConfig, ...]
    exercise_types: tuple[ExerciseTypeConfig, ...]
    formula: FormulaConfig
    rubrics: tuple[RubricConfig, ...]
    roadmap_version: str
    roadmap_contracts: Mapping[str, TaskContractConfig]
    reconciliations: tuple[RoadmapReconciliationConfig, ...]
    roadmap_tasks: tuple[RoadmapTaskConfig | RoadmapTaskV2Config, ...]
    program: RoadmapProgramConfig
    lineage: RoadmapLineageConfig | None
    calendar: RoadmapCalendarConfig
    week7: Week7PolicyConfig | None
    interview_queue: tuple[InterviewQueueItemConfig, ...]
    english_dimensions: EnglishDimensionPolicyConfig | None
    coverage: CoverageConfig | None
    phase1_contracts: RoadmapContractsConfig | None
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

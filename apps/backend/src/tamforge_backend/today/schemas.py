"""Strict contracts for the deterministic Today workspace and daily close."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..learning.enums import ActivityState

PositiveId = Annotated[int, Field(gt=0)]
AiRole = Literal[
    "none", "planner", "tutor", "coach", "interviewer", "reviewer", "analyst"
]
DayStatus = Literal[
    "off", "planned", "in_progress", "closed", "incomplete", "skipped"
]
UnfinishedClassification = Literal[
    "none", "required", "useful", "optional", "superseded"
]
UnfinishedConsequence = Literal[
    "none", "replace_adaptive", "retrieval_queue", "drop", "link_stronger_evidence"
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TodaySourceReference(StrictModel):
    path: Annotated[str, Field(min_length=1, max_length=2048)]
    anchor: Annotated[str | None, Field(max_length=512)] = None


class TodayTaskCard(StrictModel):
    activity_id: PositiveId
    roadmap_order: PositiveId
    stable_id: Annotated[str, Field(min_length=1, max_length=192)]
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
    state: ActivityState
    objective: Annotated[str, Field(min_length=1, max_length=4096)]
    timebox_minutes: Annotated[int, Field(gt=0, le=255)]
    source_references: Annotated[tuple[TodaySourceReference, ...], Field(max_length=256)]
    required_output: Annotated[tuple[str, ...], Field(max_length=256)]
    pass_criteria: Annotated[tuple[str, ...], Field(max_length=256)]
    allowed_ai_role: AiRole
    evidence_requirements: Annotated[tuple[str, ...], Field(max_length=256)]
    required: bool
    optimistic_version: PositiveId


class TodayBlock(StrictModel):
    name: str
    planned_minutes: Annotated[int, Field(ge=0, le=255)]
    activity_ids: tuple[PositiveId, ...]


class TodayCorrection(StrictModel):
    id: PositiveId
    priority: Literal[1, 2]
    due_date: date
    instruction: Annotated[str, Field(min_length=1, max_length=1024)]
    status: Literal["pending", "scheduled"]
    attempt_b_activity_id: PositiveId | None


class TodayInterview(StrictModel):
    id: PositiveId
    company: Annotated[str, Field(min_length=1, max_length=256)]
    role: Annotated[str, Field(min_length=1, max_length=256)]
    stage: Annotated[str, Field(min_length=1, max_length=128)]
    starts_at: datetime
    expected_duration_minutes: Annotated[int, Field(gt=0, le=480)]
    privacy_permission_code: Literal[
        "permission_not_requested",
        "permission_granted",
        "permission_denied",
        "recording_prohibited",
    ]


class TodaySelfReview(StrictModel):
    activity_id: PositiveId
    objective: Annotated[str, Field(min_length=1, max_length=4096)]
    output_committed_at: datetime


class TodayAnalysis(StrictModel):
    activity_id: PositiveId
    state: Literal["ready", "needs_attention"]
    progress_label: Literal["ready", "action_required"]
    updated_at: datetime


class TodayRoadmap(StrictModel):
    version_id: PositiveId
    version_key: Annotated[str, Field(min_length=1, max_length=128)]
    version_number: PositiveId
    month: PositiveId
    week: PositiveId
    day: Annotated[int, Field(ge=1, le=7)]


class TodayTimePolicy(StrictModel):
    target_minutes: Annotated[int, Field(ge=0, le=240)]
    acceptable_minimum: Annotated[int, Field(ge=0, le=225)]
    hard_stop_minutes: Annotated[int, Field(ge=0, le=255)]
    focused_minutes: Annotated[int, Field(ge=0, le=255)]
    hard_stop_recommended: bool


class ContinueAction(StrictModel):
    kind: Literal[
        "correction_warmup",
        "resume_activity",
        "complete_self_review",
        "start_activity",
        "review_feedback",
        "close_day",
    ]
    target_id: PositiveId
    label: Annotated[str, Field(min_length=1, max_length=128)]
    allowed_ai_role: AiRole


class TodayReadInput(StrictModel):
    """Repository result before policy selection and version hashing."""

    local_date: date
    timezone: str
    day_id: PositiveId | None
    day_type: Literal["weekday", "saturday", "sunday", "interview"]
    day_status: DayStatus
    roadmap: TodayRoadmap
    planned_minutes: Annotated[int, Field(ge=0, le=255)]
    focused_minutes: Annotated[int, Field(ge=0, le=255)]
    tasks: tuple[TodayTaskCard, ...]
    corrections: tuple[TodayCorrection, ...]
    interviews: tuple[TodayInterview, ...]
    awaiting_self_reviews: tuple[TodaySelfReview, ...]
    analyses: tuple[TodayAnalysis, ...]
    source_updated_at: datetime


class TodayResponse(StrictModel):
    local_date: date
    timezone: str
    day_id: PositiveId | None
    day_type: Literal["weekday", "saturday", "sunday", "interview"]
    day_status: DayStatus
    roadmap: TodayRoadmap
    total_planned_minutes: Annotated[int, Field(ge=0, le=255)]
    time_policy: TodayTimePolicy
    required_blocks: tuple[TodayBlock, ...]
    tasks: tuple[TodayTaskCard, ...]
    corrections: Annotated[tuple[TodayCorrection, ...], Field(max_length=2)]
    interviews: tuple[TodayInterview, ...]
    awaiting_self_reviews: tuple[TodaySelfReview, ...]
    analyses: tuple[TodayAnalysis, ...]
    primary_continue: ContinueAction | None
    source_updated_at: datetime
    read_model_version: str
    etag: str


class EvidenceManifest(StrictModel):
    schema_version: Literal[1] = 1
    activity_ids: Annotated[tuple[PositiveId, ...], Field(max_length=64)] = ()
    attempt_ids: Annotated[tuple[PositiveId, ...], Field(max_length=64)] = ()
    artifact_ids: Annotated[tuple[PositiveId, ...], Field(max_length=64)] = ()
    self_review_ids: Annotated[tuple[PositiveId, ...], Field(max_length=64)] = ()

    @model_validator(mode="after")
    def unique_ids(self) -> EvidenceManifest:
        for values in (
            self.activity_ids,
            self.attempt_ids,
            self.artifact_ids,
            self.self_review_ids,
        ):
            if len(values) != len(set(values)):
                raise ValueError("evidence manifest IDs must be unique")
        return self


_CONSEQUENCE_BY_CLASSIFICATION: dict[str, UnfinishedConsequence] = {
    "none": "none",
    "required": "replace_adaptive",
    "useful": "retrieval_queue",
    "optional": "drop",
    "superseded": "link_stronger_evidence",
}


class DailyCloseCommand(StrictModel):
    evidence_confirmed: bool
    evidence_manifest: EvidenceManifest
    strongest_output: Annotated[str, Field(min_length=1, max_length=4096)]
    repeated_mistake: Annotated[str, Field(min_length=1, max_length=4096)]
    unfinished_classification: UnfinishedClassification
    unfinished_requirement: Annotated[str | None, Field(max_length=4096)]
    correction_ids: Annotated[tuple[PositiveId, ...], Field(max_length=2)] = ()

    @field_validator("strongest_output", "repeated_mistake")
    @classmethod
    def compact_nonblank(cls, value: str) -> str:
        if not value.strip() or len(value.encode()) > 4096:
            raise ValueError("daily-close narrative must be compact and non-blank")
        return value

    @model_validator(mode="after")
    def coherent_close(self) -> DailyCloseCommand:
        if not self.evidence_confirmed:
            raise ValueError("daily close requires evidence confirmation")
        if len(self.correction_ids) != len(set(self.correction_ids)):
            raise ValueError("daily-close corrections must be unique")
        has_unfinished = self.unfinished_classification != "none"
        if has_unfinished != (
            self.unfinished_requirement is not None
            and bool(self.unfinished_requirement.strip())
        ):
            raise ValueError("unfinished classification and requirement are incoherent")
        if (
            self.unfinished_requirement is not None
            and len(self.unfinished_requirement.encode()) > 4096
        ):
            raise ValueError("unfinished requirement is too large")
        return self

    @property
    def consequence(self) -> UnfinishedConsequence:
        return _CONSEQUENCE_BY_CLASSIFICATION[self.unfinished_classification]


class DailyCloseResponse(StrictModel):
    daily_close_id: PositiveId
    study_day_id: PositiveId
    day_status: Literal["closed", "incomplete"]
    closed_at: datetime
    consequence: UnfinishedConsequence
    replayed: bool


__all__ = [
    "ContinueAction",
    "DailyCloseCommand",
    "DailyCloseResponse",
    "EvidenceManifest",
    "TodayAnalysis",
    "TodayBlock",
    "TodayCorrection",
    "TodayInterview",
    "TodayReadInput",
    "TodayResponse",
    "TodayRoadmap",
    "TodaySelfReview",
    "TodaySourceReference",
    "TodayTaskCard",
    "TodayTimePolicy",
]

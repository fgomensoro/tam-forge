from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

InterviewStatus = Literal["scheduled", "completed", "cancelled", "rescheduled"]
PrivacyPermission = Literal[
    "permission_not_requested", "permission_granted", "permission_denied", "recording_prohibited"
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InterviewCommand(StrictModel):
    company: Annotated[str, Field(min_length=1, max_length=256)]
    role: Annotated[str, Field(min_length=1, max_length=256)]
    stage: Annotated[str, Field(min_length=1, max_length=128)]
    starts_at: datetime
    expected_duration_minutes: Annotated[int, Field(ge=1, le=480)]
    status: InterviewStatus = "scheduled"
    privacy_permission_code: PrivacyPermission = "permission_not_requested"


class InterviewRecordingSummary(StrictModel):
    recording_id: UUID
    state: str
    started_at: datetime | None
    transcript_lineage_accepted: bool


class InterviewResponse(StrictModel):
    id: int
    has_transcript: bool = False
    company: str
    role: str
    stage: str
    starts_at: datetime
    expected_duration_minutes: int
    status: InterviewStatus
    privacy_permission_code: PrivacyPermission
    recordings: tuple[InterviewRecordingSummary, ...] = ()
    created_at: datetime
    updated_at: datetime


class InterviewPage(StrictModel):
    items: tuple[InterviewResponse, ...]


class AttachRecordingCommand(StrictModel):
    recording_id: UUID


class InterviewTranscriptCommand(StrictModel):
    """A transcript pasted for an interview without audio; `Speaker: words` per line."""

    text: Annotated[str, Field(min_length=1, max_length=1_048_576)]
    learner_labels: Annotated[tuple[str, ...], Field(max_length=8)] = ("Frank", "Me")


class TranscriptTurnResponse(StrictModel):
    speaker: Literal["learner", "other"]
    label: str
    text: str


class InterviewTranscriptResponse(StrictModel):
    """The analysis of a transcript-only interview, honest about what it cannot say."""

    interview_id: int
    analysis_kind: Literal["transcript_only"]
    analysis_version: str
    turns: tuple[TranscriptTurnResponse, ...]
    learner_words: int
    other_words: int
    learner_turns: int
    other_turns: int
    learner_word_share: float
    longest_learner_turn_words: int
    excluded_findings: tuple[str, ...]
    created_at: datetime


class DebriefFindingResponse(StrictModel):
    statement: str
    evidence: str
    skill_slug: str


class DebriefSkillEffectResponse(StrictModel):
    skill_slug: str
    skill_name: str
    direction: Literal["up", "flat", "down"]
    evidence: str


class DebriefPracticeResponse(StrictModel):
    description: str
    skill_slug: str
    minutes: int


class DebriefDimensionResponse(StrictModel):
    slug: str
    name: str
    score: Decimal
    maximum: Decimal
    rationale: str


class InterviewDebriefResponse(StrictModel):
    """Where the debrief stands, then what it says. It proposes; it never changes the plan."""

    interview_id: int
    status: Literal["not_requested", "queued", "running", "ready", "needs_attention"]
    failure_category: str | None = None
    debrief_id: int | None = None
    transcript_source: Literal["recording", "transcript_only"] | None = None
    model: str | None = None
    summary: str | None = None
    dimensions: tuple[DebriefDimensionResponse, ...] = ()
    strengths: tuple[DebriefFindingResponse, ...] = ()
    gaps: tuple[DebriefFindingResponse, ...] = ()
    skills_affected: tuple[DebriefSkillEffectResponse, ...] = ()
    next_week_practice: tuple[DebriefPracticeResponse, ...] = ()
    hiring_progression: str | None = None
    created_at: datetime | None = None


class TimelineDimensionScore(StrictModel):
    slug: str
    score: Decimal


class TimelineSkillEffect(StrictModel):
    skill_slug: str
    direction: Literal["up", "flat", "down"]


class TimelineGap(StrictModel):
    statement: str
    skill_slug: str


class InterviewTimelineItem(StrictModel):
    """One interview in sequence: its record, and its debrief's scores when it has one."""

    interview_id: int
    company: str
    role: str
    stage: str
    starts_at: datetime
    status: str
    has_debrief: bool
    hiring_progression: str | None = None
    dimensions: tuple[TimelineDimensionScore, ...] = ()
    skills_affected: tuple[TimelineSkillEffect, ...] = ()
    gaps: tuple[TimelineGap, ...] = ()


class RecurringGap(StrictModel):
    """A skill that showed up as a gap in more than one debriefed interview."""

    skill_slug: str
    interview_count: int
    statements: tuple[str, ...]


class DimensionTrend(StrictModel):
    slug: str
    name: str
    scores: tuple[TimelineDimensionScore, ...]  # slug carries the interview id as text
    latest: Decimal | None
    delta_from_first: Decimal | None


class InterviewTimelineResponse(StrictModel):
    """The interviews in order, the comparison dimensions across them, the gaps that recur."""

    items: tuple[InterviewTimelineItem, ...]
    debriefed: int
    dimension_trends: tuple[DimensionTrend, ...]
    recurring_gaps: tuple[RecurringGap, ...]


ReferenceKind = Literal["answer_bank", "story_catalog"]


class ReferenceImportCommand(StrictModel):
    """One markdown document (the answer bank or the story catalog) to split into entries."""

    kind: ReferenceKind
    title: Annotated[str, Field(min_length=1, max_length=256)]
    markdown: Annotated[str, Field(min_length=1, max_length=1_048_576)]


class ReferenceEntryResponse(StrictModel):
    id: int
    kind: ReferenceKind
    document_title: str
    heading: str
    body: str
    readiness_label: str
    readiness_verified: bool
    created_at: datetime


class ReferenceImportResponse(StrictModel):
    kind: ReferenceKind
    created: int
    existing: int
    entries: tuple[ReferenceEntryResponse, ...]


class ReferencePage(StrictModel):
    items: tuple[ReferenceEntryResponse, ...]


__all__ = [
    "AttachRecordingCommand",
    "DebriefDimensionResponse",
    "DebriefFindingResponse",
    "DimensionTrend",
    "InterviewTimelineItem",
    "InterviewTimelineResponse",
    "RecurringGap",
    "TimelineDimensionScore",
    "TimelineGap",
    "TimelineSkillEffect",
    "DebriefPracticeResponse",
    "DebriefSkillEffectResponse",
    "InterviewDebriefResponse",
    "InterviewCommand",
    "InterviewPage",
    "InterviewRecordingSummary",
    "InterviewResponse",
    "InterviewTranscriptCommand",
    "InterviewTranscriptResponse",
    "ReferenceEntryResponse",
    "ReferenceImportCommand",
    "ReferenceImportResponse",
    "ReferencePage",
    "TranscriptTurnResponse",
]

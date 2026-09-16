from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EnglishClassCommand(StrictModel):
    teacher: Annotated[str, Field(min_length=1, max_length=256)]
    starts_at: datetime
    expected_duration_minutes: Annotated[int, Field(ge=1, le=480)]
    notes: Annotated[str, Field(max_length=16384)] = ""


class ClassRecordingSummary(StrictModel):
    recording_id: UUID
    state: str
    started_at: datetime | None
    transcript_lineage_accepted: bool


class EnglishClassResponse(StrictModel):
    id: int
    kind: Literal["english_class"] = "english_class"
    teacher: str
    starts_at: datetime
    expected_duration_minutes: int
    notes: str
    skill_slug: Literal["tam_english"]
    recordings: tuple[ClassRecordingSummary, ...] = ()
    created_at: datetime
    updated_at: datetime


class ClassAspectResponse(StrictModel):
    score: Decimal
    rationale: str
    evidence: str


class ClassRecurringErrorResponse(StrictModel):
    pattern: str
    example: str
    correction: str


class ClassAnalysisResponse(StrictModel):
    """Where the analysis stands, then what it says about this class and the ones before."""

    class_id: int
    status: Literal["not_requested", "queued", "running", "ready", "needs_attention"]
    failure_category: str | None = None
    analysis_id: int | None = None
    model: str | None = None
    fluency: ClassAspectResponse | None = None
    vocabulary: ClassAspectResponse | None = None
    recurring_errors: tuple[ClassRecurringErrorResponse, ...] = ()
    progress_direction: Literal["up", "flat", "down", "first_class"] | None = None
    progress_statement: str | None = None
    next_focus: str | None = None
    previous_classes: int = 0
    created_at: datetime | None = None


class EnglishClassPage(StrictModel):
    items: tuple[EnglishClassResponse, ...]


class AttachClassRecordingCommand(StrictModel):
    recording_id: UUID


__all__ = [
    "ClassAnalysisResponse",
    "ClassAspectResponse",
    "ClassRecurringErrorResponse",
    "AttachClassRecordingCommand",
    "ClassRecordingSummary",
    "EnglishClassCommand",
    "EnglishClassPage",
    "EnglishClassResponse",
]

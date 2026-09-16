from __future__ import annotations

from datetime import datetime
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


class EnglishClassPage(StrictModel):
    items: tuple[EnglishClassResponse, ...]


class AttachClassRecordingCommand(StrictModel):
    recording_id: UUID


__all__ = [
    "AttachClassRecordingCommand",
    "ClassRecordingSummary",
    "EnglishClassCommand",
    "EnglishClassPage",
    "EnglishClassResponse",
]

from __future__ import annotations

from datetime import datetime
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


__all__ = [
    "AttachRecordingCommand",
    "InterviewCommand",
    "InterviewPage",
    "InterviewRecordingSummary",
    "InterviewResponse",
]

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CoachEvidenceProposal(StrictModel):
    index: Annotated[int, Field(ge=0)]
    kind: Literal["note", "correction", "question"]
    text: str
    accepted: bool


class CoachMessageResponse(StrictModel):
    id: int
    speaker: Literal["learner", "coach"]
    text: str
    next_step: str | None
    proposed_evidence: list[CoachEvidenceProposal]
    created_at: datetime


class CoachThreadResponse(StrictModel):
    activity_id: int
    thread_id: int | None
    coaching_allowed: bool
    committed: bool
    next_step: str
    messages: list[CoachMessageResponse]


class CoachMessageCommand(StrictModel):
    text: Annotated[str, Field(min_length=1, max_length=8192)]


class AcceptEvidenceCommand(StrictModel):
    message_id: Annotated[int, Field(gt=0)]
    index: Annotated[int, Field(ge=0, le=4)]


__all__ = [
    "AcceptEvidenceCommand",
    "CoachEvidenceProposal",
    "CoachMessageCommand",
    "CoachMessageResponse",
    "CoachThreadResponse",
]

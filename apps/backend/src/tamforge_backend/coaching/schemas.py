from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CoachEvidenceProposal(StrictModel):
    index: Annotated[int, Field(ge=0)]
    kind: Literal["note", "correction", "question", "card"]
    text: str
    answer: str = ""
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
    assistance_mode: Literal["none", "coach_preparation", "hint_ladder"]
    next_step: str
    messages: list[CoachMessageResponse]


class CoachMessageCommand(StrictModel):
    text: Annotated[str, Field(min_length=1, max_length=8192)]


class AcceptEvidenceCommand(StrictModel):
    """Accept one proposal. A card may be edited on the way in; blank fields keep the proposal."""

    message_id: Annotated[int, Field(gt=0)]
    index: Annotated[int, Field(ge=0, le=4)]
    question: Annotated[str, Field(max_length=2048)] = ""
    answer: Annotated[str, Field(max_length=4096)] = ""


__all__ = [
    "AcceptEvidenceCommand",
    "CoachEvidenceProposal",
    "CoachMessageCommand",
    "CoachMessageResponse",
    "CoachThreadResponse",
]

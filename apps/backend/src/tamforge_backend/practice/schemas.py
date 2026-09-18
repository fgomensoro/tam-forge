"""Wire shapes of free interview practice."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

PracticeStatus = Literal["awaiting_transcript", "queued", "running", "ready", "needs_attention"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PracticeAnswerCommand(StrictModel):
    """One recorded practice answer. Sending it again for the same recording is a retry:
    it changes nothing stored and queues the review once the transcript exists."""

    question: Annotated[str, Field(min_length=1, max_length=1000)]
    recording_id: UUID
    reference_material_id: Annotated[int | None, Field(default=None, ge=1)]


class PracticeDimensionResponse(StrictModel):
    slug: str
    name: str
    score: Decimal
    evidence: str
    note: str


class PracticeFixResponse(StrictModel):
    heard: str
    say_instead: str
    why: str


class PracticeAnswerResponse(StrictModel):
    id: int
    question: str
    recording_id: UUID
    reference_material_id: int | None
    status: PracticeStatus
    failure_category: str | None
    model: str | None
    dimensions: tuple[PracticeDimensionResponse, ...]
    strengths: tuple[str, ...]
    fixes: tuple[PracticeFixResponse, ...]
    reference_coverage: str
    readiness: Literal["draft", "drilling", "ready"] | None
    created_at: datetime
    reviewed_at: datetime | None


class PracticeAnswerPage(StrictModel):
    items: tuple[PracticeAnswerResponse, ...]


class FollowUpCommand(StrictModel):
    """The answer just given, transcribed on the Mac. The server never waits for its own
    transcription: the learner is in front of the app."""

    question: Annotated[str, Field(min_length=1, max_length=1000)]
    reference_answer: Annotated[str, Field(default="", max_length=65536)]
    transcript: Annotated[str, Field(min_length=1, max_length=40000)]
    prior_follow_ups: Annotated[
        tuple[Annotated[str, Field(min_length=1, max_length=240)], ...],
        Field(default=(), max_length=2),
    ]


class FollowUpResponse(StrictModel):
    follow_up: str | None
    reason: Literal["weak_point", "pressure_probe"] | None


__all__ = [
    "FollowUpCommand",
    "FollowUpResponse",
    "PracticeAnswerCommand",
    "PracticeAnswerPage",
    "PracticeAnswerResponse",
    "PracticeDimensionResponse",
    "PracticeFixResponse",
    "PracticeStatus",
]

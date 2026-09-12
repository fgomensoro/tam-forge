from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NoteQueryItem(StrictModel):
    query: Annotated[str, Field(min_length=1, max_length=4000)]
    result: Annotated[str, Field(min_length=1, max_length=2000)]


class NoteFlashcardItem(StrictModel):
    question: Annotated[str, Field(min_length=1, max_length=500)]
    answer: Annotated[str, Field(min_length=1, max_length=1000)]


class StudyNoteContent(StrictModel):
    """What the learner may edit. Status, assistance and assessment are recorded, not typed."""

    title: Annotated[str, Field(min_length=1, max_length=200)]
    rule: Annotated[str, Field(max_length=2000)] = ""
    explanation: Annotated[str, Field(max_length=4000)] = ""
    example: Annotated[str, Field(max_length=4000)] = ""
    misconceptions: Annotated[list[str], Field(max_length=8)] = []
    validated_queries: Annotated[list[NoteQueryItem], Field(max_length=8)] = []
    sources: Annotated[list[str], Field(max_length=8)] = []
    flashcards: Annotated[list[NoteFlashcardItem], Field(max_length=12)] = []


class StudyNoteResponse(StudyNoteContent):
    id: int
    activity_id: int
    stable_id: str
    local_date: date
    status: Literal["draft", "approved"]
    drafted_by: Literal["learner", "coach"]
    assistance: Literal["independent", "coached"]
    assessment_status: str
    artifact_id: int | None
    content_sha256: str | None
    updated_at: datetime
    approved_at: datetime | None


class StudyNoteSummary(StrictModel):
    id: int
    activity_id: int
    stable_id: str
    local_date: date
    title: str
    status: Literal["draft", "approved"]
    assistance: Literal["independent", "coached"]
    flashcard_count: Annotated[int, Field(ge=0)]
    updated_at: datetime


class StudyNoteSearchResponse(StrictModel):
    query: str
    items: list[StudyNoteSummary]


__all__ = [
    "NoteFlashcardItem",
    "NoteQueryItem",
    "StudyNoteContent",
    "StudyNoteResponse",
    "StudyNoteSearchResponse",
    "StudyNoteSummary",
]

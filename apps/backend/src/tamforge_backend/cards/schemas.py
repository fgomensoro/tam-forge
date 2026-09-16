from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

CardSource = Literal["study_note", "evidence", "package", "coach", "manual"]
CardAssistance = Literal["independent", "coached"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CardCommand(StrictModel):
    question: Annotated[str, Field(min_length=1, max_length=2048)]
    answer: Annotated[str, Field(min_length=1, max_length=4096)]
    skill_slug: Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")]
    source_kind: CardSource = "manual"
    source_ref: Annotated[str, Field(max_length=256)] = ""
    assistance: CardAssistance = "independent"


class CardResponse(StrictModel):
    id: int
    question: str
    answer: str
    skill_slug: str
    source_kind: CardSource
    source_ref: str
    assistance: CardAssistance
    status: Literal["active", "suspended"]
    scheduler_version: str
    easiness: Decimal
    interval_days: int
    repetitions: int
    due_on: date
    created_at: datetime
    updated_at: datetime


class CardPage(StrictModel):
    items: tuple[CardResponse, ...]


class DueCardsResponse(StrictModel):
    local_date: date
    items: tuple[CardResponse, ...]


class ReviewCardCommand(StrictModel):
    grade: Annotated[int, Field(ge=0, le=5)]
    reviewed_on: date
    mode: Literal["written", "spoken"] = "written"
    recording_id: UUID | None = None


class CardReviewResponse(StrictModel):
    id: int
    card_id: int
    grade: int
    mode: Literal["written", "spoken"]
    reviewed_on: date
    interval_before: int
    interval_after: int
    easiness_after: Decimal
    due_after: date
    created_at: datetime


class CardReviewResult(StrictModel):
    card: CardResponse
    review: CardReviewResponse


class CardsExport(StrictModel):
    scheduler_version: str
    cards: tuple[CardResponse, ...]
    reviews: tuple[CardReviewResponse, ...]


__all__ = [
    "CardCommand",
    "CardPage",
    "CardResponse",
    "CardReviewResponse",
    "CardReviewResult",
    "CardsExport",
    "DueCardsResponse",
    "ReviewCardCommand",
]

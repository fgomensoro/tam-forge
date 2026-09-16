from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReviewedDimensionResponse(StrictModel):
    slug: str
    name: str
    score: Annotated[Decimal, Field(ge=0, le=20)]
    maximum: Annotated[Decimal, Field(gt=0, le=20)]
    rationale: str
    evidence: str


class ReviewFindingResponse(StrictModel):
    statement: str
    instruction: str = ""


class ActivityReviewResponse(StrictModel):
    """The learner-facing review: where it stands, then the scores and the reasoning."""

    activity_id: int
    status: Literal["not_requested", "queued", "running", "ready", "needs_attention"]
    failure_category: str | None = None
    review_id: int | None = None
    attempt_id: int | None = None
    rubric_slug: str | None = None
    rubric_version: str | None = None
    model: str | None = None
    verdict: str | None = None
    dimensions: tuple[ReviewedDimensionResponse, ...] = ()
    strengths: tuple[ReviewFindingResponse, ...] = ()
    corrections: tuple[ReviewFindingResponse, ...] = ()
    next_practice: str | None = None
    evidence_status: str | None = None
    evidence_event_ids: tuple[int, ...] = ()
    created_at: datetime | None = None


__all__ = ["ActivityReviewResponse", "ReviewFindingResponse", "ReviewedDimensionResponse"]

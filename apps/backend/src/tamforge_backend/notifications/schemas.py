"""Content-safe notification and status-stream read contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

PositiveId = Annotated[int, Field(gt=0)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class NotificationResponse(StrictModel):
    id: PositiveId
    notification_type: Literal[
        "feedback_ready",
        "correction_due",
        "upcoming_real_interview",
        "saturday_assessment",
        "processing_failure_requires_action",
    ]
    subject_kind: Literal[
        "activity", "correction", "interview", "study_day", "processing_status"
    ]
    subject_id: PositiveId
    created_at: datetime
    read_at: datetime | None


class NotificationPage(StrictModel):
    items: tuple[NotificationResponse, ...]
    next_cursor: PositiveId | None


class StatusEventResponse(StrictModel):
    id: PositiveId
    event_type: str
    aggregate_type: str
    aggregate_id: PositiveId
    subject_id: PositiveId
    related_id: PositiveId | None
    occurred_at: datetime


class DeliveryBatch(StrictModel):
    published_event_ids: tuple[PositiveId, ...]
    notification_ids: tuple[PositiveId, ...]


__all__ = [
    "DeliveryBatch",
    "NotificationPage",
    "NotificationResponse",
    "StatusEventResponse",
]

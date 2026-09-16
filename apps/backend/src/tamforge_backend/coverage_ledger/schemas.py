from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

CoverageStatus = Literal["completed", "in_progress", "pending", "not_assessed"]
QueueStatus = Literal["assessed", "practiced", "in_progress", "pending"]
EvidenceStatus = Literal["qualifying", "nonqualifying", "none"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CoverageItem(StrictModel):
    """One required task of the version: exactly one coverage record, one owner."""

    task_definition_id: int
    stable_id: str
    title: str
    block: str
    objective: str
    exercise_type: str | None
    status: CoverageStatus
    evidence_status: EvidenceStatus
    planned_minutes: int
    actual_minutes: int
    activity_ids: tuple[int, ...]
    evidence_event_ids: tuple[int, ...]
    last_activity_at: datetime | None


class InterviewQueueItem(StrictModel):
    """One spoken block in queue order: the question due, and whether it was practiced."""

    position: int
    task_definition_id: int
    stable_id: str
    question: str
    status: QueueStatus
    activity_ids: tuple[int, ...]
    real_interview_attempts: int
    evidence_event_ids: tuple[int, ...]


class CoverageSummary(StrictModel):
    required_items: int
    completed: int
    in_progress: int
    pending: int
    not_assessed: int
    planned_minutes: int
    actual_minutes: int
    queue_items: int
    queue_practiced: int
    next_question: str | None


class CoverageLedgerResponse(StrictModel):
    roadmap_version_id: int
    version_key: str
    summary: CoverageSummary
    items: tuple[CoverageItem, ...]
    interview_queue: tuple[InterviewQueueItem, ...]


__all__ = [
    "CoverageItem",
    "CoverageLedgerResponse",
    "CoverageStatus",
    "CoverageSummary",
    "EvidenceStatus",
    "InterviewQueueItem",
    "QueueStatus",
]

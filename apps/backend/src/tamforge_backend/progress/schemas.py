from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from ..assessments.schemas import AssessmentDayResult


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProgressSkillPoint(StrictModel):
    snapshot_date: date
    estimated_level: Decimal


class ProgressSkill(StrictModel):
    """One skill against its targets, with every estimate the ledger wrote."""

    slug: str
    name: str
    baseline: Decimal
    month_one_target: Decimal
    final_target: Decimal
    latest_level: Decimal | None
    confidence: str | None
    trend: str | None
    points: tuple[ProgressSkillPoint, ...]


class ProgressWeek(StrictModel):
    """Planned against focused minutes for one week, Monday to Sunday."""

    week_start: date
    planned_minutes: int
    focused_minutes: int
    study_days: int
    closed_days: int


class ProgressAssessment(StrictModel):
    """One reviewer verdict on a block: the average dimension score on the rubric's scale."""

    review_id: int
    activity_id: int
    task_stable_id: str
    local_date: date
    rubric_slug: str
    block: str
    average_score: Decimal
    dimension_count: int
    verdict: str
    reviewed_at: datetime


class ProgressInterview(StrictModel):
    interview_id: int
    company: str
    role: str
    stage: str
    starts_at: datetime
    status: str
    recording_count: int


class ProgressResponse(StrictModel):
    skills: tuple[ProgressSkill, ...]
    weeks: tuple[ProgressWeek, ...]
    assessments: tuple[ProgressAssessment, ...]
    assessment_days: tuple[AssessmentDayResult, ...]
    interviews: tuple[ProgressInterview, ...]


__all__ = [
    "ProgressAssessment",
    "ProgressInterview",
    "ProgressResponse",
    "ProgressSkill",
    "ProgressSkillPoint",
    "ProgressWeek",
]

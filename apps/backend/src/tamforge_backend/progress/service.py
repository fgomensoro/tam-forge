"""Progress reads only what other modules wrote: snapshots, study days, reviews, interviews."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..evidence.repository import SqlAlchemyEvidenceRepository
from ..evidence.service import EvidenceError, EvidenceQueryService
from ..learning.models import ActivityInstance, StudyDay
from ..recordings.models import Recording
from ..reviews.models import ActivityReview
from ..today.models import Interview
from .schemas import (
    ProgressAssessment,
    ProgressInterview,
    ProgressResponse,
    ProgressSkill,
    ProgressSkillPoint,
    ProgressWeek,
)

RECENT_LIMIT = 10


class ProgressUnavailable(Exception):
    """The store cannot answer right now."""


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def weekly_minutes(days: Iterable[tuple[date, int, int, str]]) -> tuple[ProgressWeek, ...]:
    """Fold study days (local_date, planned, focused, status) into Monday-based weeks."""
    weeks: dict[date, list[int]] = defaultdict(lambda: [0, 0, 0, 0])
    for local_date, planned, focused, status in days:
        bucket = weeks[week_start(local_date)]
        bucket[0] += planned
        bucket[1] += focused
        bucket[2] += 1
        bucket[3] += 1 if status == "closed" else 0
    return tuple(
        ProgressWeek(
            week_start=start,
            planned_minutes=values[0],
            focused_minutes=values[1],
            study_days=values[2],
            closed_days=values[3],
        )
        for start, values in sorted(weeks.items())
    )


def average_dimension_score(outcome: dict[str, Any]) -> tuple[Decimal, int]:
    dimensions = outcome.get("dimensions")
    if not isinstance(dimensions, list) or not dimensions:
        return Decimal("0"), 0
    scores = [Decimal(str(item.get("score", "0"))) for item in dimensions if isinstance(item, dict)]
    if not scores:
        return Decimal("0"), 0
    average = (sum(scores, Decimal("0")) / len(scores)).quantize(Decimal("0.01"))
    return average, len(scores)


class ProgressQueryService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def read(self, *, owner_id: int) -> ProgressResponse:
        try:
            skills = await self._skills(owner_id)
            weeks = await self._weeks(owner_id)
            assessments = await self._assessments(owner_id)
            interviews = await self._interviews(owner_id)
            await self._session.rollback()
        except (SQLAlchemyError, EvidenceError):
            raise ProgressUnavailable("progress is unavailable") from None
        return ProgressResponse(
            skills=skills, weeks=weeks, assessments=assessments, interviews=interviews
        )

    async def _skills(self, owner_id: int) -> tuple[ProgressSkill, ...]:
        evidence = EvidenceQueryService(SqlAlchemyEvidenceRepository(self._session))
        listed = await evidence.list_skills(owner_id=owner_id)
        skills: list[ProgressSkill] = []
        for summary in listed.items:
            series = await evidence.skill_series(owner_id=owner_id, skill_slug=summary.slug)
            latest = summary.latest_snapshot
            skills.append(
                ProgressSkill(
                    slug=summary.slug,
                    name=summary.name,
                    baseline=summary.baseline,
                    month_one_target=summary.month_one_target,
                    final_target=summary.final_target,
                    latest_level=latest.estimated_level if latest else None,
                    confidence=latest.confidence if latest else None,
                    trend=latest.trend if latest else None,
                    points=tuple(
                        ProgressSkillPoint(
                            snapshot_date=point.snapshot_date, estimated_level=point.estimated_level
                        )
                        for point in series.points
                    ),
                )
            )
        return tuple(skills)

    async def _weeks(self, owner_id: int) -> tuple[ProgressWeek, ...]:
        rows = (
            await self._session.execute(
                select(
                    StudyDay.local_date,
                    StudyDay.planned_minutes,
                    StudyDay.focused_minutes,
                    StudyDay.status,
                )
                .where(StudyDay.owner_id == owner_id)
                .order_by(StudyDay.local_date)
            )
        ).all()
        return weekly_minutes((r[0], int(r[1]), int(r[2]), str(r[3])) for r in rows)

    async def _assessments(self, owner_id: int) -> tuple[ProgressAssessment, ...]:
        rows = (
            await self._session.execute(
                select(
                    ActivityReview, ActivityInstance.task_stable_id_snapshot, StudyDay.local_date
                )
                .join(
                    ActivityInstance,
                    (ActivityInstance.owner_id == ActivityReview.owner_id)
                    & (ActivityInstance.id == ActivityReview.activity_instance_id),
                )
                .join(
                    StudyDay,
                    (StudyDay.owner_id == ActivityInstance.owner_id)
                    & (StudyDay.id == ActivityInstance.study_day_id),
                )
                .where(ActivityReview.owner_id == owner_id)
                .order_by(ActivityReview.created_at.desc(), ActivityReview.id.desc())
                .limit(RECENT_LIMIT)
            )
        ).all()
        items: list[ProgressAssessment] = []
        for review, stable_id, local_date in rows:
            average, count = average_dimension_score(review.outcome)
            items.append(
                ProgressAssessment(
                    review_id=review.id,
                    activity_id=review.activity_instance_id,
                    task_stable_id=str(stable_id),
                    local_date=local_date,
                    rubric_slug=review.rubric_slug,
                    average_score=average,
                    dimension_count=count,
                    verdict=str(review.outcome.get("verdict", "")),
                    reviewed_at=review.created_at,
                )
            )
        return tuple(items)

    async def _interviews(self, owner_id: int) -> tuple[ProgressInterview, ...]:
        recordings = (
            select(Recording.interview_id, func.count().label("count"))
            .where(Recording.owner_id == owner_id)
            .where(Recording.interview_id.is_not(None))
            .group_by(Recording.interview_id)
            .subquery()
        )
        rows = (
            await self._session.execute(
                select(Interview, func.coalesce(recordings.c.count, 0))
                .outerjoin(recordings, recordings.c.interview_id == Interview.id)
                .where(Interview.owner_id == owner_id)
                .order_by(Interview.starts_at.desc(), Interview.id.desc())
                .limit(RECENT_LIMIT)
            )
        ).all()
        return tuple(
            ProgressInterview(
                interview_id=interview.id,
                company=interview.company,
                role=interview.role,
                stage=interview.stage,
                starts_at=interview.starts_at,
                status=interview.status,
                recording_count=int(count),
            )
            for interview, count in rows
        )


__all__ = [
    "ProgressQueryService",
    "ProgressUnavailable",
    "average_dimension_score",
    "week_start",
    "weekly_minutes",
]

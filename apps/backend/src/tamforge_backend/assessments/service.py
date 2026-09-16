"""Assessment days are Saturdays in the scheme; every block on them is a contract to score.

Nothing here is written. The reviewer scores the committed attempt against the block rubric
and records evidence in timed-assessment mode, so the skill series already carries the
result; this read model gathers it per day and per contract so the app and the weekly
report show the day as Frank tracked it by hand.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..learning.models import ActivityInstance, StudyDay
from ..reviews.models import ActivityReview
from ..roadmaps.models import TaskDefinition
from .schemas import AssessmentContractResult, AssessmentDayPage, AssessmentDayResult

ASSESSMENT_BLOCK = "saturday_assessment"
COMMITTED_STATES = frozenset(
    {"output_committed", "self_review_complete", "feedback_ready", "correction_due", "completed"}
)


class AssessmentsUnavailable(Exception):
    """The store cannot answer right now."""


# The release config gives every Saturday contract one distinctive first phase; the task
# definition keeps the expanded procedure, not the contract's name, so the phase names it.
PHASE_CONTRACTS: dict[str, str] = {
    "timed_sql": "saturday_sql",
    "assessed_case": "saturday_case",
    "assessed_portfolio": "saturday_portfolio",
    "assessed_writing": "saturday_writing",
    "assessed_behavioral": "saturday_behavioral",
    "integrated_gauntlet": "saturday_gauntlet",
    "evidence_scoring": "saturday_scoring",
}


def contract_type_for(output_contract: dict[str, Any], exercise_type: str | None) -> str:
    """The Saturday contract a task follows, read from its procedure's first phase."""
    procedure = output_contract.get("procedure")
    if isinstance(procedure, list):
        for step in procedure:
            if isinstance(step, dict) and str(step.get("phase", "")) in PHASE_CONTRACTS:
                return PHASE_CONTRACTS[str(step["phase"])]
    return f"saturday_{exercise_type}" if exercise_type else "saturday_unknown"


def average_score(outcome: dict[str, Any]) -> tuple[Decimal | None, int]:
    dimensions = outcome.get("dimensions")
    if not isinstance(dimensions, list):
        return None, 0
    scores = [Decimal(str(item.get("score", "0"))) for item in dimensions if isinstance(item, dict)]
    if not scores:
        return None, 0
    return (sum(scores, Decimal("0")) / len(scores)).quantize(Decimal("0.01")), len(scores)


def summarize_day(
    day: StudyDay, contracts: tuple[AssessmentContractResult, ...]
) -> AssessmentDayResult:
    scored = [c.average_score for c in contracts if c.average_score is not None]
    average = (
        (sum(scored, Decimal("0")) / len(scored)).quantize(Decimal("0.01")) if scored else None
    )
    return AssessmentDayResult(
        study_day_id=day.id,
        local_date=day.local_date,
        day_status=day.status,
        planned_minutes=day.planned_minutes,
        focused_minutes=day.focused_minutes,
        contracts=contracts,
        scored_contracts=len(scored),
        average_score=average,
    )


class AssessmentQueryService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list(self, *, owner_id: int, limit: int = 20) -> AssessmentDayPage:
        try:
            page = await self._list(owner_id=owner_id, limit=limit)
            await self._session.rollback()
        except SQLAlchemyError:
            raise AssessmentsUnavailable("assessments are unavailable") from None
        return page

    async def _list(self, *, owner_id: int, limit: int) -> AssessmentDayPage:
        rows = (
            await self._session.execute(
                select(StudyDay, ActivityInstance, TaskDefinition)
                .join(
                    ActivityInstance,
                    (ActivityInstance.owner_id == StudyDay.owner_id)
                    & (ActivityInstance.study_day_id == StudyDay.id),
                )
                .join(
                    TaskDefinition,
                    (TaskDefinition.owner_id == ActivityInstance.owner_id)
                    & (TaskDefinition.id == ActivityInstance.task_definition_id),
                )
                .where(StudyDay.owner_id == owner_id)
                .where(TaskDefinition.block == ASSESSMENT_BLOCK)
                .order_by(StudyDay.local_date.desc(), ActivityInstance.id)
            )
        ).all()
        if not rows:
            return AssessmentDayPage(items=())
        activity_ids = [activity.id for _, activity, _ in rows]
        reviews = (
            await self._session.scalars(
                select(ActivityReview)
                .where(ActivityReview.owner_id == owner_id)
                .where(ActivityReview.activity_instance_id.in_(activity_ids))
                .order_by(ActivityReview.activity_instance_id, ActivityReview.id.desc())
            )
        ).all()
        latest_review: dict[int, ActivityReview] = {}
        for review in reviews:
            latest_review.setdefault(review.activity_instance_id, review)

        days: list[AssessmentDayResult] = []
        current: StudyDay | None = None
        contracts: list[AssessmentContractResult] = []
        for day, activity, definition in rows:
            if current is not None and day.id != current.id:
                days.append(summarize_day(current, tuple(contracts)))
                contracts = []
                if len(days) >= limit:
                    return AssessmentDayPage(items=tuple(days))
            current = day
            contracts.append(self._contract(activity, definition, latest_review.get(activity.id)))
        if current is not None:
            days.append(summarize_day(current, tuple(contracts)))
        return AssessmentDayPage(items=tuple(days[:limit]))

    @staticmethod
    def _contract(
        activity: ActivityInstance,
        definition: TaskDefinition,
        review: ActivityReview | None,
    ) -> AssessmentContractResult:
        if review is not None:
            average, count = average_score(review.outcome)
            result = "scored" if average is not None else "committed"
        else:
            average, count = None, 0
            result = "committed" if activity.state in COMMITTED_STATES else "not_attempted"
            if activity.state in {"active", "paused"}:
                result = "pending"
        return AssessmentContractResult(
            activity_id=activity.id,
            task_stable_id=definition.stable_id,
            contract_type=contract_type_for(definition.output_contract, definition.exercise_type),
            exercise_type=definition.exercise_type,
            activity_state=activity.state,
            result=result,  # type: ignore[arg-type]
            average_score=average,
            dimension_count=count,
            review_id=review.id if review else None,
            evidence_event_ids=tuple(review.evidence_event_ids) if review else (),
        )


__all__ = [
    "ASSESSMENT_BLOCK",
    "AssessmentQueryService",
    "AssessmentsUnavailable",
    "average_score",
    "contract_type_for",
    "summarize_day",
]

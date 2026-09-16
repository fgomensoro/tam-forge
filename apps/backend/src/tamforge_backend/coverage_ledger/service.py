"""Coverage is read from the version's tasks and what the ledger recorded against them.

Every required task of a roadmap version is one coverage record with one owner, as the
six-week design asks; the statuses are the ones Frank keeps by hand: `completed` once an
activity finished and evidence was recorded, `not_assessed` when it finished without any,
`in_progress` while an activity is open or committed, `pending` otherwise. Nothing is
written: evidence and attempts move the ledger the moment they exist, so there is no
bookkeeping to fall behind.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..evidence.models import SkillEvidenceEvent
from ..learning.models import ActivityInstance, ActivityTimerSession, Attempt
from ..roadmaps.models import CurriculumNode, RoadmapVersion, TaskDefinition
from .schemas import (
    CoverageItem,
    CoverageLedgerResponse,
    CoverageStatus,
    CoverageSummary,
    EvidenceStatus,
    InterviewQueueItem,
    QueueStatus,
)

INTERVIEW_BLOCK = "communication_spoken"
DONE_STATES = frozenset({"feedback_ready", "completed", "correction_due", "needs_work"})
OPEN_STATES = frozenset({"active", "paused", "output_committed", "self_review_complete"})


class CoverageError(Exception):
    """Base error safe to convert to a closed public problem response."""


class CoverageNotFound(CoverageError):
    """No such version for this owner, or no active version."""


class CoverageUnavailable(CoverageError):
    """The store cannot answer right now."""


@dataclass(frozen=True, slots=True)
class ActivityFacts:
    """What one task's activities add up to."""

    activity_ids: tuple[int, ...]
    states: tuple[str, ...]
    committed: bool
    counted_seconds: int
    evidence_event_ids: tuple[int, ...]
    qualifying: bool
    real_interview_attempts: int
    last_activity_at: datetime | None


def coverage_status(facts: ActivityFacts) -> CoverageStatus:
    if any(state in DONE_STATES for state in facts.states):
        return "completed" if facts.evidence_event_ids else "not_assessed"
    if any(state in OPEN_STATES for state in facts.states):
        return "in_progress"
    return "pending"


def evidence_status(facts: ActivityFacts) -> EvidenceStatus:
    if not facts.evidence_event_ids:
        return "none"
    return "qualifying" if facts.qualifying else "nonqualifying"


def queue_status(facts: ActivityFacts) -> QueueStatus:
    if facts.evidence_event_ids:
        return "assessed"
    if facts.committed or facts.real_interview_attempts:
        return "practiced"
    if any(state in OPEN_STATES for state in facts.states):
        return "in_progress"
    return "pending"


def summarize(
    items: Sequence[CoverageItem], queue: Sequence[InterviewQueueItem]
) -> CoverageSummary:
    counts = {status: 0 for status in ("completed", "in_progress", "pending", "not_assessed")}
    for item in items:
        counts[item.status] += 1
    next_item = next((q for q in queue if q.status in {"pending", "in_progress"}), None)
    return CoverageSummary(
        required_items=len(items),
        completed=counts["completed"],
        in_progress=counts["in_progress"],
        pending=counts["pending"],
        not_assessed=counts["not_assessed"],
        planned_minutes=sum(item.planned_minutes for item in items),
        actual_minutes=sum(item.actual_minutes for item in items),
        queue_items=len(queue),
        queue_practiced=sum(1 for q in queue if q.status in {"practiced", "assessed"}),
        next_question=next_item.question if next_item else None,
    )


class CoverageLedgerService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def read(self, *, owner_id: int, version_id: int | None = None) -> CoverageLedgerResponse:
        try:
            try:
                version = await self._version(owner_id=owner_id, version_id=version_id)
                tasks = await self._tasks(owner_id=owner_id, version_id=version.id)
                facts = await self._facts(owner_id=owner_id, task_ids=[t.id for t, _ in tasks])
                items = tuple(
                    _item(task, node, facts.get(task.id, _EMPTY))
                    for task, node in tasks
                    if task.required
                )
                queue = tuple(
                    _queue_item(position, task, facts.get(task.id, _EMPTY))
                    for position, (task, _) in enumerate(
                        [(t, n) for t, n in tasks if t.block == INTERVIEW_BLOCK], start=1
                    )
                )
                return CoverageLedgerResponse(
                    roadmap_version_id=version.id,
                    version_key=version.version_key,
                    summary=summarize(items, queue),
                    items=items,
                    interview_queue=queue,
                )
            finally:
                await self._session.rollback()
        except SQLAlchemyError:
            raise CoverageUnavailable("the coverage store is unavailable") from None

    async def _version(self, *, owner_id: int, version_id: int | None) -> RoadmapVersion:
        statement = select(RoadmapVersion).where(RoadmapVersion.owner_id == owner_id)
        if version_id is None:
            statement = statement.where(RoadmapVersion.state == "active")
        else:
            statement = statement.where(RoadmapVersion.id == version_id)
        version = await self._session.scalar(statement.order_by(RoadmapVersion.id.desc()).limit(1))
        if version is None:
            raise CoverageNotFound("no roadmap version to cover")
        return version

    async def _tasks(
        self, *, owner_id: int, version_id: int
    ) -> list[tuple[TaskDefinition, CurriculumNode]]:
        rows = (
            await self._session.execute(
                select(TaskDefinition, CurriculumNode)
                .join(
                    CurriculumNode,
                    (CurriculumNode.owner_id == TaskDefinition.owner_id)
                    & (CurriculumNode.id == TaskDefinition.curriculum_node_id),
                )
                .where(TaskDefinition.owner_id == owner_id)
                .where(TaskDefinition.roadmap_version_id == version_id)
                .order_by(CurriculumNode.ordinal, TaskDefinition.stable_id, TaskDefinition.id)
            )
        ).all()
        return [(task, node) for task, node in rows]

    async def _facts(self, *, owner_id: int, task_ids: Iterable[int]) -> dict[int, ActivityFacts]:
        ids = list(task_ids)
        if not ids:
            return {}
        activities = (
            await self._session.scalars(
                select(ActivityInstance)
                .where(ActivityInstance.owner_id == owner_id)
                .where(ActivityInstance.task_definition_id.in_(ids))
                .order_by(ActivityInstance.id)
            )
        ).all()
        if not activities:
            return {}
        activity_ids = [a.id for a in activities]
        seconds: dict[int, int] = {
            int(activity_id): int(total)
            for activity_id, total in (
                await self._session.execute(
                    select(
                        ActivityTimerSession.activity_instance_id,
                        func.coalesce(func.sum(ActivityTimerSession.counted_seconds), 0),
                    )
                    .where(ActivityTimerSession.owner_id == owner_id)
                    .where(ActivityTimerSession.activity_instance_id.in_(activity_ids))
                    .group_by(ActivityTimerSession.activity_instance_id)
                )
            ).all()
        }
        events = (
            await self._session.execute(
                select(
                    SkillEvidenceEvent.activity_instance_id,
                    SkillEvidenceEvent.id,
                    SkillEvidenceEvent.qualifying_for_level,
                )
                .where(SkillEvidenceEvent.owner_id == owner_id)
                .where(SkillEvidenceEvent.activity_instance_id.in_(activity_ids))
                .order_by(SkillEvidenceEvent.id)
            )
        ).all()
        real: dict[int, int] = {
            int(activity_id): int(total)
            for activity_id, total in (
                await self._session.execute(
                    select(Attempt.activity_instance_id, func.count())
                    .where(Attempt.owner_id == owner_id)
                    .where(Attempt.activity_instance_id.in_(activity_ids))
                    .where(Attempt.attempt_kind == "real_interview")
                    .group_by(Attempt.activity_instance_id)
                )
            ).all()
        }
        by_task: dict[int, list[ActivityInstance]] = defaultdict(list)
        for activity in activities:
            by_task[activity.task_definition_id].append(activity)
        event_ids: dict[int, list[int]] = defaultdict(list)
        qualifying: dict[int, bool] = defaultdict(bool)
        for activity_id, event_id, qualifies in events:
            event_ids[activity_id].append(int(event_id))
            qualifying[activity_id] = qualifying[activity_id] or bool(qualifies)
        facts: dict[int, ActivityFacts] = {}
        for task_id, rows in by_task.items():
            ids_for_task = tuple(a.id for a in rows)
            evidence = tuple(e for a in ids_for_task for e in event_ids.get(a, ()))
            stamps = [
                stamp
                for a in rows
                for stamp in (a.output_committed_at, a.started_at)
                if stamp is not None
            ]
            facts[task_id] = ActivityFacts(
                activity_ids=ids_for_task,
                states=tuple(a.state for a in rows),
                committed=any(a.output_committed_at is not None for a in rows),
                counted_seconds=sum(seconds.get(a, 0) for a in ids_for_task),
                evidence_event_ids=evidence,
                qualifying=any(qualifying.get(a, False) for a in ids_for_task),
                real_interview_attempts=sum(real.get(a, 0) for a in ids_for_task),
                last_activity_at=max(stamps) if stamps else None,
            )
        return facts


_EMPTY = ActivityFacts((), (), False, 0, (), False, 0, None)


def _item(task: TaskDefinition, node: CurriculumNode, facts: ActivityFacts) -> CoverageItem:
    return CoverageItem(
        task_definition_id=task.id,
        stable_id=task.stable_id,
        title=node.title,
        block=task.block,
        objective=task.objective,
        exercise_type=task.exercise_type,
        status=coverage_status(facts),
        evidence_status=evidence_status(facts),
        planned_minutes=task.timebox_minutes,
        actual_minutes=facts.counted_seconds // 60,
        activity_ids=facts.activity_ids,
        evidence_event_ids=facts.evidence_event_ids,
        last_activity_at=facts.last_activity_at,
    )


def _queue_item(position: int, task: TaskDefinition, facts: ActivityFacts) -> InterviewQueueItem:
    return InterviewQueueItem(
        position=position,
        task_definition_id=task.id,
        stable_id=task.stable_id,
        question=task.objective,
        status=queue_status(facts),
        activity_ids=facts.activity_ids,
        real_interview_attempts=facts.real_interview_attempts,
        evidence_event_ids=facts.evidence_event_ids,
    )


__all__ = [
    "ActivityFacts",
    "CoverageError",
    "CoverageLedgerService",
    "CoverageNotFound",
    "CoverageUnavailable",
    "coverage_status",
    "evidence_status",
    "queue_status",
    "summarize",
]

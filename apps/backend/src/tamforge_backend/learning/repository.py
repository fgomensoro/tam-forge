"""Transactional, idempotent creation of learner-local study days."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from ..database import transaction_scope
from ..roadmaps.models import CurriculumNode, RoadmapVersion, TaskDefinition
from ..today.models import Interview
from .models import ActivityInstance, LearnerSetting, StudyDay
from .scheduling import (
    InterviewCommitment,
    SchedulePolicyError,
    TaskTemplate,
    build_day,
    curriculum_day_number,
    local_study_context,
)


class StudyDayNotReady(SchedulePolicyError):
    """The learner or active roadmap cannot produce the requested study day."""


@dataclass(frozen=True, slots=True)
class StudyDayRecord:
    id: int
    owner_id: int
    roadmap_version_id: int
    local_date: date
    planned_minutes: int
    day_type: str
    activity_ids: tuple[int, ...]
    created: bool


class StudyDayService:
    """Create a frozen roadmap day once per owner and learner-local date."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def ensure_current_day(
        self, *, owner_id: int, at: datetime
    ) -> StudyDayRecord | None:
        if owner_id <= 0:
            raise StudyDayNotReady("owner is invalid")
        async with transaction_scope(self._session):
            setting = (
                await self._session.execute(
                    select(LearnerSetting)
                    .where(LearnerSetting.owner_id == owner_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if setting is None:
                raise StudyDayNotReady("learner settings are unavailable")
            context = local_study_context(at, setting.timezone)
            curriculum_day = curriculum_day_number(
                setting.study_start_date, context.local_date
            )
            if curriculum_day is None:
                return None
            existing = (
                await self._session.execute(
                    select(StudyDay)
                    .where(StudyDay.owner_id == owner_id)
                    .where(StudyDay.local_date == context.local_date)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if existing is not None:
                return await self._record(existing, created=False)
            if setting.active_roadmap_version_id is None:
                raise StudyDayNotReady("an active roadmap is required")
            version = (
                await self._session.execute(
                    select(RoadmapVersion)
                    .where(RoadmapVersion.owner_id == owner_id)
                    .where(RoadmapVersion.id == setting.active_roadmap_version_id)
                )
            ).scalar_one_or_none()
            if version is None or version.state != "active":
                raise StudyDayNotReady("the selected roadmap is not active")

            definitions = await self._definitions(
                owner_id=owner_id,
                version_id=version.id,
                curriculum_day=curriculum_day,
            )
            interviews = tuple(
                InterviewCommitment(id=item.id, minutes=item.expected_duration_minutes)
                for item in (
                    await self._session.execute(
                        select(Interview)
                        .where(Interview.owner_id == owner_id)
                        .where(Interview.status == "scheduled")
                        .where(Interview.starts_at >= context.start_utc)
                        .where(Interview.starts_at < context.end_utc)
                        .order_by(Interview.starts_at, Interview.id)
                    )
                ).scalars()
            )
            templates = tuple(self._template(item, ordinal) for item, ordinal in definitions)
            if not templates and not interviews:
                raise StudyDayNotReady("the active roadmap has no task for this study date")
            plan = build_day(
                context.local_date,
                curriculum_day=curriculum_day,
                tasks=templates,
                interviews=interviews,
            )
            day = StudyDay(
                owner_id=owner_id,
                roadmap_version_id=version.id,
                local_date=context.local_date,
                planned_minutes=plan.planned_minutes,
                focused_minutes=0,
                day_type=plan.day_type,
                status="planned",
                started_at=None,
                closed_at=None,
            )
            self._session.add(day)
            await self._session.flush()
            definitions_by_id = {item.id: item for item, _ in definitions}
            activities: list[ActivityInstance] = []
            for template in plan.tasks:
                definition = definitions_by_id[template.task_definition_id]
                activity = ActivityInstance(
                    owner_id=owner_id,
                    study_day_id=day.id,
                    roadmap_version_id=version.id,
                    task_definition_id=definition.id,
                    task_stable_id_snapshot=definition.stable_id,
                    task_mapping_version_snapshot=(
                        definition.mapping_version or "not-applicable"
                    ),
                    task_objective_snapshot=definition.objective,
                    task_timebox_minutes_snapshot=definition.timebox_minutes,
                    roadmap_version_key_snapshot=version.version_key,
                    state="ready",
                    attempt_kind=(
                        "no_ai_assessment"
                        if definition.block == "saturday_assessment"
                        else "none"
                    ),
                    assistance_mode="none",
                    classification="required" if definition.required else "useful",
                    timebox_minutes=definition.timebox_minutes,
                    source_hidden=False,
                    optimistic_version=1,
                    replacement_version=1,
                    replaces_activity_id=None,
                    started_at=None,
                    output_committed_at=None,
                    completed_at=None,
                )
                self._session.add(activity)
                activities.append(activity)
            await self._session.flush()
            return StudyDayRecord(
                id=day.id,
                owner_id=owner_id,
                roadmap_version_id=version.id,
                local_date=context.local_date,
                planned_minutes=day.planned_minutes,
                day_type=day.day_type,
                activity_ids=tuple(item.id for item in activities),
                created=True,
            )

    async def _definitions(
        self, *, owner_id: int, version_id: int, curriculum_day: int
    ) -> tuple[tuple[TaskDefinition, int], ...]:
        task_node = aliased(CurriculumNode, name="scheduled_task_node")
        day_node = aliased(CurriculumNode, name="scheduled_day_node")
        rows = (
            await self._session.execute(
                select(TaskDefinition, task_node.ordinal)
                .join(
                    task_node,
                    (task_node.owner_id == TaskDefinition.owner_id)
                    & (task_node.roadmap_version_id == TaskDefinition.roadmap_version_id)
                    & (task_node.id == TaskDefinition.curriculum_node_id),
                )
                .join(
                    day_node,
                    (day_node.owner_id == task_node.owner_id)
                    & (day_node.roadmap_version_id == task_node.roadmap_version_id)
                    & (day_node.id == task_node.parent_id),
                )
                .where(TaskDefinition.owner_id == owner_id)
                .where(TaskDefinition.roadmap_version_id == version_id)
                .where(day_node.kind == "day")
                .where(day_node.ordinal == curriculum_day)
                .order_by(task_node.ordinal, TaskDefinition.id)
            )
        ).all()
        return tuple((row[0], row[1]) for row in rows)

    @staticmethod
    def _template(definition: TaskDefinition, ordinal: int) -> TaskTemplate:
        return TaskTemplate(
            task_definition_id=definition.id,
            stable_id=definition.stable_id,
            mapping_version=definition.mapping_version or "not-applicable",
            objective=definition.objective,
            block=definition.block,
            order=ordinal,
            timebox_minutes=definition.timebox_minutes,
            required=definition.required,
            adaptive_priority=1 if not definition.required else None,
        )

    async def _record(self, day: StudyDay, *, created: bool) -> StudyDayRecord:
        activity_ids = tuple(
            (
                await self._session.execute(
                    select(ActivityInstance.id)
                    .where(ActivityInstance.owner_id == day.owner_id)
                    .where(ActivityInstance.study_day_id == day.id)
                    .order_by(ActivityInstance.id)
                )
            ).scalars()
        )
        return StudyDayRecord(
            id=day.id,
            owner_id=day.owner_id,
            roadmap_version_id=day.roadmap_version_id,
            local_date=day.local_date,
            planned_minutes=day.planned_minutes,
            day_type=day.day_type,
            activity_ids=activity_ids,
            created=created,
        )

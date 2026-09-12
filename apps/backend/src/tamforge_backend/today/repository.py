"""Constant-query PostgreSQL Today aggregate and atomic daily close.

`load_today` and `close_day` translate a failed session call into
`TodayUnavailable`, the Today domain error `today_problem_response` maps to the
`application/problem+json` 503 the routes declare. Nothing above them catches a
raw `SQLAlchemyError` -- `api.register_routes` installs a handler per domain
error type and none for SQLAlchemy's, and `OperationalMiddleware` re-raises --
so an untranslated dropped connection or statement timeout reached Starlette's
own server-error handling as a plain-text 500. Each guard sits outside
`transaction_scope`, so a failing commit is translated the same way a failing
statement is, and raises `from None` because the chained error carries the
rejected statement and its bound parameters.

`load_today` also materializes the current study day through
`StudyDayService.ensure_current_day`, which raises the learning domain's
`ActivityUnavailable` when its own session call fails. That error is registered
app-wide through `ActivityCommandError`, so it already produced a 503, but with
`activity_dependency_unavailable` -- another domain's problem code on a Today
response. Translating it here keeps every failure of a Today request inside the
Today domain's codes.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from ..coaching.models import CoachMessage, CoachThread
from ..database import transaction_scope
from ..learning.models import (
    ActivityArtifactLink,
    ActivityInstance,
    ActivityTimerSession,
    Attempt,
    DailyClose,
    LearnerSetting,
    SelfReview,
    StudyDay,
)
from ..learning.repository import StudyDayNotReady, StudyDayService
from ..learning.scheduling import SchemeInfo, scheme_for_version
from ..learning.service import ActivityUnavailable
from ..models.base import utc_now
from ..notifications.models import OutboxEvent
from ..roadmaps.models import CurriculumNode, RoadmapVersion, TaskDefinition
from .handoff import HandoffActivityInput, build_handoff
from .models import ActivityProcessingStatus, Correction, DailyHandoff, Interview
from .schemas import (
    DailyCloseCommand,
    DailyCloseResponse,
    DailyHandoffResponse,
    HandoffBlockResponse,
    TodayAnalysis,
    TodayBudget,
    TodayCorrection,
    TodayInterview,
    TodayReadInput,
    TodayRoadmap,
    TodaySelfReview,
    TodaySourceReference,
    TodayTaskCard,
)
from .service import TodayConflict, TodayNotReady, TodayUnavailable


class SqlAlchemyTodayRepository:
    """Build Today in a bounded number of owner-scoped queries."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._session = session
        self._clock = clock

    async def load_today(self, *, owner_id: int, local_date: date) -> TodayReadInput:
        try:
            setting = await self._session.scalar(
                select(LearnerSetting).where(LearnerSetting.owner_id == owner_id)
            )
            if setting is None or setting.active_roadmap_version_id is None:
                await self._session.rollback()
                raise TodayNotReady("learner settings and an active roadmap are required")
            start_utc, end_utc, materialize_at = self._date_boundaries(local_date, setting.timezone)
            if local_date < setting.study_start_date:
                await self._session.rollback()
                raise TodayNotReady("study date precedes the roadmap start")
            scheme = await self._scheme(
                owner_id=owner_id, version_id=setting.active_roadmap_version_id
            )
            if local_date.weekday() not in scheme.rest_weekdays:
                await self._session.rollback()
                try:
                    await StudyDayService(self._session).ensure_current_day(
                        owner_id=owner_id,
                        at=materialize_at,
                    )
                except StudyDayNotReady as exc:
                    raise TodayNotReady(str(exc)) from exc
                except ActivityUnavailable:
                    raise TodayUnavailable("today storage is unavailable") from None

            day = await self._session.scalar(
                select(StudyDay)
                .where(StudyDay.owner_id == owner_id)
                .where(StudyDay.local_date == local_date)
            )
            version_id = (
                day.roadmap_version_id if day is not None else setting.active_roadmap_version_id
            )
            version = await self._session.scalar(
                select(RoadmapVersion)
                .where(RoadmapVersion.owner_id == owner_id)
                .where(RoadmapVersion.id == version_id)
            )
            if version is None:
                await self._session.rollback()
                raise TodayNotReady("roadmap version is unavailable")

            tasks: tuple[TodayTaskCard, ...] = ()
            activity_rows: tuple[ActivityInstance, ...] = ()
            if day is not None:
                task_node = aliased(CurriculumNode, name="today_task_node")
                rows = (
                    await self._session.execute(
                        select(ActivityInstance, TaskDefinition, task_node.ordinal)
                        .join(
                            TaskDefinition,
                            (TaskDefinition.owner_id == ActivityInstance.owner_id)
                            & (
                                TaskDefinition.roadmap_version_id
                                == ActivityInstance.roadmap_version_id
                            )
                            & (TaskDefinition.id == ActivityInstance.task_definition_id),
                        )
                        .join(
                            task_node,
                            (task_node.owner_id == TaskDefinition.owner_id)
                            & (task_node.roadmap_version_id == TaskDefinition.roadmap_version_id)
                            & (task_node.id == TaskDefinition.curriculum_node_id),
                        )
                        .where(ActivityInstance.owner_id == owner_id)
                        .where(ActivityInstance.study_day_id == day.id)
                        .order_by(task_node.ordinal, ActivityInstance.id)
                    )
                ).all()
                tasks = tuple(
                    self._task_card(activity, definition, int(ordinal))
                    for activity, definition, ordinal in rows
                )
                activity_rows = tuple(row[0] for row in rows)

            correction_rows = tuple(
                (
                    await self._session.scalars(
                        select(Correction)
                        .where(Correction.owner_id == owner_id)
                        .where(Correction.status.in_(("pending", "scheduled")))
                        .where(Correction.due_date <= local_date)
                        .order_by(Correction.due_date, Correction.priority, Correction.id)
                        .limit(100)
                    )
                ).all()
            )
            corrections = tuple(
                TodayCorrection(
                    id=item.id,
                    priority=cast(Any, item.priority),
                    due_date=item.due_date,
                    instruction=item.instruction,
                    status=cast(Any, item.status),
                    attempt_b_activity_id=item.attempt_b_activity_id,
                )
                for item in correction_rows
            )
            interview_rows = tuple(
                (
                    await self._session.scalars(
                        select(Interview)
                        .where(Interview.owner_id == owner_id)
                        .where(Interview.status == "scheduled")
                        .where(Interview.starts_at >= start_utc)
                        .where(Interview.starts_at < end_utc)
                        .order_by(Interview.starts_at, Interview.id)
                    )
                ).all()
            )
            interviews = tuple(
                TodayInterview(
                    id=item.id,
                    company=item.company,
                    role=item.role,
                    stage=item.stage,
                    starts_at=item.starts_at,
                    expected_duration_minutes=item.expected_duration_minutes,
                    privacy_permission_code=cast(Any, item.privacy_permission_code),
                )
                for item in interview_rows
            )
            self_review_rows = tuple(
                (
                    await self._session.scalars(
                        select(ActivityInstance)
                        .where(ActivityInstance.owner_id == owner_id)
                        .where(ActivityInstance.state == "output_committed")
                        .order_by(ActivityInstance.output_committed_at, ActivityInstance.id)
                        .limit(100)
                    )
                ).all()
            )
            awaiting_self_reviews = tuple(
                TodaySelfReview(
                    activity_id=item.id,
                    objective=item.task_objective_snapshot,
                    output_committed_at=cast(datetime, item.output_committed_at),
                )
                for item in self_review_rows
            )
            analysis_rows = tuple(
                (
                    await self._session.scalars(
                        select(ActivityProcessingStatus)
                        .where(ActivityProcessingStatus.owner_id == owner_id)
                        .where(ActivityProcessingStatus.state.in_(("ready", "needs_attention")))
                        .order_by(
                            ActivityProcessingStatus.updated_at,
                            ActivityProcessingStatus.activity_instance_id,
                        )
                        .limit(100)
                    )
                ).all()
            )
            analyses = tuple(
                TodayAnalysis(
                    activity_id=item.activity_instance_id,
                    state=cast(Any, item.state),
                    progress_label=cast(Any, item.progress_label),
                    updated_at=item.updated_at,
                )
                for item in analysis_rows
            )
            source_updated_at = max(
                self._timestamps(
                    setting,
                    version,
                    day,
                    activities=activity_rows,
                    corrections=correction_rows,
                    interviews=interview_rows,
                    self_reviews=self_review_rows,
                    analyses=analysis_rows,
                )
            )
            roadmap_day = (local_date - setting.study_start_date).days
            source = TodayReadInput(
                local_date=local_date,
                timezone=setting.timezone,
                day_id=day.id if day is not None else None,
                day_type=cast(Any, day.day_type if day is not None else "sunday"),
                day_status=cast(Any, day.status if day is not None else "off"),
                roadmap=TodayRoadmap(
                    version_id=version.id,
                    version_key=version.version_key,
                    version_number=version.version_number,
                    month=version.month_number,
                    week=(roadmap_day // 7) + 1,
                    day=local_date.weekday() + 1,
                ),
                planned_minutes=day.planned_minutes if day is not None else 0,
                focused_minutes=day.focused_minutes if day is not None else 0,
                tasks=tasks,
                corrections=corrections,
                interviews=interviews,
                awaiting_self_reviews=awaiting_self_reviews,
                analyses=analyses,
                source_updated_at=source_updated_at,
                budget=self._budget(scheme, setting.study_start_date, local_date),
            )
            await self._session.rollback()
            return source
        except SQLAlchemyError:
            raise TodayUnavailable("the today workspace is unavailable") from None

    async def _scheme(self, *, owner_id: int, version_id: int | None) -> SchemeInfo:
        if version_id is None:
            return scheme_for_version(None)
        version = await self._session.scalar(
            select(RoadmapVersion)
            .where(RoadmapVersion.owner_id == owner_id)
            .where(RoadmapVersion.id == version_id)
        )
        if version is None:
            return scheme_for_version(None)
        return scheme_for_version(version.normalized_payload.get("scheme"))

    @staticmethod
    def _budget(scheme: SchemeInfo, study_start_date: date, local_date: date) -> TodayBudget | None:
        if scheme.is_legacy or local_date < study_start_date:
            return None
        budget = scheme.budget(scheme.day_number(study_start_date, local_date), local_date)
        return TodayBudget(
            day_type=budget.day_type,
            target_minutes=budget.target_minutes,
            acceptable_minimum=budget.acceptable_minimum,
            maximum_minutes=budget.maximum_minutes,
        )

    async def close_day(
        self,
        *,
        owner_id: int,
        local_date: date,
        command: DailyCloseCommand,
        idempotency_key: str,
    ) -> DailyCloseResponse:
        del idempotency_key
        now = self._now()
        manifest = command.evidence_manifest.model_dump(mode="json")
        try:
            async with transaction_scope(self._session):
                day = await self._session.scalar(
                    select(StudyDay)
                    .where(StudyDay.owner_id == owner_id)
                    .where(StudyDay.local_date == local_date)
                    .with_for_update()
                )
                if day is None or day.day_type == "sunday":
                    raise TodayNotReady("study day is unavailable")
                existing = await self._session.scalar(
                    select(DailyClose)
                    .where(DailyClose.owner_id == owner_id)
                    .where(DailyClose.study_day_id == day.id)
                )
                if existing is not None:
                    if not self._same_close(existing, command, manifest):
                        raise TodayConflict("study day was already closed differently")
                    return self._close_response(existing, day.status, command, replayed=True)
                if day.status not in {"planned", "in_progress"}:
                    raise TodayConflict("study day cannot be closed from its current state")
                await self._validate_evidence(
                    owner_id=owner_id,
                    study_day_id=day.id,
                    command=command,
                )
                await self._validate_corrections(
                    owner_id=owner_id,
                    local_date=local_date,
                    correction_ids=command.correction_ids,
                )
                open_timer = await self._session.scalar(
                    select(ActivityTimerSession.id)
                    .join(
                        ActivityInstance,
                        (ActivityInstance.owner_id == ActivityTimerSession.owner_id)
                        & (ActivityInstance.id == ActivityTimerSession.activity_instance_id),
                    )
                    .where(ActivityTimerSession.owner_id == owner_id)
                    .where(ActivityInstance.study_day_id == day.id)
                    .where(ActivityTimerSession.ended_at.is_(None))
                    .limit(1)
                )
                if open_timer is not None:
                    raise TodayConflict("an active study timer must be stopped before close")
                if command.unfinished_classification == "none":
                    blocker = await self._session.scalar(
                        select(ActivityInstance.id)
                        .join(
                            TaskDefinition,
                            (TaskDefinition.owner_id == ActivityInstance.owner_id)
                            & (
                                TaskDefinition.roadmap_version_id
                                == ActivityInstance.roadmap_version_id
                            )
                            & (TaskDefinition.id == ActivityInstance.task_definition_id),
                        )
                        .where(ActivityInstance.owner_id == owner_id)
                        .where(ActivityInstance.study_day_id == day.id)
                        .where(TaskDefinition.required.is_(True))
                        .where(TaskDefinition.block != "daily_close")
                        .where(
                            ActivityInstance.state.not_in(
                                (
                                    "self_review_complete",
                                    "ai_processing",
                                    "feedback_ready",
                                    "correction_due",
                                    "demonstrated",
                                    "needs_work",
                                    "incomplete",
                                    "superseded",
                                )
                            )
                        )
                        .limit(1)
                    )
                    if blocker is not None:
                        raise TodayConflict(
                            "required work must be completed or classified before close"
                        )
                if day.status == "planned":
                    day.status = "in_progress"
                    day.started_at = max(now, day.created_at)
                    await self._session.flush()
                closed_at = max(now, cast(datetime, day.started_at), day.created_at)
                day.status = (
                    "closed" if command.unfinished_classification == "none" else "incomplete"
                )
                day.closed_at = closed_at
                close = DailyClose(
                    owner_id=owner_id,
                    roadmap_version_id=day.roadmap_version_id,
                    study_day_id=day.id,
                    evidence_confirmed=True,
                    evidence_manifest=manifest,
                    strongest_output=command.strongest_output,
                    repeated_mistake=command.repeated_mistake,
                    unfinished_classification=command.unfinished_classification,
                    unfinished_requirement=command.unfinished_requirement,
                    correction_count=len(command.correction_ids),
                    closed_at=closed_at,
                )
                self._session.add(close)
                await self._session.flush()
                self._session.add(
                    await self._handoff(
                        owner_id=owner_id, day=day, close=close, command=command
                    )
                )
                self._session.add(
                    OutboxEvent(
                        owner_id=owner_id,
                        aggregate_type="study_day",
                        aggregate_id=day.id,
                        event_type=f"study_day.{day.status}",
                        payload_schema_version=1,
                        payload={
                            "schema_version": 1,
                            "subject_id": day.id,
                            "related_id": close.id,
                        },
                        occurred_at=closed_at,
                        published_at=None,
                        attempts=0,
                        idempotency_key=f"daily-close:{close.id}:{day.status}",
                    )
                )
                await self._session.flush()
                return self._close_response(close, day.status, command, replayed=False)
        except SQLAlchemyError:
            raise TodayUnavailable("the today workspace is unavailable") from None

    async def _handoff(
        self, *, owner_id: int, day: StudyDay, close: DailyClose, command: DailyCloseCommand
    ) -> DailyHandoff:
        """Derive the handoff from recorded state; the plan's words, nothing inferred."""
        rows = (
            await self._session.execute(
                select(ActivityInstance, TaskDefinition.required)
                .join(
                    TaskDefinition,
                    (TaskDefinition.owner_id == ActivityInstance.owner_id)
                    & (TaskDefinition.roadmap_version_id == ActivityInstance.roadmap_version_id)
                    & (TaskDefinition.id == ActivityInstance.task_definition_id),
                )
                .where(ActivityInstance.owner_id == owner_id)
                .where(ActivityInstance.study_day_id == day.id)
                .where(ActivityInstance.state != "superseded")
                .order_by(ActivityInstance.id)
            )
        ).all()
        activity_ids = [activity.id for activity, _ in rows]
        seconds: dict[int, int] = {}
        if activity_ids:
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
            ).all():
                seconds[int(activity_id)] = int(total or 0)
        coached: set[int] = set()
        if activity_ids:
            coached = {
                int(activity_id)
                for activity_id in (
                    await self._session.scalars(
                        select(CoachThread.activity_instance_id)
                        .join(
                            CoachMessage,
                            (CoachMessage.owner_id == CoachThread.owner_id)
                            & (CoachMessage.thread_id == CoachThread.id),
                        )
                        .where(CoachThread.owner_id == owner_id)
                        .where(CoachThread.activity_instance_id.in_(activity_ids))
                        .where(CoachMessage.speaker == "coach")
                        .distinct()
                    )
                ).all()
            }
        pending = tuple(
            int(item)
            for item in (
                await self._session.scalars(
                    select(Correction.id)
                    .where(Correction.owner_id == owner_id)
                    .where(Correction.status.in_(("pending", "scheduled")))
                    .where(Correction.due_date <= day.local_date)
                    .order_by(Correction.priority, Correction.id)
                )
            ).all()
        )
        draft = build_handoff(
            tuple(
                HandoffActivityInput(
                    activity_id=activity.id,
                    stable_id=activity.task_stable_id_snapshot,
                    objective=activity.task_objective_snapshot,
                    state=activity.state,
                    required=bool(required),
                    focused_seconds=seconds.get(activity.id, 0),
                    coached=activity.id in coached,
                )
                for activity, required in rows
            ),
            unfinished_requirement=command.unfinished_requirement,
            pending_correction_ids=pending,
        )
        return DailyHandoff(
            owner_id=owner_id,
            study_day_id=day.id,
            daily_close_id=close.id,
            local_date=day.local_date,
            day_status=day.status,
            focused_minutes=max(draft.focused_minutes, day.focused_minutes),
            next_action=draft.next_action,
            blocks=[block.as_json() for block in draft.blocks],
            gaps=list(draft.gaps),
        )

    async def load_handoff(self, *, owner_id: int, before: date) -> DailyHandoffResponse | None:
        try:
            row = await self._session.scalar(
                select(DailyHandoff)
                .where(DailyHandoff.owner_id == owner_id)
                .where(DailyHandoff.local_date < before)
                .order_by(DailyHandoff.local_date.desc(), DailyHandoff.id.desc())
                .limit(1)
            )
            # Build the response before the rollback expires the loaded row.
            response = None if row is None else handoff_response(row)
            await self._session.rollback()
        except SQLAlchemyError:
            raise TodayUnavailable("the today workspace is unavailable") from None
        return response

    @staticmethod
    def _task_card(
        activity: ActivityInstance,
        definition: TaskDefinition,
        ordinal: int,
    ) -> TodayTaskCard:
        return TodayTaskCard(
            activity_id=activity.id,
            roadmap_order=ordinal,
            stable_id=activity.task_stable_id_snapshot,
            block=cast(Any, definition.block),
            state=cast(Any, activity.state),
            objective=activity.task_objective_snapshot,
            timebox_minutes=activity.timebox_minutes,
            source_references=tuple(
                TodaySourceReference(
                    path=cast(str, item["path"]),
                    anchor=cast(str | None, item.get("heading")),
                )
                for item in definition.source_references
            ),
            required_output=SqlAlchemyTodayRepository._contract_items(definition.output_contract),
            pass_criteria=SqlAlchemyTodayRepository._contract_items(definition.pass_contract),
            allowed_ai_role=cast(Any, definition.allowed_ai_role),
            evidence_requirements=SqlAlchemyTodayRepository._contract_items(
                definition.evidence_contract
            ),
            required=definition.required,
            optimistic_version=activity.optimistic_version,
        )

    @staticmethod
    def _contract_items(payload: dict[str, Any]) -> tuple[str, ...]:
        values = payload.get("items")
        if not isinstance(values, list) or not all(
            isinstance(item, str) and item.strip() for item in values
        ):
            raise TodayNotReady("roadmap task contract is invalid")
        return tuple(values)

    @staticmethod
    def _date_boundaries(
        local_date: date, timezone_name: str
    ) -> tuple[datetime, datetime, datetime]:
        try:
            timezone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            raise TodayNotReady("learner timezone is invalid") from None
        start = datetime.combine(local_date, time.min, timezone)
        end = datetime.combine(local_date + timedelta(days=1), time.min, timezone)
        noon = datetime.combine(local_date, time(hour=12), timezone)
        return start.astimezone(UTC), end.astimezone(UTC), noon.astimezone(UTC)

    @staticmethod
    def _timestamps(
        setting: LearnerSetting,
        version: RoadmapVersion,
        day: StudyDay | None,
        *,
        activities: tuple[ActivityInstance, ...],
        corrections: tuple[Correction, ...],
        interviews: tuple[Interview, ...],
        self_reviews: tuple[ActivityInstance, ...],
        analyses: tuple[ActivityProcessingStatus, ...],
    ) -> tuple[datetime, ...]:
        values: list[datetime] = [setting.updated_at, version.created_at]
        if version.activated_at is not None:
            values.append(version.activated_at)
        if day is not None:
            values.append(day.created_at)
            values.extend(item for item in (day.started_at, day.closed_at) if item is not None)
        for activity in activities:
            values.append(activity.created_at)
            values.extend(
                item
                for item in (
                    activity.started_at,
                    activity.output_committed_at,
                    activity.completed_at,
                )
                if item is not None
            )
        values.extend(item.updated_at for item in corrections)
        values.extend(item.updated_at for item in interviews)
        values.extend(cast(datetime, item.output_committed_at) for item in self_reviews)
        values.extend(item.updated_at for item in analyses)
        return tuple(values)

    async def _validate_evidence(
        self,
        *,
        owner_id: int,
        study_day_id: int,
        command: DailyCloseCommand,
    ) -> None:
        manifest = command.evidence_manifest
        if not any(
            (
                manifest.activity_ids,
                manifest.attempt_ids,
                manifest.artifact_ids,
                manifest.self_review_ids,
            )
        ):
            raise TodayConflict("daily close requires saved evidence")
        await self._require_exact_ids(
            manifest.activity_ids,
            select(ActivityInstance.id)
            .where(ActivityInstance.owner_id == owner_id)
            .where(ActivityInstance.study_day_id == study_day_id),
        )
        await self._require_exact_ids(
            manifest.attempt_ids,
            select(Attempt.id)
            .join(
                ActivityInstance,
                (ActivityInstance.owner_id == Attempt.owner_id)
                & (ActivityInstance.id == Attempt.activity_instance_id),
            )
            .where(Attempt.owner_id == owner_id)
            .where(ActivityInstance.study_day_id == study_day_id),
        )
        await self._require_exact_ids(
            manifest.artifact_ids,
            select(ActivityArtifactLink.artifact_id)
            .join(
                ActivityInstance,
                (ActivityInstance.owner_id == ActivityArtifactLink.owner_id)
                & (ActivityInstance.id == ActivityArtifactLink.activity_instance_id),
            )
            .where(ActivityArtifactLink.owner_id == owner_id)
            .where(ActivityInstance.study_day_id == study_day_id)
            .distinct(),
        )
        await self._require_exact_ids(
            manifest.self_review_ids,
            select(SelfReview.id)
            .join(
                ActivityInstance,
                (ActivityInstance.owner_id == SelfReview.owner_id)
                & (ActivityInstance.id == SelfReview.activity_instance_id),
            )
            .where(SelfReview.owner_id == owner_id)
            .where(ActivityInstance.study_day_id == study_day_id),
        )

    async def _validate_corrections(
        self,
        *,
        owner_id: int,
        local_date: date,
        correction_ids: tuple[int, ...],
    ) -> None:
        if not correction_ids:
            return
        setting = await self._session.scalar(
            select(LearnerSetting).where(LearnerSetting.owner_id == owner_id)
        )
        scheme = await self._scheme(
            owner_id=owner_id,
            version_id=None if setting is None else setting.active_roadmap_version_id,
        )
        next_study_date = scheme.next_study_date(local_date)
        rows = set(
            (
                await self._session.scalars(
                    select(Correction.id)
                    .where(Correction.owner_id == owner_id)
                    .where(Correction.id.in_(correction_ids))
                    .where(Correction.status.in_(("pending", "scheduled")))
                    .where(Correction.due_date == next_study_date)
                )
            ).all()
        )
        if rows != set(correction_ids):
            raise TodayConflict("selected corrections are not due next study day")

    async def _require_exact_ids(self, expected: Iterable[int], query: Any) -> None:
        values = tuple(expected)
        if not values:
            return
        scoped = query.where(query.selected_columns[0].in_(values))
        rows = set((await self._session.scalars(scoped)).all())
        if rows != set(values):
            raise TodayConflict("evidence manifest contains unavailable evidence")

    @staticmethod
    def _same_close(
        existing: DailyClose,
        command: DailyCloseCommand,
        manifest: dict[str, Any],
    ) -> bool:
        return (
            existing.evidence_confirmed
            and existing.evidence_manifest == manifest
            and existing.strongest_output == command.strongest_output
            and existing.repeated_mistake == command.repeated_mistake
            and existing.unfinished_classification == command.unfinished_classification
            and existing.unfinished_requirement == command.unfinished_requirement
            and existing.correction_count == len(command.correction_ids)
        )

    @staticmethod
    def _close_response(
        close: DailyClose,
        day_status: str,
        command: DailyCloseCommand,
        *,
        replayed: bool,
    ) -> DailyCloseResponse:
        return DailyCloseResponse(
            daily_close_id=close.id,
            study_day_id=close.study_day_id,
            day_status=cast(Any, day_status),
            closed_at=close.closed_at,
            consequence=command.consequence,
            replayed=replayed,
        )

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise TodayConflict("repository clock must be timezone-aware")
        return value


__all__ = ["SqlAlchemyTodayRepository"]


def handoff_response(row: DailyHandoff) -> DailyHandoffResponse:
    return DailyHandoffResponse(
        local_date=row.local_date,
        day_status=cast(Any, row.day_status),
        focused_minutes=row.focused_minutes,
        next_action=row.next_action,
        blocks=tuple(
            HandoffBlockResponse(
                activity_id=int(cast(Any, block["activity_id"])),
                stable_id=str(block["stable_id"]),
                outcome=cast(Any, block["outcome"]),
                assistance=cast(Any, block["assistance"]),
                focused_minutes=int(cast(Any, block["focused_minutes"])),
                state=cast(Any, block["state"]),
            )
            for block in row.blocks
        ),
        gaps=tuple(str(gap) for gap in row.gaps),
    )

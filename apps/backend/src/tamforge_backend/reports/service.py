"""The weekly report job: due on Sunday evening, composed from aggregates, stored, delivered.

The week runs Monday to Sunday in the learner's timezone. A report becomes due once that
Sunday reaches 18:00 local time, and again for any earlier week that has none; the job key
is the week, so a beat never queues the same week twice. Nothing here changes the plan.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, cast
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..agents.roles.contracts import RoleContractError
from ..agents.roles.weekly_report import (
    WEEKLY_REPORT_PROMPT_VERSION,
    WeeklyReportOutcome,
    WeeklyReportRequest,
    WeeklyReportService,
    WeeklyReportUnavailable,
    WeeklySkillInput,
)
from ..assessments.service import AssessmentQueryService
from ..cards.models import CardReview
from ..classes.models import ClassAnalysis, EnglishClass
from ..coverage_ledger.service import CoverageLedgerService, CoverageNotFound
from ..database import transaction_scope
from ..evidence.repository import SqlAlchemyEvidenceRepository
from ..evidence.service import EvidenceError, EvidenceQueryService
from ..interviews.debriefs import InterviewDebriefService
from ..jobs.repository import SqlAlchemyJobRepository
from ..jobs.schemas import EnqueueJobCommand, ReferencePayload
from ..jobs.service import JobConflict, JobService
from ..learning.models import ActivityInstance, LearnerSetting, StudyDay
from ..models.base import utc_now
from ..notifications.models import BackgroundJob
from ..recordings.models import Recording
from ..speech.jobs import CLAUDE_ANALYSIS_PRIORITY
from .delivery import NullReportSender, ReportSender, render_report_text
from .models import WeeklyReport
from .schemas import (
    ReportSkillLine,
    ReportSuggestion,
    WeeklyReportPage,
    WeeklyReportResponse,
)

WEEKLY_REPORT_JOB_KIND = "claude_weekly_report"
WEEKLY_REPORT_MAX_ATTEMPTS = 3
DUE_HOUR = 18
DONE_STATES = frozenset({"feedback_ready", "completed", "correction_due", "needs_work"})


class ReportsError(Exception):
    """Base error safe to convert to a closed public problem response."""


class ReportNotFound(ReportsError):
    """No such week for this owner."""


class ReportInvalid(ReportsError):
    """The week cannot be reported on yet, or the inputs are not there."""


class ReportConflict(ReportsError):
    """The week already has its report."""


class ReportsUnavailable(ReportsError):
    """The store cannot answer right now."""


def week_start_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


def due_week(now: datetime, timezone: str) -> date | None:
    """The most recent week whose report is due: its Sunday reached 18:00 local time."""
    local = now.astimezone(ZoneInfo(timezone))
    this_week = week_start_of(local.date())
    sunday_evening = datetime.combine(this_week + timedelta(days=6), time(DUE_HOUR), local.tzinfo)
    if local >= sunday_evening:
        return this_week
    return this_week - timedelta(days=7)


def weekly_report_idempotency_key(*, owner_id: int, week_start: date) -> str:
    return f"claude-weekly-report-o{owner_id}-{week_start.isoformat()}"


class WeeklyReportQueue:
    def __init__(
        self,
        session: AsyncSession,
        *,
        analyst: WeeklyReportService,
        sender: ReportSender | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._session = session
        self._analyst = analyst
        self._sender = sender or NullReportSender()
        self._clock = clock

    # -- scheduling ---------------------------------------------------------------

    async def schedule_due(self, *, now: datetime | None = None, limit: int = 20) -> int:
        """Queue the due week for every learner who has none yet; a replay queues nothing."""
        moment = now or self._clock()
        try:
            learners = [
                (int(owner), str(zone))
                for owner, zone in (
                    await self._session.execute(
                        select(LearnerSetting.owner_id, LearnerSetting.timezone).limit(limit)
                    )
                ).all()
            ]
            await self._session.rollback()
            queued = 0
            for owner_id, zone in learners:
                week = due_week(moment, zone)
                if week is None:
                    continue
                if await self._enqueue(owner_id=owner_id, week_start=week):
                    queued += 1
            return queued
        except SQLAlchemyError:
            raise ReportsUnavailable("the report store is unavailable") from None

    async def request(self, *, owner_id: int, week_start: date | None) -> WeeklyReportResponse:
        """Queue one week now, by hand; without a date, the last complete week."""
        try:
            week = week_start or self._last_complete_week(await self._timezone(owner_id))
            if week != week_start_of(week):
                raise ReportInvalid("a week starts on a Monday")
            if week + timedelta(days=6) > self._clock().date():
                raise ReportInvalid("the week has not ended yet")
            existing = await self._session.scalar(
                select(WeeklyReport.id)
                .where(WeeklyReport.owner_id == owner_id)
                .where(WeeklyReport.week_start == week)
            )
            await self._session.rollback()
            if existing is not None:
                raise ReportConflict("this week already has its report")
            await self._enqueue(owner_id=owner_id, week_start=week)
            return await self.read(owner_id=owner_id, week_start=week)
        except SQLAlchemyError:
            raise ReportsUnavailable("the report store is unavailable") from None

    async def _enqueue(self, *, owner_id: int, week_start: date) -> bool:
        existing = await self._session.scalar(
            select(WeeklyReport.id)
            .where(WeeklyReport.owner_id == owner_id)
            .where(WeeklyReport.week_start == week_start)
        )
        await self._session.rollback()
        if existing is not None:
            return False
        try:
            result = await JobService(SqlAlchemyJobRepository(self._session)).enqueue(
                owner_id=owner_id,
                command=EnqueueJobCommand(
                    kind=WEEKLY_REPORT_JOB_KIND,
                    payload=ReferencePayload(subject_id=week_start.toordinal()),
                    priority=CLAUDE_ANALYSIS_PRIORITY,
                    available_at=self._clock(),
                    max_attempts=WEEKLY_REPORT_MAX_ATTEMPTS,
                ),
                idempotency_key=weekly_report_idempotency_key(
                    owner_id=owner_id, week_start=week_start
                ),
            )
        except JobConflict:
            return False
        return not result.replayed

    # -- processing ---------------------------------------------------------------

    async def process(self, *, owner_id: int, week_start: date) -> WeeklyReport:
        """Compose the week's report from aggregates, store it, and hand it to the channel."""
        week_end = week_start + timedelta(days=6)
        try:
            request = await self._request_for(owner_id, week_start, week_end)
            try:
                outcome = await self._analyst.compose(request)
            except WeeklyReportUnavailable as exc:
                raise ReportsUnavailable(str(exc)) from None
            except RoleContractError as exc:
                raise ReportInvalid(str(exc)) from None
            payload = outcome.model_dump(mode="json")
            span = f"{week_start.isoformat()} to {week_end.isoformat()}"
            delivery = await self._sender.send(
                owner_id=owner_id,
                subject=f"TAM Forge weekly report, {span}",
                body=render_report_text(week_start.isoformat(), week_end.isoformat(), payload),
            )
            async with transaction_scope(self._session):
                row = await self._session.scalar(
                    select(WeeklyReport)
                    .where(WeeklyReport.owner_id == owner_id)
                    .where(WeeklyReport.week_start == week_start)
                    .with_for_update()
                )
                values = {
                    "week_end": week_end,
                    "model": self._analyst.model,
                    "prompt_version": WEEKLY_REPORT_PROMPT_VERSION,
                    "inputs": _inputs_json(request),
                    "outcome": payload,
                    "delivery_status": delivery.status,
                    "delivery_detail": delivery.detail[:1000],
                    "created_at": self._clock(),
                }
                if row is None:
                    row = WeeklyReport(owner_id=owner_id, week_start=week_start, **values)
                    self._session.add(row)
                else:
                    for key, value in values.items():
                        setattr(row, key, value)
                await self._session.flush()
                return row
        except SQLAlchemyError:
            raise ReportsUnavailable("the report store is unavailable") from None

    async def _request_for(
        self, owner_id: int, week_start: date, week_end: date
    ) -> WeeklyReportRequest:
        skills = await self._skills(owner_id, week_start, week_end)
        if not skills:
            raise ReportInvalid("the skill catalog is not seeded")
        days = (
            await self._session.execute(
                select(
                    func.count(),
                    func.coalesce(func.sum(StudyDay.planned_minutes), 0),
                    func.coalesce(func.sum(StudyDay.focused_minutes), 0),
                    func.count(StudyDay.id).filter(StudyDay.status == "closed"),
                )
                .where(StudyDay.owner_id == owner_id)
                .where(StudyDay.local_date >= week_start)
                .where(StudyDay.local_date <= week_end)
            )
        ).one()
        completed = await self._session.scalar(
            select(func.count())
            .select_from(ActivityInstance)
            .join(
                StudyDay,
                (StudyDay.owner_id == ActivityInstance.owner_id)
                & (StudyDay.id == ActivityInstance.study_day_id),
            )
            .where(ActivityInstance.owner_id == owner_id)
            .where(StudyDay.local_date >= week_start)
            .where(StudyDay.local_date <= week_end)
            .where(ActivityInstance.state.in_(DONE_STATES))
        )
        cards = await self._session.scalar(
            select(func.count())
            .select_from(CardReview)
            .where(CardReview.owner_id == owner_id)
            .where(CardReview.reviewed_on >= week_start)
            .where(CardReview.reviewed_on <= week_end)
        )
        start_at = datetime.combine(week_start, time.min, UTC) - timedelta(days=1)
        end_at = datetime.combine(week_end, time.max, UTC) + timedelta(days=1)
        recordings = await self._session.scalar(
            select(func.count())
            .select_from(Recording)
            .where(Recording.owner_id == owner_id)
            .where(Recording.started_at >= start_at)
            .where(Recording.started_at <= end_at)
        )
        aggregates: dict[str, object] = {
            "study_days": int(days[0]),
            "planned_minutes": int(days[1]),
            "focused_minutes": int(days[2]),
            "closed_days": int(days[3]),
            "activities_completed": int(completed or 0),
            "cards_reviewed": int(cards or 0),
            "recordings": int(recordings or 0),
        }
        assessments = tuple(
            f"{d.local_date.isoformat()}: {d.scored_contracts}/{len(d.contracts)} contracts scored"
            + (f", average {d.average_score}" if d.average_score is not None else "")
            for d in (
                await AssessmentQueryService(self._session)._list(owner_id=owner_id, limit=8)
            ).items
            if week_start <= d.local_date <= week_end
        )
        await self._session.rollback()
        timeline = await InterviewDebriefService(self._session, debriefer=cast(Any, None)).timeline(
            owner_id=owner_id
        )
        interviews = tuple(
            f"{i.starts_at.date().isoformat()} {i.company} ({i.stage}, {i.status})"
            + (
                "; "
                + ", ".join(f"{d.slug} {d.score}" for d in i.dimensions)
                + (f"; {i.hiring_progression}" if i.hiring_progression else "")
                if i.has_debrief
                else "; not debriefed"
            )
            for i in timeline.items
            if week_start <= i.starts_at.date() <= week_end
        )
        class_rows = (
            await self._session.execute(
                select(EnglishClass, ClassAnalysis)
                .outerjoin(
                    ClassAnalysis,
                    (ClassAnalysis.owner_id == EnglishClass.owner_id)
                    & (ClassAnalysis.english_class_id == EnglishClass.id),
                )
                .where(EnglishClass.owner_id == owner_id)
                .where(EnglishClass.starts_at >= start_at)
                .where(EnglishClass.starts_at <= end_at)
                .order_by(EnglishClass.starts_at)
            )
        ).all()
        classes = tuple(
            f"{record.starts_at.date().isoformat()} with {record.teacher}"
            + (
                f": fluency {analysis.fluency_score}, vocabulary {analysis.vocabulary_score}, "
                f"{analysis.outcome.get('progress_direction', '')}"
                if analysis is not None
                else ": not analysed"
            )
            for record, analysis in class_rows
            if week_start <= record.starts_at.date() <= week_end
        )
        await self._session.rollback()
        coverage: dict[str, object] | None
        try:
            ledger = await CoverageLedgerService(self._session).read(owner_id=owner_id)
            coverage = {
                "required_items": ledger.summary.required_items,
                "completed": ledger.summary.completed,
                "in_progress": ledger.summary.in_progress,
                "pending": ledger.summary.pending,
                "not_assessed": ledger.summary.not_assessed,
                "next_interview_question": ledger.summary.next_question or "none",
            }
        except CoverageNotFound:
            coverage = None
        return WeeklyReportRequest(
            week_start=week_start,
            week_end=week_end,
            skills=skills,
            aggregates=aggregates,
            assessments=assessments,
            interviews=interviews,
            classes=classes,
            coverage=coverage,
        )

    async def _skills(
        self, owner_id: int, week_start: date, week_end: date
    ) -> tuple[WeeklySkillInput, ...]:
        evidence = EvidenceQueryService(SqlAlchemyEvidenceRepository(self._session))
        try:
            listed = await evidence.list_skills(owner_id=owner_id)
        except EvidenceError:
            return ()
        skills: list[WeeklySkillInput] = []
        for summary in listed.items:
            series = await evidence.skill_series(owner_id=owner_id, skill_slug=summary.slug)
            before = [p for p in series.points if p.snapshot_date < week_start]
            through = [p for p in series.points if p.snapshot_date <= week_end]
            start_level = before[-1].estimated_level if before else summary.baseline
            end_level = through[-1].estimated_level if through else start_level
            events = sum(1 for e in series.events if week_start <= e.occurred_at.date() <= week_end)
            skills.append(
                WeeklySkillInput(
                    slug=summary.slug,
                    name=summary.name,
                    level_at_start=str(Decimal(start_level)),
                    level_at_end=str(Decimal(end_level)),
                    events_this_week=events,
                )
            )
        await self._session.rollback()
        return tuple(skills)

    # -- reading ------------------------------------------------------------------

    async def list(self, *, owner_id: int, limit: int = 12) -> WeeklyReportPage:
        try:
            rows = (
                await self._session.scalars(
                    select(WeeklyReport)
                    .where(WeeklyReport.owner_id == owner_id)
                    .order_by(WeeklyReport.week_start.desc())
                    .limit(limit)
                )
            ).all()
            names = await self._skill_names(owner_id)
            page = WeeklyReportPage(
                items=tuple(_response(r.week_start, r, None, names) for r in rows)
            )
            await self._session.rollback()
            return page
        except SQLAlchemyError:
            raise ReportsUnavailable("the report store is unavailable") from None

    async def read(self, *, owner_id: int, week_start: date) -> WeeklyReportResponse:
        try:
            try:
                row = await self._session.scalar(
                    select(WeeklyReport)
                    .where(WeeklyReport.owner_id == owner_id)
                    .where(WeeklyReport.week_start == week_start)
                )
                job = await self._session.scalar(
                    select(BackgroundJob)
                    .where(BackgroundJob.owner_id == owner_id)
                    .where(BackgroundJob.kind == WEEKLY_REPORT_JOB_KIND)
                    .where(
                        BackgroundJob.payload["subject_id"].as_integer() == week_start.toordinal()
                    )
                    .order_by(BackgroundJob.id.desc())
                    .limit(1)
                )
                names = await self._skill_names(owner_id) if row else {}
                return _response(week_start, row, job, names)
            finally:
                await self._session.rollback()
        except SQLAlchemyError:
            raise ReportsUnavailable("the report store is unavailable") from None

    async def _skill_names(self, owner_id: int) -> dict[str, str]:
        try:
            listed = await EvidenceQueryService(
                SqlAlchemyEvidenceRepository(self._session)
            ).list_skills(owner_id=owner_id)
        except EvidenceError:
            return {}
        return {s.slug: s.name for s in listed.items}

    async def _timezone(self, owner_id: int) -> str:
        zone = await self._session.scalar(
            select(LearnerSetting.timezone).where(LearnerSetting.owner_id == owner_id)
        )
        await self._session.rollback()
        return zone or "UTC"

    def _last_complete_week(self, timezone: str) -> date:
        today = self._clock().astimezone(ZoneInfo(timezone)).date()
        return week_start_of(today) - timedelta(days=7)


def _inputs_json(request: WeeklyReportRequest) -> dict[str, Any]:
    return {
        "aggregates": dict(request.aggregates),
        "skills": [
            {
                "slug": s.slug,
                "level_at_start": s.level_at_start,
                "level_at_end": s.level_at_end,
                "events_this_week": s.events_this_week,
            }
            for s in request.skills
        ],
        "assessments": list(request.assessments),
        "interviews": list(request.interviews),
        "classes": list(request.classes),
        "coverage": dict(request.coverage) if request.coverage else None,
    }


def _status(job: BackgroundJob | None, row: WeeklyReport | None) -> str:
    if row is not None and (job is None or job.state == "succeeded"):
        return "ready"
    if job is None:
        return "not_requested"
    if job.state in {"queued", "running"}:
        return job.state
    if job.state == "succeeded":
        return "ready"
    return "needs_attention"


def _response(
    week_start: date,
    row: WeeklyReport | None,
    job: BackgroundJob | None,
    names: dict[str, str],
) -> WeeklyReportResponse:
    status = _status(job, row)
    failure = job.last_error_category if status == "needs_attention" and job else None
    if row is None:
        return WeeklyReportResponse(
            week_start=week_start,
            week_end=week_start + timedelta(days=6),
            status=cast(Any, status),
            failure_category=failure,
        )
    outcome = WeeklyReportOutcome.model_validate(row.outcome)
    return WeeklyReportResponse(
        week_start=row.week_start,
        week_end=row.week_end,
        status=cast(Any, status),
        failure_category=failure,
        report_id=row.id,
        model=row.model,
        delivery_status=cast(Any, row.delivery_status),
        delivery_detail=row.delivery_detail,
        headline=outcome.headline,
        did=outcome.did,
        learned=outcome.learned,
        improved=outcome.improved,
        skills=tuple(
            ReportSkillLine(
                skill_slug=line.skill_slug,
                skill_name=names.get(line.skill_slug, line.skill_slug),
                direction=line.direction,
                note=line.note,
            )
            for line in outcome.skills
        ),
        suggestions=tuple(
            ReportSuggestion(change=s.change, reason=s.reason, skill_slug=s.skill_slug)
            for s in outcome.suggestions
        ),
        risks=outcome.risks,
        decision_for_frank=outcome.decision_for_frank,
        created_at=row.created_at,
    )


__all__ = [
    "WEEKLY_REPORT_JOB_KIND",
    "ReportConflict",
    "ReportInvalid",
    "ReportNotFound",
    "ReportsError",
    "ReportsUnavailable",
    "WeeklyReportQueue",
    "due_week",
    "week_start_of",
    "weekly_report_idempotency_key",
]

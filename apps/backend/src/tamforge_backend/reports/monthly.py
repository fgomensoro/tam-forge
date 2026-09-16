"""The monthly report job: due on the last day of the month, every skill against its targets.

The month is the calendar month in the learner's timezone; the report becomes due once
its last day reaches 18:00 local time. The gaps are computed here from the ledger and the
configured targets, and the analyst is held to them: the largest gaps it names must be
the ones the numbers show. Nothing here changes the plan.
"""

from __future__ import annotations

import calendar
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, cast
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..agents.roles.contracts import RoleContractError
from ..agents.roles.monthly_report import (
    MONTHLY_REPORT_PROMPT_VERSION,
    MonthlyReportOutcome,
    MonthlyReportRequest,
    MonthlyReportService,
    MonthlyReportUnavailable,
    MonthlySkillInput,
)
from ..assessments.service import AssessmentQueryService
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
from ..speech.jobs import CLAUDE_ANALYSIS_PRIORITY
from .delivery import NullReportSender, ReportSender
from .models import MonthlyReport
from .schemas import MonthlyReportPage, MonthlyReportResponse, MonthlySkillTrajectory
from .service import DONE_STATES, ReportConflict, ReportInvalid, ReportsUnavailable

MONTHLY_REPORT_JOB_KIND = "claude_monthly_report"
MONTHLY_REPORT_MAX_ATTEMPTS = 3
DUE_HOUR = 18


def month_start_of(day: date) -> date:
    return day.replace(day=1)


def month_end_of(month_start: date) -> date:
    return month_start.replace(day=calendar.monthrange(month_start.year, month_start.month)[1])


def previous_month(month_start: date) -> date:
    return (month_start - timedelta(days=1)).replace(day=1)


def due_month(now: datetime, timezone: str) -> date:
    """The most recent month whose report is due: its last day reached 18:00 local time."""
    local = now.astimezone(ZoneInfo(timezone))
    this_month = month_start_of(local.date())
    last_evening = datetime.combine(month_end_of(this_month), time(DUE_HOUR), local.tzinfo)
    if local >= last_evening:
        return this_month
    return previous_month(this_month)


def monthly_report_idempotency_key(*, owner_id: int, month_start: date) -> str:
    return f"claude-monthly-report-o{owner_id}-{month_start.isoformat()}"


def render_monthly_text(month_start: str, month_end: str, outcome: dict[str, object]) -> str:
    parts = [
        f"TAM Forge monthly report, {month_start} to {month_end}",
        "",
        str(outcome.get("headline", "")),
        "",
    ]
    gaps = outcome.get("largest_gaps")
    if isinstance(gaps, list) and gaps:
        parts += ["Largest gaps first: " + ", ".join(str(g) for g in gaps), ""]
    trajectory = outcome.get("trajectory")
    if isinstance(trajectory, list):
        parts.append("Trajectory:")
        for item in trajectory:
            if isinstance(item, dict):
                parts.append(
                    f"- {item.get('skill_slug')}: {item.get('status')}; {item.get('note')}"
                )
        parts.append("")
    parts += [
        f"Coverage: {outcome.get('coverage_verdict', '')}",
        f"Exit criteria: {outcome.get('exit_criteria_verdict', '')}",
        "",
    ]
    verdict = outcome.get("recommendation", "")
    parts += [f"Recommendation ({verdict}): {outcome.get('recommendation_reasoning', '')}", ""]
    priorities = outcome.get("next_month_priorities")
    if isinstance(priorities, list) and priorities:
        parts.append("Next month:")
        parts += [f"- {p}" for p in priorities]
    return "\n".join(parts)


class MonthlyReportQueue:
    def __init__(
        self,
        session: AsyncSession,
        *,
        analyst: MonthlyReportService,
        sender: ReportSender | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._session = session
        self._analyst = analyst
        self._sender = sender or NullReportSender()
        self._clock = clock

    async def schedule_due(self, *, now: datetime | None = None, limit: int = 20) -> int:
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
                if await self._enqueue(owner_id=owner_id, month_start=due_month(moment, zone)):
                    queued += 1
            return queued
        except SQLAlchemyError:
            raise ReportsUnavailable("the report store is unavailable") from None

    async def request(self, *, owner_id: int, month_start: date | None) -> MonthlyReportResponse:
        try:
            month = month_start or previous_month(
                month_start_of(
                    self._clock().astimezone(ZoneInfo(await self._timezone(owner_id))).date()
                )
            )
            if month != month_start_of(month):
                raise ReportInvalid("a month starts on its first day")
            if month_end_of(month) > self._clock().date():
                raise ReportInvalid("the month has not ended yet")
            existing = await self._session.scalar(
                select(MonthlyReport.id)
                .where(MonthlyReport.owner_id == owner_id)
                .where(MonthlyReport.month_start == month)
            )
            await self._session.rollback()
            if existing is not None:
                raise ReportConflict("this month already has its report")
            await self._enqueue(owner_id=owner_id, month_start=month)
            return await self.read(owner_id=owner_id, month_start=month)
        except SQLAlchemyError:
            raise ReportsUnavailable("the report store is unavailable") from None

    async def _enqueue(self, *, owner_id: int, month_start: date) -> bool:
        existing = await self._session.scalar(
            select(MonthlyReport.id)
            .where(MonthlyReport.owner_id == owner_id)
            .where(MonthlyReport.month_start == month_start)
        )
        await self._session.rollback()
        if existing is not None:
            return False
        try:
            result = await JobService(SqlAlchemyJobRepository(self._session)).enqueue(
                owner_id=owner_id,
                command=EnqueueJobCommand(
                    kind=MONTHLY_REPORT_JOB_KIND,
                    payload=ReferencePayload(subject_id=month_start.toordinal()),
                    priority=CLAUDE_ANALYSIS_PRIORITY,
                    available_at=self._clock(),
                    max_attempts=MONTHLY_REPORT_MAX_ATTEMPTS,
                ),
                idempotency_key=monthly_report_idempotency_key(
                    owner_id=owner_id, month_start=month_start
                ),
            )
        except JobConflict:
            return False
        return not result.replayed

    async def process(self, *, owner_id: int, month_start: date) -> MonthlyReport:
        month_end = month_end_of(month_start)
        try:
            request = await self._request_for(owner_id, month_start, month_end)
            try:
                outcome = await self._analyst.compose(request)
            except MonthlyReportUnavailable as exc:
                raise ReportsUnavailable(str(exc)) from None
            except RoleContractError as exc:
                raise ReportInvalid(str(exc)) from None
            payload = outcome.model_dump(mode="json")
            span = f"{month_start.isoformat()} to {month_end.isoformat()}"
            delivery = await self._sender.send(
                owner_id=owner_id,
                subject=f"TAM Forge monthly report, {span}",
                body=render_monthly_text(month_start.isoformat(), month_end.isoformat(), payload),
            )
            async with transaction_scope(self._session):
                row = await self._session.scalar(
                    select(MonthlyReport)
                    .where(MonthlyReport.owner_id == owner_id)
                    .where(MonthlyReport.month_start == month_start)
                    .with_for_update()
                )
                values = {
                    "month_end": month_end,
                    "model": self._analyst.model,
                    "prompt_version": MONTHLY_REPORT_PROMPT_VERSION,
                    "inputs": _inputs_json(request),
                    "outcome": payload,
                    "delivery_status": delivery.status,
                    "delivery_detail": delivery.detail[:1000],
                    "created_at": self._clock(),
                }
                if row is None:
                    row = MonthlyReport(owner_id=owner_id, month_start=month_start, **values)
                    self._session.add(row)
                else:
                    for key, value in values.items():
                        setattr(row, key, value)
                await self._session.flush()
                return row
        except SQLAlchemyError:
            raise ReportsUnavailable("the report store is unavailable") from None

    async def _request_for(
        self, owner_id: int, month_start: date, month_end: date
    ) -> MonthlyReportRequest:
        skills = await self._skills(owner_id, month_start, month_end)
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
                .where(StudyDay.local_date >= month_start)
                .where(StudyDay.local_date <= month_end)
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
            .where(StudyDay.local_date >= month_start)
            .where(StudyDay.local_date <= month_end)
            .where(ActivityInstance.state.in_(DONE_STATES))
        )
        aggregates: dict[str, object] = {
            "study_days": int(days[0]),
            "planned_minutes": int(days[1]),
            "focused_minutes": int(days[2]),
            "closed_days": int(days[3]),
            "activities_completed": int(completed or 0),
        }
        assessments = tuple(
            f"{d.local_date.isoformat()}: {d.scored_contracts}/{len(d.contracts)} contracts scored"
            + (f", average {d.average_score}" if d.average_score is not None else "")
            for d in (
                await AssessmentQueryService(self._session)._list(owner_id=owner_id, limit=8)
            ).items
            if month_start <= d.local_date <= month_end
        )
        await self._session.rollback()
        timeline = await InterviewDebriefService(self._session, debriefer=cast(Any, None)).timeline(
            owner_id=owner_id
        )
        interviews = tuple(
            f"{i.starts_at.date().isoformat()} {i.company} ({i.stage}, {i.status})"
            + (
                "; " + ", ".join(f"{d.slug} {d.score}" for d in i.dimensions)
                if i.has_debrief
                else "; not debriefed"
            )
            for i in timeline.items
            if month_start <= i.starts_at.date() <= month_end
        )
        start_at = datetime.combine(month_start, time.min, UTC) - timedelta(days=1)
        end_at = datetime.combine(month_end, time.max, UTC) + timedelta(days=1)
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
            f"{record.starts_at.date().isoformat()}"
            + (
                f": fluency {analysis.fluency_score}, vocabulary {analysis.vocabulary_score}"
                if analysis is not None
                else ": not analysed"
            )
            for record, analysis in class_rows
            if month_start <= record.starts_at.date() <= month_end
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
                "queue_practiced": f"{ledger.summary.queue_practiced}/{ledger.summary.queue_items}",
            }
        except CoverageNotFound:
            coverage = None
        return MonthlyReportRequest(
            month_start=month_start,
            month_end=month_end,
            skills=skills,
            aggregates=aggregates,
            coverage=coverage,
            assessments=assessments,
            interviews=interviews,
            classes=classes,
        )

    async def _skills(
        self, owner_id: int, month_start: date, month_end: date
    ) -> tuple[MonthlySkillInput, ...]:
        evidence = EvidenceQueryService(SqlAlchemyEvidenceRepository(self._session))
        try:
            listed = await evidence.list_skills(owner_id=owner_id)
        except EvidenceError:
            return ()
        skills: list[MonthlySkillInput] = []
        for summary in listed.items:
            series = await evidence.skill_series(owner_id=owner_id, skill_slug=summary.slug)
            before = [p for p in series.points if p.snapshot_date < month_start]
            through = [p for p in series.points if p.snapshot_date <= month_end]
            start_level = before[-1].estimated_level if before else summary.baseline
            end_level = through[-1].estimated_level if through else start_level
            skills.append(
                MonthlySkillInput(
                    slug=summary.slug,
                    name=summary.name,
                    baseline=Decimal(summary.baseline),
                    month_one_target=Decimal(summary.month_one_target),
                    final_target=Decimal(summary.final_target),
                    level_at_start=Decimal(start_level),
                    level_at_end=Decimal(end_level),
                    events_this_month=sum(
                        1 for e in series.events if month_start <= e.occurred_at.date() <= month_end
                    ),
                )
            )
        await self._session.rollback()
        return tuple(skills)

    async def list(self, *, owner_id: int, limit: int = 12) -> MonthlyReportPage:
        try:
            names = await self._skill_names(owner_id)
            rows = (
                await self._session.scalars(
                    select(MonthlyReport)
                    .where(MonthlyReport.owner_id == owner_id)
                    .order_by(MonthlyReport.month_start.desc())
                    .limit(limit)
                )
            ).all()
            page = MonthlyReportPage(
                items=tuple(_response(r.month_start, r, None, names) for r in rows)
            )
            await self._session.rollback()
            return page
        except SQLAlchemyError:
            raise ReportsUnavailable("the report store is unavailable") from None

    async def read(self, *, owner_id: int, month_start: date) -> MonthlyReportResponse:
        try:
            try:
                names = await self._skill_names(owner_id)
                row = await self._session.scalar(
                    select(MonthlyReport)
                    .where(MonthlyReport.owner_id == owner_id)
                    .where(MonthlyReport.month_start == month_start)
                )
                job = await self._session.scalar(
                    select(BackgroundJob)
                    .where(BackgroundJob.owner_id == owner_id)
                    .where(BackgroundJob.kind == MONTHLY_REPORT_JOB_KIND)
                    .where(
                        BackgroundJob.payload["subject_id"].as_integer() == month_start.toordinal()
                    )
                    .order_by(BackgroundJob.id.desc())
                    .limit(1)
                )
                return _response(month_start, row, job, names)
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
            await self._session.rollback()
            return {}
        await self._session.rollback()
        return {s.slug: s.name for s in listed.items}

    async def _timezone(self, owner_id: int) -> str:
        zone = await self._session.scalar(
            select(LearnerSetting.timezone).where(LearnerSetting.owner_id == owner_id)
        )
        await self._session.rollback()
        return zone or "UTC"


def _inputs_json(request: MonthlyReportRequest) -> dict[str, Any]:
    return {
        "aggregates": dict(request.aggregates),
        "skills": [
            {
                "slug": s.slug,
                "baseline": str(s.baseline),
                "month_one_target": str(s.month_one_target),
                "final_target": str(s.final_target),
                "level_at_start": str(s.level_at_start),
                "level_at_end": str(s.level_at_end),
                "events_this_month": s.events_this_month,
            }
            for s in request.skills
        ],
        "coverage": dict(request.coverage) if request.coverage else None,
        "assessments": list(request.assessments),
        "interviews": list(request.interviews),
        "classes": list(request.classes),
    }


def _status(job: BackgroundJob | None, row: MonthlyReport | None) -> str:
    if row is not None:
        return "ready"
    if job is None:
        return "not_requested"
    if job.state in {"queued", "running"}:
        return job.state
    if job.state == "succeeded":
        return "ready"
    return "needs_attention"


def _response(
    month_start: date,
    row: MonthlyReport | None,
    job: BackgroundJob | None,
    names: dict[str, str],
) -> MonthlyReportResponse:
    status = _status(job, row)
    failure = job.last_error_category if status == "needs_attention" and job else None
    if row is None:
        return MonthlyReportResponse(
            month_start=month_start,
            month_end=month_end_of(month_start),
            status=cast(Any, status),
            failure_category=failure,
        )
    outcome = MonthlyReportOutcome.model_validate(row.outcome)
    inputs = {s["slug"]: s for s in row.inputs.get("skills", []) if isinstance(s, dict)}
    notes = {item.skill_slug: item for item in outcome.trajectory}

    def trajectory(slug: str) -> MonthlySkillTrajectory:
        raw = inputs.get(slug, {})
        end = Decimal(str(raw.get("level_at_end", "0")))
        item = notes[slug]
        return MonthlySkillTrajectory(
            skill_slug=slug,
            skill_name=names.get(slug, slug),
            baseline=Decimal(str(raw.get("baseline", "0"))),
            month_one_target=Decimal(str(raw.get("month_one_target", "0"))),
            final_target=Decimal(str(raw.get("final_target", "0"))),
            level_at_start=Decimal(str(raw.get("level_at_start", "0"))),
            level_at_end=end,
            gap_to_month_one=Decimal(str(raw.get("month_one_target", "0"))) - end,
            gap_to_final=Decimal(str(raw.get("final_target", "0"))) - end,
            status=item.status,
            note=item.note,
        )

    ordered = sorted(notes, key=lambda slug: (-trajectory(slug).gap_to_month_one, slug))
    return MonthlyReportResponse(
        month_start=row.month_start,
        month_end=row.month_end,
        status=cast(Any, status),
        failure_category=failure,
        report_id=row.id,
        model=row.model,
        delivery_status=cast(Any, row.delivery_status),
        delivery_detail=row.delivery_detail,
        headline=outcome.headline,
        trajectory=tuple(trajectory(slug) for slug in ordered),
        largest_gaps=outcome.largest_gaps,
        coverage_verdict=outcome.coverage_verdict,
        exit_criteria_verdict=outcome.exit_criteria_verdict,
        best_evidence=outcome.best_evidence,
        recommendation=outcome.recommendation,
        recommendation_reasoning=outcome.recommendation_reasoning,
        next_month_priorities=outcome.next_month_priorities,
        created_at=row.created_at,
    )


__all__ = [
    "MONTHLY_REPORT_JOB_KIND",
    "MonthlyReportQueue",
    "due_month",
    "month_end_of",
    "month_start_of",
    "monthly_report_idempotency_key",
    "previous_month",
    "render_monthly_text",
]

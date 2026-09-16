"""One debrief per real interview, on request, from whatever transcript the interview has."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import datetime
from typing import Any, Literal, cast

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..agents.roles.contracts import RoleContractError
from ..agents.roles.debrief import (
    DEBRIEF_PROMPT_VERSION,
    DIMENSION_MAXIMUM,
    TRACKER_DIMENSIONS,
    DebriefInterview,
    DebriefOutcome,
    DebriefRequest,
    DebriefService,
    DebriefSkill,
    DebriefUnavailable,
)
from ..database import transaction_scope
from ..evidence.config_loader import load_config_payload
from ..evidence.models import ConfigSeedVersion
from ..jobs.repository import SqlAlchemyJobRepository
from ..jobs.schemas import EnqueueJobCommand, ReferencePayload
from ..jobs.service import JobConflict, JobService
from ..models.base import utc_now
from ..notifications.models import BackgroundJob
from ..recordings.models import Recording
from ..speech.jobs import CLAUDE_ANALYSIS_PRIORITY
from ..speech.models import SpeechAnalysis
from ..today.models import Interview
from .models import InterviewDebrief, InterviewTranscript
from .schemas import (
    DebriefDimensionResponse,
    DebriefFindingResponse,
    DebriefPracticeResponse,
    DebriefSkillEffectResponse,
    DimensionTrend,
    InterviewDebriefResponse,
    InterviewTimelineItem,
    InterviewTimelineResponse,
    RecurringGap,
    TimelineDimensionScore,
    TimelineGap,
    TimelineSkillEffect,
)
from .service import (
    InterviewConflict,
    InterviewInvalid,
    InterviewNotFound,
    InterviewsUnavailable,
    ReferenceMaterialService,
)

DEBRIEF_JOB_KIND = "claude_debrief"
DEBRIEF_MAX_ATTEMPTS = 3
TranscriptSource = Literal["recording", "transcript_only"]


def debrief_idempotency_key(*, interview_id: int, transcript_sha256: str) -> str:
    return f"claude-debrief-i{interview_id}-{transcript_sha256[:16]}"


def render_turns(turns: list[dict[str, Any]], *, with_time: bool) -> str:
    lines = []
    for turn in turns:
        speaker = "Learner" if turn.get("speaker") == "learner" else "Interviewer"
        text = str(turn.get("text", "")).strip()
        if not text:
            continue
        stamp = f"[{int(turn.get('start_ms', 0))}] " if with_time else ""
        lines.append(f"{stamp}{speaker}: {text}")
    return "\n".join(lines)


class InterviewDebriefService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        debriefer: DebriefService,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._session = session
        self._debriefer = debriefer
        self._clock = clock

    async def request(self, *, owner_id: int, interview_id: int) -> InterviewDebriefResponse:
        """Queue a debrief for an interview that has a transcript; a queued one replays."""
        try:
            async with transaction_scope(self._session):
                interview = await self._interview(owner_id, interview_id, lock=True)
                transcript, _ = await self._transcript(owner_id, interview)
                if not transcript.strip():
                    raise InterviewInvalid("the interview has no transcript to debrief")
                digest = hashlib.sha256(transcript.encode("utf-8")).hexdigest()
                existing = await self._session.scalar(
                    select(InterviewDebrief)
                    .where(InterviewDebrief.owner_id == owner_id)
                    .where(InterviewDebrief.interview_id == interview_id)
                )
                if existing is not None and existing.transcript_sha256 == digest:
                    raise InterviewConflict("this transcript already has its debrief")
            # The queue owns its own transaction, so the enqueue happens after the checks.
            try:
                await JobService(SqlAlchemyJobRepository(self._session)).enqueue(
                    owner_id=owner_id,
                    command=EnqueueJobCommand(
                        kind=DEBRIEF_JOB_KIND,
                        payload=ReferencePayload(subject_id=interview_id),
                        priority=CLAUDE_ANALYSIS_PRIORITY,
                        available_at=self._clock(),
                        max_attempts=DEBRIEF_MAX_ATTEMPTS,
                    ),
                    idempotency_key=debrief_idempotency_key(
                        interview_id=interview_id, transcript_sha256=digest
                    ),
                )
            except JobConflict:
                pass
            return await self.read(owner_id=owner_id, interview_id=interview_id)
        except SQLAlchemyError:
            raise InterviewsUnavailable("the interview store is unavailable") from None

    async def process(self, *, owner_id: int, interview_id: int) -> InterviewDebrief:
        """Run the bounded debrief for a claimed job and store its outcome."""
        try:
            async with transaction_scope(self._session):
                interview = await self._interview(owner_id, interview_id, lock=True)
                transcript, source = await self._transcript(owner_id, interview)
                if not transcript.strip():
                    raise InterviewInvalid("the interview has no transcript to debrief")
                skills = await self._skills(owner_id)
                reference = await ReferenceMaterialService(self._session).citations(
                    owner_id=owner_id, text=f"{interview.company} {interview.role} interview"
                )
                request = DebriefRequest(
                    interview=DebriefInterview(
                        company=interview.company,
                        role=interview.role,
                        stage=interview.stage,
                        starts_at=interview.starts_at,
                        status=interview.status,
                    ),
                    transcript=transcript,
                    skills=skills,
                    transcript_source=source,
                    reference=reference,
                )
                try:
                    outcome = await self._debriefer.debrief(request)
                except DebriefUnavailable as exc:
                    raise InterviewsUnavailable(str(exc)) from None
                except RoleContractError as exc:
                    raise InterviewInvalid(str(exc)) from None
                row = await self._session.scalar(
                    select(InterviewDebrief)
                    .where(InterviewDebrief.owner_id == owner_id)
                    .where(InterviewDebrief.interview_id == interview_id)
                )
                digest = hashlib.sha256(transcript.encode("utf-8")).hexdigest()
                payload = outcome.model_dump(mode="json")
                if row is None:
                    row = InterviewDebrief(
                        owner_id=owner_id,
                        interview_id=interview_id,
                        transcript_source=source,
                        transcript_sha256=digest,
                        model=self._debriefer.model,
                        prompt_version=DEBRIEF_PROMPT_VERSION,
                        outcome=payload,
                        created_at=self._clock(),
                    )
                    self._session.add(row)
                else:
                    row.transcript_source = source
                    row.transcript_sha256 = digest
                    row.model = self._debriefer.model
                    row.prompt_version = DEBRIEF_PROMPT_VERSION
                    row.outcome = payload
                    row.created_at = self._clock()
                await self._session.flush()
                return row
        except SQLAlchemyError:
            raise InterviewsUnavailable("the interview store is unavailable") from None

    async def read(self, *, owner_id: int, interview_id: int) -> InterviewDebriefResponse:
        try:
            try:
                await self._interview(owner_id, interview_id, lock=False)
                row = await self._session.scalar(
                    select(InterviewDebrief)
                    .where(InterviewDebrief.owner_id == owner_id)
                    .where(InterviewDebrief.interview_id == interview_id)
                )
                job = await self._session.scalar(
                    select(BackgroundJob)
                    .where(BackgroundJob.owner_id == owner_id)
                    .where(BackgroundJob.kind == DEBRIEF_JOB_KIND)
                    .where(BackgroundJob.payload["subject_id"].as_integer() == interview_id)
                    .order_by(BackgroundJob.id.desc())
                    .limit(1)
                )
                names = {s.slug: s.name for s in await self._skills(owner_id)} if row else {}
                return _response(interview_id, row, job, names)
            finally:
                await self._session.rollback()
        except SQLAlchemyError:
            raise InterviewsUnavailable("the interview store is unavailable") from None

    async def timeline(self, *, owner_id: int) -> InterviewTimelineResponse:
        """Every interview in order with its debrief's scores, and what recurs across them."""
        try:
            try:
                rows = (
                    await self._session.execute(
                        select(Interview, InterviewDebrief)
                        .outerjoin(
                            InterviewDebrief,
                            (InterviewDebrief.owner_id == Interview.owner_id)
                            & (InterviewDebrief.interview_id == Interview.id),
                        )
                        .where(Interview.owner_id == owner_id)
                        .order_by(Interview.starts_at, Interview.id)
                        .limit(200)
                    )
                ).all()
                return build_timeline([(i, d.outcome if d else None) for i, d in rows])
            finally:
                await self._session.rollback()
        except SQLAlchemyError:
            raise InterviewsUnavailable("the interview store is unavailable") from None

    async def _interview(self, owner_id: int, interview_id: int, *, lock: bool) -> Interview:
        statement = (
            select(Interview)
            .where(Interview.owner_id == owner_id)
            .where(Interview.id == interview_id)
        )
        if lock:
            statement = statement.with_for_update()
        row = await self._session.scalar(statement)
        if row is None:
            raise InterviewNotFound("the interview was not found")
        return row

    async def _transcript(
        self, owner_id: int, interview: Interview
    ) -> tuple[str, TranscriptSource]:
        """The recordings' speaker turns when there are any, else the pasted transcript."""
        analyses = (
            await self._session.execute(
                select(SpeechAnalysis, Recording.started_at)
                .join(
                    Recording,
                    (Recording.owner_id == SpeechAnalysis.owner_id)
                    & (Recording.id == SpeechAnalysis.recording_id),
                )
                .where(SpeechAnalysis.owner_id == owner_id)
                .where(Recording.interview_id == interview.id)
                .order_by(Recording.started_at, Recording.id)
            )
        ).all()
        parts = [render_turns(a.turns, with_time=True) for a, _ in analyses]
        parts = [part for part in parts if part.strip()]
        if parts:
            return "\n\n".join(parts), "recording"
        pasted = await self._session.scalar(
            select(InterviewTranscript)
            .where(InterviewTranscript.owner_id == owner_id)
            .where(InterviewTranscript.interview_id == interview.id)
        )
        if pasted is None:
            return "", "transcript_only"
        return render_turns(pasted.turns, with_time=False), "transcript_only"

    async def _skills(self, owner_id: int) -> tuple[DebriefSkill, ...]:
        seeded = await self._session.scalar(
            select(ConfigSeedVersion)
            .where(ConfigSeedVersion.owner_id == owner_id)
            .order_by(ConfigSeedVersion.id.desc())
            .limit(1)
        )
        if seeded is None:
            raise InterviewInvalid("the skill catalog is not seeded")
        bundle = load_config_payload(seeded.canonical_payload)
        return tuple(DebriefSkill(slug=s.slug, name=s.name) for s in bundle.skills)


def build_timeline(
    rows: list[tuple[Interview, dict[str, Any] | None]],
) -> InterviewTimelineResponse:
    """Pure: the sequence, per-dimension trends, and gaps that recur across debriefs."""
    items: list[InterviewTimelineItem] = []
    per_dimension: dict[str, list[TimelineDimensionScore]] = {
        slug: [] for slug, _ in TRACKER_DIMENSIONS
    }
    gap_interviews: dict[str, set[int]] = {}
    gap_statements: dict[str, list[str]] = {}
    debriefed = 0
    for interview, payload in rows:
        outcome = DebriefOutcome.model_validate(payload) if payload else None
        if outcome is not None:
            debriefed += 1
            for d in outcome.dimensions:
                per_dimension.setdefault(d.slug, []).append(
                    TimelineDimensionScore(slug=str(interview.id), score=d.score)
                )
            for gap in outcome.gaps:
                gap_interviews.setdefault(gap.skill_slug, set()).add(interview.id)
                gap_statements.setdefault(gap.skill_slug, []).append(gap.statement)
        items.append(
            InterviewTimelineItem(
                interview_id=interview.id,
                company=interview.company,
                role=interview.role,
                stage=interview.stage,
                starts_at=interview.starts_at,
                status=interview.status,
                has_debrief=outcome is not None,
                hiring_progression=outcome.hiring_progression if outcome else None,
                dimensions=tuple(
                    TimelineDimensionScore(slug=d.slug, score=d.score) for d in outcome.dimensions
                )
                if outcome
                else (),
                skills_affected=tuple(
                    TimelineSkillEffect(skill_slug=e.skill_slug, direction=e.direction)
                    for e in outcome.skills_affected
                )
                if outcome
                else (),
                gaps=tuple(
                    TimelineGap(statement=g.statement, skill_slug=g.skill_slug)
                    for g in outcome.gaps
                )
                if outcome
                else (),
            )
        )
    names = dict(TRACKER_DIMENSIONS)
    trends = tuple(
        DimensionTrend(
            slug=slug,
            name=names.get(slug, slug),
            scores=tuple(scores),
            latest=scores[-1].score if scores else None,
            delta_from_first=(scores[-1].score - scores[0].score) if len(scores) > 1 else None,
        )
        for slug, scores in per_dimension.items()
    )
    recurring = tuple(
        RecurringGap(
            skill_slug=slug,
            interview_count=len(ids),
            statements=tuple(dict.fromkeys(gap_statements[slug]))[:3],
        )
        for slug, ids in sorted(gap_interviews.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        if len(ids) >= 2
    )
    return InterviewTimelineResponse(
        items=tuple(items), debriefed=debriefed, dimension_trends=trends, recurring_gaps=recurring
    )


def _status(job: BackgroundJob | None, row: InterviewDebrief | None) -> str:
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
    interview_id: int,
    row: InterviewDebrief | None,
    job: BackgroundJob | None,
    names: dict[str, str],
) -> InterviewDebriefResponse:
    status = _status(job, row)
    failure = job.last_error_category if status == "needs_attention" and job else None
    if row is None:
        return InterviewDebriefResponse(
            interview_id=interview_id,
            status=cast(Any, status),
            failure_category=failure,
        )
    outcome = DebriefOutcome.model_validate(row.outcome)
    return InterviewDebriefResponse(
        interview_id=interview_id,
        status=cast(Any, status),
        failure_category=failure,
        debrief_id=row.id,
        transcript_source=cast(Any, row.transcript_source),
        model=row.model,
        summary=outcome.summary,
        dimensions=tuple(
            DebriefDimensionResponse(
                slug=d.slug,
                name=dict(TRACKER_DIMENSIONS).get(d.slug, d.slug),
                score=d.score,
                maximum=DIMENSION_MAXIMUM,
                rationale=d.rationale,
            )
            for d in outcome.dimensions
        ),
        strengths=tuple(
            DebriefFindingResponse(
                statement=f.statement, evidence=f.evidence, skill_slug=f.skill_slug
            )
            for f in outcome.strengths
        ),
        gaps=tuple(
            DebriefFindingResponse(
                statement=f.statement, evidence=f.evidence, skill_slug=f.skill_slug
            )
            for f in outcome.gaps
        ),
        skills_affected=tuple(
            DebriefSkillEffectResponse(
                skill_slug=e.skill_slug,
                skill_name=names.get(e.skill_slug, e.skill_slug),
                direction=e.direction,
                evidence=e.evidence,
            )
            for e in outcome.skills_affected
        ),
        next_week_practice=tuple(
            DebriefPracticeResponse(
                description=p.description, skill_slug=p.skill_slug, minutes=p.minutes
            )
            for p in outcome.next_week_practice
        ),
        hiring_progression=outcome.hiring_progression,
        created_at=row.created_at,
    )


__all__ = [
    "DEBRIEF_JOB_KIND",
    "InterviewDebriefService",
    "build_timeline",
    "debrief_idempotency_key",
    "render_turns",
]

"""One analysis per English class, on request, from the recordings' speaker turns."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..agents.roles.class_analysis import (
    CLASS_ANALYSIS_PROMPT_VERSION,
    ClassAnalysisOutcome,
    ClassAnalysisRequest,
    ClassAnalysisService,
    ClassAnalysisUnavailable,
    ClassRecord,
    PreviousClass,
    vocabulary_metrics,
)
from ..agents.roles.contracts import RoleContractError
from ..database import transaction_scope
from ..jobs.repository import SqlAlchemyJobRepository
from ..jobs.schemas import EnqueueJobCommand, ReferencePayload
from ..jobs.service import JobConflict, JobService
from ..models.base import utc_now
from ..notifications.models import BackgroundJob
from ..recordings.models import Recording
from ..speech.jobs import CLAUDE_ANALYSIS_PRIORITY
from ..speech.models import SpeechAnalysis
from .models import ClassAnalysis, EnglishClass
from .schemas import ClassAnalysisResponse, ClassAspectResponse, ClassRecurringErrorResponse
from .service import ClassConflict, ClassesUnavailable, ClassInvalid, ClassNotFound

CLASS_ANALYSIS_JOB_KIND = "claude_class_analysis"
CLASS_ANALYSIS_MAX_ATTEMPTS = 3
PREVIOUS_CLASSES = 6


def class_analysis_idempotency_key(*, class_id: int, transcript_sha256: str) -> str:
    return f"claude-class-c{class_id}-{transcript_sha256[:16]}"


def render_turns(turns: list[dict[str, Any]]) -> str:
    lines = []
    for turn in turns:
        speaker = "Learner" if turn.get("speaker") == "learner" else "Teacher"
        text = str(turn.get("text", "")).strip()
        if text:
            lines.append(f"[{int(turn.get('start_ms', 0))}] {speaker}: {text}")
    return "\n".join(lines)


def learner_text(turns: list[dict[str, Any]]) -> str:
    return " ".join(str(t.get("text", "")) for t in turns if t.get("speaker") == "learner")


class EnglishClassAnalysisService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        analyst: ClassAnalysisService,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._session = session
        self._analyst = analyst
        self._clock = clock

    async def request(self, *, owner_id: int, class_id: int) -> ClassAnalysisResponse:
        """Queue the analysis of a class whose recording has speaker turns."""
        try:
            async with transaction_scope(self._session):
                record = await self._class(owner_id, class_id, lock=True)
                turns, _ = await self._turns(owner_id, record)
                if not turns:
                    raise ClassInvalid("the class has no transcribed recording yet")
                digest = _digest(turns)
                existing = await self._session.scalar(
                    select(ClassAnalysis)
                    .where(ClassAnalysis.owner_id == owner_id)
                    .where(ClassAnalysis.english_class_id == class_id)
                )
                if existing is not None and existing.transcript_sha256 == digest:
                    raise ClassConflict("this recording already has its analysis")
            try:
                await JobService(SqlAlchemyJobRepository(self._session)).enqueue(
                    owner_id=owner_id,
                    command=EnqueueJobCommand(
                        kind=CLASS_ANALYSIS_JOB_KIND,
                        payload=ReferencePayload(subject_id=class_id),
                        priority=CLAUDE_ANALYSIS_PRIORITY,
                        available_at=self._clock(),
                        max_attempts=CLASS_ANALYSIS_MAX_ATTEMPTS,
                    ),
                    idempotency_key=class_analysis_idempotency_key(
                        class_id=class_id, transcript_sha256=digest
                    ),
                )
            except JobConflict:
                pass
            return await self.read(owner_id=owner_id, class_id=class_id)
        except SQLAlchemyError:
            raise ClassesUnavailable("the class store is unavailable") from None

    async def process(self, *, owner_id: int, class_id: int) -> ClassAnalysis:
        """Run the bounded analysis for a claimed job and store its outcome."""
        try:
            async with transaction_scope(self._session):
                record = await self._class(owner_id, class_id, lock=True)
                turns, metrics = await self._turns(owner_id, record)
                if not turns:
                    raise ClassInvalid("the class has no transcribed recording yet")
                previous = await self._previous(owner_id, record)
                request = ClassAnalysisRequest(
                    record=ClassRecord(
                        teacher=record.teacher,
                        starts_at=record.starts_at,
                        expected_duration_minutes=record.expected_duration_minutes,
                        notes=record.notes,
                    ),
                    transcript=render_turns(turns),
                    speech_metrics=metrics,
                    vocabulary_metrics=vocabulary_metrics(learner_text(turns)),
                    previous=previous,
                )
                try:
                    outcome = await self._analyst.analyse(request)
                except ClassAnalysisUnavailable as exc:
                    raise ClassesUnavailable(str(exc)) from None
                except RoleContractError as exc:
                    raise ClassInvalid(str(exc)) from None
                row = await self._session.scalar(
                    select(ClassAnalysis)
                    .where(ClassAnalysis.owner_id == owner_id)
                    .where(ClassAnalysis.english_class_id == class_id)
                )
                values = {
                    "transcript_sha256": _digest(turns),
                    "model": self._analyst.model,
                    "prompt_version": CLASS_ANALYSIS_PROMPT_VERSION,
                    "fluency_score": outcome.fluency.score,
                    "vocabulary_score": outcome.vocabulary.score,
                    "outcome": outcome.model_dump(mode="json"),
                    "created_at": self._clock(),
                }
                if row is None:
                    row = ClassAnalysis(owner_id=owner_id, english_class_id=class_id, **values)
                    self._session.add(row)
                else:
                    for key, value in values.items():
                        setattr(row, key, value)
                await self._session.flush()
                return row
        except SQLAlchemyError:
            raise ClassesUnavailable("the class store is unavailable") from None

    async def read(self, *, owner_id: int, class_id: int) -> ClassAnalysisResponse:
        try:
            try:
                record = await self._class(owner_id, class_id, lock=False)
                row = await self._session.scalar(
                    select(ClassAnalysis)
                    .where(ClassAnalysis.owner_id == owner_id)
                    .where(ClassAnalysis.english_class_id == class_id)
                )
                job = await self._session.scalar(
                    select(BackgroundJob)
                    .where(BackgroundJob.owner_id == owner_id)
                    .where(BackgroundJob.kind == CLASS_ANALYSIS_JOB_KIND)
                    .where(BackgroundJob.payload["subject_id"].as_integer() == class_id)
                    .order_by(BackgroundJob.id.desc())
                    .limit(1)
                )
                previous = len(await self._previous(owner_id, record)) if row else 0
                return _response(class_id, row, job, previous)
            finally:
                await self._session.rollback()
        except SQLAlchemyError:
            raise ClassesUnavailable("the class store is unavailable") from None

    async def _class(self, owner_id: int, class_id: int, *, lock: bool) -> EnglishClass:
        statement = (
            select(EnglishClass)
            .where(EnglishClass.owner_id == owner_id)
            .where(EnglishClass.id == class_id)
        )
        if lock:
            statement = statement.with_for_update()
        row = await self._session.scalar(statement)
        if row is None:
            raise ClassNotFound("the class was not found")
        return row

    async def _turns(
        self, owner_id: int, record: EnglishClass
    ) -> tuple[list[dict[str, Any]], dict[str, object]]:
        """Every analysed recording of the class, in order; metrics from the first."""
        rows = (
            (
                await self._session.execute(
                    select(SpeechAnalysis)
                    .join(
                        Recording,
                        (Recording.owner_id == SpeechAnalysis.owner_id)
                        & (Recording.id == SpeechAnalysis.recording_id),
                    )
                    .where(SpeechAnalysis.owner_id == owner_id)
                    .where(Recording.english_class_id == record.id)
                    .order_by(Recording.started_at, Recording.id)
                )
            )
            .scalars()
            .all()
        )
        turns: list[dict[str, Any]] = []
        for analysis in rows:
            turns.extend(analysis.turns)
        metrics: dict[str, object] = dict(rows[0].metrics) if rows else {}
        return turns, metrics

    async def _previous(self, owner_id: int, record: EnglishClass) -> tuple[PreviousClass, ...]:
        rows = (
            await self._session.execute(
                select(ClassAnalysis, EnglishClass.starts_at)
                .join(
                    EnglishClass,
                    (EnglishClass.owner_id == ClassAnalysis.owner_id)
                    & (EnglishClass.id == ClassAnalysis.english_class_id),
                )
                .where(ClassAnalysis.owner_id == owner_id)
                .where(EnglishClass.id != record.id)
                .where(EnglishClass.starts_at < record.starts_at)
                .order_by(EnglishClass.starts_at.desc())
                .limit(PREVIOUS_CLASSES)
            )
        ).all()
        previous = [
            PreviousClass(
                starts_at=starts_at,
                fluency_score=Decimal(analysis.fluency_score),
                vocabulary_score=Decimal(analysis.vocabulary_score),
                recurring_errors=tuple(
                    str(e.get("pattern", ""))
                    for e in analysis.outcome.get("recurring_errors", [])
                    if isinstance(e, dict)
                ),
            )
            for analysis, starts_at in rows
        ]
        previous.reverse()
        return tuple(previous)


def _digest(turns: list[dict[str, Any]]) -> str:
    return hashlib.sha256(render_turns(turns).encode("utf-8")).hexdigest()


def _status(job: BackgroundJob | None, row: ClassAnalysis | None) -> str:
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
    class_id: int, row: ClassAnalysis | None, job: BackgroundJob | None, previous: int
) -> ClassAnalysisResponse:
    status = _status(job, row)
    failure = job.last_error_category if status == "needs_attention" and job else None
    if row is None:
        return ClassAnalysisResponse(
            class_id=class_id, status=cast(Any, status), failure_category=failure
        )
    outcome = ClassAnalysisOutcome.model_validate(row.outcome)
    return ClassAnalysisResponse(
        class_id=class_id,
        status=cast(Any, status),
        failure_category=failure,
        analysis_id=row.id,
        model=row.model,
        fluency=ClassAspectResponse(
            score=outcome.fluency.score,
            rationale=outcome.fluency.rationale,
            evidence=outcome.fluency.evidence,
        ),
        vocabulary=ClassAspectResponse(
            score=outcome.vocabulary.score,
            rationale=outcome.vocabulary.rationale,
            evidence=outcome.vocabulary.evidence,
        ),
        recurring_errors=tuple(
            ClassRecurringErrorResponse(
                pattern=e.pattern, example=e.example, correction=e.correction
            )
            for e in outcome.recurring_errors
        ),
        progress_direction=outcome.progress_direction,
        progress_statement=outcome.progress_statement,
        next_focus=outcome.next_focus,
        previous_classes=previous,
        created_at=row.created_at,
    )


__all__ = [
    "CLASS_ANALYSIS_JOB_KIND",
    "EnglishClassAnalysisService",
    "class_analysis_idempotency_key",
    "learner_text",
    "render_turns",
]

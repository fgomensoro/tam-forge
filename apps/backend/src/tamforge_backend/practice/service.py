"""Free-practice answers: store one per recording, queue its review, run it, read it.

The app records the answer and transcribes it on the Mac, so the transcript reaches the
server some time after the recording does. `submit` is therefore safe to call again: it
stores the answer once and queues the review as soon as the recording has speaker turns.
A practice review never moves the roadmap and is never a block's committed attempt.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..agents.roles.contracts import RoleContractError
from ..agents.roles.practice_review import (
    PRACTICE_DIMENSIONS,
    PRACTICE_REVIEW_PROMPT_VERSION,
    PracticeReviewOutcome,
    PracticeReviewRequest,
    PracticeReviewService,
    PracticeReviewUnavailable,
)
from ..database import transaction_scope
from ..interviews.models import ReferenceMaterial
from ..jobs.repository import SqlAlchemyJobRepository
from ..jobs.schemas import EnqueueJobCommand, ReferencePayload
from ..jobs.service import JobConflict, JobService
from ..models.base import utc_now
from ..notifications.models import BackgroundJob
from ..recordings.models import Recording
from ..speech.jobs import CLAUDE_ANALYSIS_PRIORITY
from ..speech.models import SpeechAnalysis
from .models import PracticeAnswer
from .schemas import (
    PracticeAnswerCommand,
    PracticeAnswerPage,
    PracticeAnswerResponse,
    PracticeDimensionResponse,
    PracticeFixResponse,
)

PRACTICE_REVIEW_JOB_KIND = "claude_practice_review"
PRACTICE_REVIEW_MAX_ATTEMPTS = 3
PRACTICE_PAGE_LIMIT = 50
_DIMENSION_NAMES = dict(PRACTICE_DIMENSIONS)


class PracticeError(Exception):
    """Base error safe to convert to a closed public problem response."""


class PracticeNotFound(PracticeError):
    pass


class PracticeInvalid(PracticeError):
    pass


class PracticeUnavailable(PracticeError):
    pass


def practice_review_idempotency_key(*, answer_id: int, transcript_sha256: str) -> str:
    return f"claude-practice-a{answer_id}-{transcript_sha256[:16]}"


def learner_answer(turns: list[dict[str, Any]]) -> str:
    """What the learner said. The interviewer's synthesized question reaches the recording
    through the system audio track, so every other speaker is left out."""
    return " ".join(
        str(turn.get("text", "")).strip()
        for turn in turns
        if turn.get("speaker") == "learner" and str(turn.get("text", "")).strip()
    )


class PracticeAnswerService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        reviewer: PracticeReviewService,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._session = session
        self._reviewer = reviewer
        self._clock = clock

    async def submit(
        self, *, owner_id: int, command: PracticeAnswerCommand
    ) -> PracticeAnswerResponse:
        """Store the answer for this recording once, and queue its review when it can run."""
        try:
            async with transaction_scope(self._session):
                recording_pk = await self._session.scalar(
                    select(Recording.id)
                    .where(Recording.owner_id == owner_id)
                    .where(Recording.client_recording_id == command.recording_id)
                )
                if recording_pk is None:
                    raise PracticeNotFound("the recording has not reached the server yet")
                row = await self._session.scalar(
                    select(PracticeAnswer)
                    .where(PracticeAnswer.owner_id == owner_id)
                    .where(PracticeAnswer.recording_id == recording_pk)
                    .with_for_update()
                )
                if row is None:
                    reference = ""
                    if command.reference_material_id is not None:
                        entry = await self._session.scalar(
                            select(ReferenceMaterial)
                            .where(ReferenceMaterial.owner_id == owner_id)
                            .where(ReferenceMaterial.id == command.reference_material_id)
                        )
                        if entry is None:
                            raise PracticeInvalid("the reference entry was not found")
                        reference = entry.body
                    row = PracticeAnswer(
                        owner_id=owner_id,
                        recording_id=recording_pk,
                        reference_material_id=command.reference_material_id,
                        question=command.question.strip(),
                        reference_answer=reference,
                        created_at=self._clock(),
                    )
                    self._session.add(row)
                    await self._session.flush()
                answer_id = row.id
                reviewed = row.outcome is not None
                answer = "" if reviewed else await self._answer_text(owner_id, recording_pk)
            if not reviewed and answer:
                try:
                    await JobService(SqlAlchemyJobRepository(self._session)).enqueue(
                        owner_id=owner_id,
                        command=EnqueueJobCommand(
                            kind=PRACTICE_REVIEW_JOB_KIND,
                            payload=ReferencePayload(subject_id=answer_id),
                            priority=CLAUDE_ANALYSIS_PRIORITY,
                            available_at=self._clock(),
                            max_attempts=PRACTICE_REVIEW_MAX_ATTEMPTS,
                        ),
                        idempotency_key=practice_review_idempotency_key(
                            answer_id=answer_id, transcript_sha256=_digest(answer)
                        ),
                    )
                except JobConflict:
                    pass
            return await self.read(owner_id=owner_id, answer_id=answer_id)
        except SQLAlchemyError:
            raise PracticeUnavailable("the practice store is unavailable") from None

    async def process(self, *, owner_id: int, answer_id: int) -> PracticeAnswer:
        """Run the bounded review for a claimed job and store its outcome."""
        try:
            async with transaction_scope(self._session):
                row = await self._session.scalar(
                    select(PracticeAnswer)
                    .where(PracticeAnswer.owner_id == owner_id)
                    .where(PracticeAnswer.id == answer_id)
                    .with_for_update()
                )
                if row is None:
                    raise PracticeNotFound("the practice answer was not found")
                answer = await self._answer_text(owner_id, row.recording_id)
                if not answer:
                    raise PracticeInvalid("the recording has no transcribed answer yet")
                metrics = await self._session.scalar(
                    select(SpeechAnalysis.metrics)
                    .where(SpeechAnalysis.owner_id == owner_id)
                    .where(SpeechAnalysis.recording_id == row.recording_id)
                )
                try:
                    outcome = await self._reviewer.review(
                        PracticeReviewRequest(
                            question=row.question,
                            answer_transcript=answer,
                            reference_answer=row.reference_answer,
                            speech_metrics=dict(metrics or {}),
                        )
                    )
                except PracticeReviewUnavailable as exc:
                    raise PracticeUnavailable(str(exc)) from None
                except RoleContractError as exc:
                    raise PracticeInvalid(str(exc)) from None
                row.outcome = outcome.model_dump(mode="json")
                row.model = self._reviewer.model
                row.prompt_version = PRACTICE_REVIEW_PROMPT_VERSION
                row.reviewed_at = self._clock()
                await self._session.flush()
                return row
        except SQLAlchemyError:
            raise PracticeUnavailable("the practice store is unavailable") from None

    async def read(self, *, owner_id: int, answer_id: int) -> PracticeAnswerResponse:
        try:
            try:
                row = await self._session.scalar(
                    select(PracticeAnswer)
                    .where(PracticeAnswer.owner_id == owner_id)
                    .where(PracticeAnswer.id == answer_id)
                )
                if row is None:
                    raise PracticeNotFound("the practice answer was not found")
                return await self._render(owner_id, row)
            finally:
                await self._session.rollback()
        except SQLAlchemyError:
            raise PracticeUnavailable("the practice store is unavailable") from None

    async def list(self, *, owner_id: int) -> PracticeAnswerPage:
        try:
            try:
                rows = (
                    await self._session.scalars(
                        select(PracticeAnswer)
                        .where(PracticeAnswer.owner_id == owner_id)
                        .order_by(PracticeAnswer.created_at.desc(), PracticeAnswer.id.desc())
                        .limit(PRACTICE_PAGE_LIMIT)
                    )
                ).all()
                return PracticeAnswerPage(
                    items=tuple([await self._render(owner_id, row) for row in rows])
                )
            finally:
                await self._session.rollback()
        except SQLAlchemyError:
            raise PracticeUnavailable("the practice store is unavailable") from None

    async def _answer_text(self, owner_id: int, recording_pk: int) -> str:
        turns = await self._session.scalar(
            select(SpeechAnalysis.turns)
            .where(SpeechAnalysis.owner_id == owner_id)
            .where(SpeechAnalysis.recording_id == recording_pk)
        )
        return learner_answer(list(turns or []))

    async def _render(self, owner_id: int, row: PracticeAnswer) -> PracticeAnswerResponse:
        client_id = await self._session.scalar(
            select(Recording.client_recording_id)
            .where(Recording.owner_id == owner_id)
            .where(Recording.id == row.recording_id)
        )
        job = await self._session.scalar(
            select(BackgroundJob)
            .where(BackgroundJob.owner_id == owner_id)
            .where(BackgroundJob.kind == PRACTICE_REVIEW_JOB_KIND)
            .where(BackgroundJob.payload["subject_id"].as_integer() == row.id)
            .order_by(BackgroundJob.id.desc())
            .limit(1)
        )
        return _response(row, cast(UUID, client_id), job)


def _digest(answer: str) -> str:
    return hashlib.sha256(answer.encode("utf-8")).hexdigest()


def _status(job: BackgroundJob | None, row: PracticeAnswer) -> str:
    if row.outcome is not None:
        return "ready"
    if job is None:
        return "awaiting_transcript"
    if job.state in {"queued", "running"}:
        return job.state
    return "needs_attention"


def _response(
    row: PracticeAnswer, client_recording_id: UUID, job: BackgroundJob | None
) -> PracticeAnswerResponse:
    status = _status(job, row)
    failure = job.last_error_category if status == "needs_attention" and job else None
    outcome = PracticeReviewOutcome.model_validate(row.outcome) if row.outcome else None
    return PracticeAnswerResponse(
        id=row.id,
        question=row.question,
        recording_id=client_recording_id,
        reference_material_id=row.reference_material_id,
        status=cast(Any, status),
        failure_category=failure,
        model=row.model,
        dimensions=tuple(
            PracticeDimensionResponse(
                slug=d.slug,
                name=_DIMENSION_NAMES.get(d.slug, d.slug),
                score=d.score,
                evidence=d.evidence,
                note=d.note,
            )
            for d in (outcome.dimensions if outcome else ())
        ),
        strengths=outcome.strengths if outcome else (),
        fixes=tuple(
            PracticeFixResponse(heard=f.heard, say_instead=f.say_instead, why=f.why)
            for f in (outcome.fixes if outcome else ())
        ),
        reference_coverage=outcome.reference_coverage if outcome else "",
        readiness=outcome.readiness if outcome else None,
        created_at=row.created_at,
        reviewed_at=row.reviewed_at,
    )


__all__ = [
    "PRACTICE_REVIEW_JOB_KIND",
    "PracticeAnswerService",
    "PracticeError",
    "PracticeInvalid",
    "PracticeNotFound",
    "PracticeUnavailable",
    "learner_answer",
    "practice_review_idempotency_key",
]

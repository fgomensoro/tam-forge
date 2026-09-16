"""Interview records: the real interviews, edited by hand, with their recordings attached."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import transaction_scope
from ..models.base import utc_now
from ..recordings.models import Recording
from ..today.models import Interview
from .models import TRANSCRIPT_ONLY, InterviewTranscript, ReferenceMaterial
from .reference import parse_reference_entries, rank_entries, render_citation
from .schemas import (
    InterviewCommand,
    InterviewPage,
    InterviewRecordingSummary,
    InterviewResponse,
    InterviewTranscriptCommand,
    InterviewTranscriptResponse,
    ReferenceEntryResponse,
    ReferenceImportCommand,
    ReferenceImportResponse,
    ReferencePage,
    TranscriptTurnResponse,
)
from .transcripts import (
    TRANSCRIPT_ANALYSIS_VERSION,
    parse_transcript_turns,
    transcript_metrics,
)


class InterviewsError(Exception):
    """Base error safe to convert to a closed public problem response."""


class InterviewNotFound(InterviewsError):
    """The owner-scoped interview or recording does not exist."""


class InterviewConflict(InterviewsError):
    """The recording already belongs to another interview."""


class InterviewsUnavailable(InterviewsError):
    """The store cannot answer right now."""


class InterviewInvalid(InterviewsError):
    """The command carries nothing usable."""


class InterviewService:
    def __init__(self, session: AsyncSession, *, clock: Callable[[], datetime] = utc_now) -> None:
        self._session = session
        self._clock = clock

    async def list(self, *, owner_id: int) -> InterviewPage:
        try:
            rows = (
                await self._session.scalars(
                    select(Interview)
                    .where(Interview.owner_id == owner_id)
                    .order_by(Interview.starts_at.desc(), Interview.id.desc())
                    .limit(200)
                )
            ).all()
            items = [await self._response(item) for item in rows]
            await self._session.rollback()
            return InterviewPage(items=tuple(items))
        except SQLAlchemyError:
            raise InterviewsUnavailable("the interview store is unavailable") from None

    async def get(self, *, owner_id: int, interview_id: int) -> InterviewResponse:
        try:
            try:
                row = await self._load(owner_id=owner_id, interview_id=interview_id, lock=False)
                return await self._response(row)
            finally:
                await self._session.rollback()
        except SQLAlchemyError:
            raise InterviewsUnavailable("the interview store is unavailable") from None

    async def create(self, *, owner_id: int, command: InterviewCommand) -> InterviewResponse:
        try:
            async with transaction_scope(self._session):
                now = self._clock()
                row = Interview(
                    owner_id=owner_id,
                    company=command.company.strip(),
                    role=command.role.strip(),
                    stage=command.stage.strip(),
                    starts_at=command.starts_at,
                    expected_duration_minutes=command.expected_duration_minutes,
                    status=command.status,
                    privacy_permission_code=command.privacy_permission_code,
                    created_at=now,
                    updated_at=now,
                )
                self._session.add(row)
                await self._session.flush()
                return await self._response(row)
        except SQLAlchemyError:
            raise InterviewsUnavailable("the interview store is unavailable") from None

    async def update(
        self, *, owner_id: int, interview_id: int, command: InterviewCommand
    ) -> InterviewResponse:
        try:
            async with transaction_scope(self._session):
                row = await self._load(owner_id=owner_id, interview_id=interview_id, lock=True)
                row.company = command.company.strip()
                row.role = command.role.strip()
                row.stage = command.stage.strip()
                row.starts_at = command.starts_at
                row.expected_duration_minutes = command.expected_duration_minutes
                row.status = command.status
                row.privacy_permission_code = command.privacy_permission_code
                row.updated_at = max(self._clock(), row.created_at)
                await self._session.flush()
                return await self._response(row)
        except SQLAlchemyError:
            raise InterviewsUnavailable("the interview store is unavailable") from None

    async def attach_recording(
        self, *, owner_id: int, interview_id: int, recording_id: UUID
    ) -> InterviewResponse:
        """Attach a recording made before or after the record existed."""
        try:
            async with transaction_scope(self._session):
                row = await self._load(owner_id=owner_id, interview_id=interview_id, lock=True)
                recording = await self._session.scalar(
                    select(Recording)
                    .where(Recording.owner_id == owner_id)
                    .where(Recording.client_recording_id == recording_id)
                    .with_for_update()
                )
                if recording is None:
                    raise InterviewNotFound("the recording was not found")
                if recording.interview_id not in (None, interview_id):
                    raise InterviewConflict("the recording belongs to another interview")
                recording.interview_id = interview_id
                row.updated_at = max(self._clock(), row.created_at)
                await self._session.flush()
                return await self._response(row)
        except SQLAlchemyError:
            raise InterviewsUnavailable("the interview store is unavailable") from None

    async def attach_transcript(
        self, *, owner_id: int, interview_id: int, command: InterviewTranscriptCommand
    ) -> InterviewTranscriptResponse:
        """Keep a pasted transcript for an interview with no audio; analyse only what it holds."""
        turns = parse_transcript_turns(command.text, command.learner_labels)
        if not turns:
            raise InterviewInvalid("the transcript has no speaker turns")
        try:
            async with transaction_scope(self._session):
                interview = await self._load(
                    owner_id=owner_id, interview_id=interview_id, lock=True
                )
                existing = await self._session.scalar(
                    select(InterviewTranscript)
                    .where(InterviewTranscript.owner_id == owner_id)
                    .where(InterviewTranscript.interview_id == interview.id)
                )
                now = self._clock()
                if existing is None:
                    existing = InterviewTranscript(
                        owner_id=owner_id,
                        interview_id=interview.id,
                        source=TRANSCRIPT_ONLY,
                        text=command.text,
                        turns=[turn.as_json() for turn in turns],
                        metrics=transcript_metrics(turns),
                        analysis_version=TRANSCRIPT_ANALYSIS_VERSION,
                        created_at=now,
                    )
                    self._session.add(existing)
                else:
                    existing.text = command.text
                    existing.turns = [turn.as_json() for turn in turns]
                    existing.metrics = transcript_metrics(turns)
                    existing.analysis_version = TRANSCRIPT_ANALYSIS_VERSION
                await self._session.flush()
                return _transcript(existing)
        except SQLAlchemyError:
            raise InterviewsUnavailable("the interview store is unavailable") from None

    async def transcript(self, *, owner_id: int, interview_id: int) -> InterviewTranscriptResponse:
        try:
            try:
                await self._load(owner_id=owner_id, interview_id=interview_id, lock=False)
                row = await self._session.scalar(
                    select(InterviewTranscript)
                    .where(InterviewTranscript.owner_id == owner_id)
                    .where(InterviewTranscript.interview_id == interview_id)
                )
                if row is None:
                    raise InterviewNotFound("the interview has no transcript")
                return _transcript(row)
            finally:
                await self._session.rollback()
        except SQLAlchemyError:
            raise InterviewsUnavailable("the interview store is unavailable") from None

    async def _load(self, *, owner_id: int, interview_id: int, lock: bool) -> Interview:
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

    async def _response(self, row: Interview) -> InterviewResponse:
        recordings = (
            await self._session.scalars(
                select(Recording)
                .where(Recording.owner_id == row.owner_id)
                .where(Recording.interview_id == row.id)
                .order_by(Recording.started_at, Recording.id)
            )
        ).all()
        has_transcript = (
            await self._session.scalar(
                select(InterviewTranscript.id)
                .where(InterviewTranscript.owner_id == row.owner_id)
                .where(InterviewTranscript.interview_id == row.id)
            )
        ) is not None
        return InterviewResponse(
            id=row.id,
            has_transcript=has_transcript,
            company=row.company,
            role=row.role,
            stage=row.stage,
            starts_at=row.starts_at,
            expected_duration_minutes=row.expected_duration_minutes,
            status=cast(Any, row.status),
            privacy_permission_code=cast(Any, row.privacy_permission_code),
            recordings=tuple(
                InterviewRecordingSummary(
                    recording_id=item.client_recording_id,
                    state=item.state,
                    started_at=item.started_at,
                    transcript_lineage_accepted=item.transcript_lineage_accepted,
                )
                for item in recordings
            ),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


__all__ = [
    "InterviewConflict",
    "InterviewNotFound",
    "InterviewService",
    "InterviewsError",
    "InterviewsUnavailable",
]


def _transcript(row: InterviewTranscript) -> InterviewTranscriptResponse:
    metrics = row.metrics
    return InterviewTranscriptResponse(
        interview_id=row.interview_id,
        analysis_kind="transcript_only",
        analysis_version=row.analysis_version,
        turns=tuple(
            TranscriptTurnResponse(
                speaker=cast(Any, item.get("speaker", "other")),
                label=str(item.get("label", "")),
                text=str(item.get("text", "")),
            )
            for item in row.turns
        ),
        learner_words=int(metrics.get("learner_words", 0)),
        other_words=int(metrics.get("other_words", 0)),
        learner_turns=int(metrics.get("learner_turns", 0)),
        other_turns=int(metrics.get("other_turns", 0)),
        learner_word_share=float(metrics.get("learner_word_share", 0.0)),
        longest_learner_turn_words=int(metrics.get("longest_learner_turn_words", 0)),
        excluded_findings=tuple(str(x) for x in metrics.get("excluded_findings", ())),
        created_at=row.created_at,
    )


class ReferenceMaterialService:
    """The answer bank and story catalog as entries the roles cite, never as evidence."""

    def __init__(self, session: AsyncSession, *, clock: Callable[[], datetime] = utc_now) -> None:
        self._session = session
        self._clock = clock

    async def import_markdown(
        self, *, owner_id: int, command: ReferenceImportCommand
    ) -> ReferenceImportResponse:
        entries = parse_reference_entries(command.markdown)
        if not entries:
            raise InterviewInvalid("the document has no entries under headings")
        try:
            async with transaction_scope(self._session):
                created = 0
                rows: list[ReferenceMaterial] = []
                for entry in entries:
                    digest = entry.content_hash
                    row = await self._session.scalar(
                        select(ReferenceMaterial)
                        .where(ReferenceMaterial.owner_id == owner_id)
                        .where(ReferenceMaterial.content_hash == digest)
                    )
                    if row is None:
                        row = ReferenceMaterial(
                            owner_id=owner_id,
                            kind=command.kind,
                            document_title=command.title,
                            heading=entry.heading,
                            body=entry.body,
                            readiness_label=entry.readiness_label,
                            readiness_verified=False,
                            content_hash=digest,
                            created_at=self._clock(),
                        )
                        self._session.add(row)
                        await self._session.flush()
                        created += 1
                    rows.append(row)
                return ReferenceImportResponse(
                    kind=command.kind,
                    created=created,
                    existing=len(rows) - created,
                    entries=tuple(_reference(row) for row in rows),
                )
        except SQLAlchemyError:
            raise InterviewsUnavailable("the reference store is unavailable") from None

    async def list(self, *, owner_id: int, kind: str | None = None) -> ReferencePage:
        try:
            statement = (
                select(ReferenceMaterial)
                .where(ReferenceMaterial.owner_id == owner_id)
                .order_by(ReferenceMaterial.kind, ReferenceMaterial.id)
                .limit(500)
            )
            if kind is not None:
                statement = statement.where(ReferenceMaterial.kind == kind)
            rows = (await self._session.scalars(statement)).all()
            page = ReferencePage(items=tuple(_reference(row) for row in rows))
            await self._session.rollback()
            return page
        except SQLAlchemyError:
            raise InterviewsUnavailable("the reference store is unavailable") from None

    async def citations(self, *, owner_id: int, text: str, limit: int = 3) -> tuple[str, ...]:
        """Citations for a prompt: the entries whose words overlap the text, labeled unverified."""
        rows = (
            await self._session.scalars(
                select(ReferenceMaterial).where(ReferenceMaterial.owner_id == owner_id).limit(500)
            )
        ).all()
        ranked = rank_entries(
            tuple((row.heading, row.body, row.readiness_label) for row in rows), text, limit
        )
        kinds = {(row.heading, row.body): row.kind for row in rows}
        return tuple(
            render_citation(heading, body, readiness, kinds.get((heading, body), "reference"))
            for heading, body, readiness in ranked
        )


def _reference(row: ReferenceMaterial) -> ReferenceEntryResponse:
    return ReferenceEntryResponse(
        id=row.id,
        kind=cast(Any, row.kind),
        document_title=row.document_title,
        heading=row.heading,
        body=row.body,
        readiness_label=row.readiness_label,
        readiness_verified=row.readiness_verified,
        created_at=row.created_at,
    )

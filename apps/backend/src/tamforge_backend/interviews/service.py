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
from .schemas import (
    InterviewCommand,
    InterviewPage,
    InterviewRecordingSummary,
    InterviewResponse,
)


class InterviewsError(Exception):
    """Base error safe to convert to a closed public problem response."""


class InterviewNotFound(InterviewsError):
    """The owner-scoped interview or recording does not exist."""


class InterviewConflict(InterviewsError):
    """The recording already belongs to another interview."""


class InterviewsUnavailable(InterviewsError):
    """The store cannot answer right now."""


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
        return InterviewResponse(
            id=row.id,
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

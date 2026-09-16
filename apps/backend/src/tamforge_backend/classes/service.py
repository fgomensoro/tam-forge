"""English class sessions: kept by hand, recorded, and always mapped to TAM English."""

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
from .models import ENGLISH_SKILL_SLUG, EnglishClass
from .schemas import (
    ClassRecordingSummary,
    EnglishClassCommand,
    EnglishClassPage,
    EnglishClassResponse,
)


class ClassesError(Exception):
    """Base error safe to convert to a closed public problem response."""


class ClassNotFound(ClassesError):
    """The owner-scoped class or recording does not exist."""


class ClassConflict(ClassesError):
    """The recording already belongs to another class."""


class ClassesUnavailable(ClassesError):
    """The store cannot answer right now."""


class EnglishClassService:
    def __init__(self, session: AsyncSession, *, clock: Callable[[], datetime] = utc_now) -> None:
        self._session = session
        self._clock = clock

    async def list(self, *, owner_id: int) -> EnglishClassPage:
        try:
            rows = (
                await self._session.scalars(
                    select(EnglishClass)
                    .where(EnglishClass.owner_id == owner_id)
                    .order_by(EnglishClass.starts_at.desc(), EnglishClass.id.desc())
                    .limit(200)
                )
            ).all()
            items = [await self._response(item) for item in rows]
            await self._session.rollback()
            return EnglishClassPage(items=tuple(items))
        except SQLAlchemyError:
            raise ClassesUnavailable("the class store is unavailable") from None

    async def get(self, *, owner_id: int, class_id: int) -> EnglishClassResponse:
        try:
            try:
                return await self._response(
                    await self._load(owner_id=owner_id, class_id=class_id, lock=False)
                )
            finally:
                await self._session.rollback()
        except SQLAlchemyError:
            raise ClassesUnavailable("the class store is unavailable") from None

    async def create(self, *, owner_id: int, command: EnglishClassCommand) -> EnglishClassResponse:
        try:
            async with transaction_scope(self._session):
                now = self._clock()
                row = EnglishClass(
                    owner_id=owner_id,
                    teacher=command.teacher.strip(),
                    starts_at=command.starts_at,
                    expected_duration_minutes=command.expected_duration_minutes,
                    notes=command.notes,
                    skill_slug=ENGLISH_SKILL_SLUG,
                    created_at=now,
                    updated_at=now,
                )
                self._session.add(row)
                await self._session.flush()
                return await self._response(row)
        except SQLAlchemyError:
            raise ClassesUnavailable("the class store is unavailable") from None

    async def update(
        self, *, owner_id: int, class_id: int, command: EnglishClassCommand
    ) -> EnglishClassResponse:
        try:
            async with transaction_scope(self._session):
                row = await self._load(owner_id=owner_id, class_id=class_id, lock=True)
                row.teacher = command.teacher.strip()
                row.starts_at = command.starts_at
                row.expected_duration_minutes = command.expected_duration_minutes
                row.notes = command.notes
                row.updated_at = max(self._clock(), row.created_at)
                await self._session.flush()
                return await self._response(row)
        except SQLAlchemyError:
            raise ClassesUnavailable("the class store is unavailable") from None

    async def attach_recording(
        self, *, owner_id: int, class_id: int, recording_id: UUID
    ) -> EnglishClassResponse:
        try:
            async with transaction_scope(self._session):
                row = await self._load(owner_id=owner_id, class_id=class_id, lock=True)
                recording = await self._session.scalar(
                    select(Recording)
                    .where(Recording.owner_id == owner_id)
                    .where(Recording.client_recording_id == recording_id)
                    .with_for_update()
                )
                if recording is None:
                    raise ClassNotFound("the recording was not found")
                if recording.english_class_id not in (None, class_id):
                    raise ClassConflict("the recording belongs to another class")
                recording.english_class_id = class_id
                row.updated_at = max(self._clock(), row.created_at)
                await self._session.flush()
                return await self._response(row)
        except SQLAlchemyError:
            raise ClassesUnavailable("the class store is unavailable") from None

    async def _load(self, *, owner_id: int, class_id: int, lock: bool) -> EnglishClass:
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

    async def _response(self, row: EnglishClass) -> EnglishClassResponse:
        recordings = (
            await self._session.scalars(
                select(Recording)
                .where(Recording.owner_id == row.owner_id)
                .where(Recording.english_class_id == row.id)
                .order_by(Recording.started_at, Recording.id)
            )
        ).all()
        return EnglishClassResponse(
            id=row.id,
            teacher=row.teacher,
            starts_at=row.starts_at,
            expected_duration_minutes=row.expected_duration_minutes,
            notes=row.notes,
            skill_slug=cast(Any, row.skill_slug),
            recordings=tuple(
                ClassRecordingSummary(
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
    "ClassConflict",
    "ClassNotFound",
    "ClassesError",
    "ClassesUnavailable",
    "EnglishClassService",
]

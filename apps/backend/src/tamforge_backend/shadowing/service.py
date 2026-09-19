"""Shadowing clips: owner-scoped rows whose excerpt lives in the object store."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import transaction_scope
from ..models.base import utc_now
from ..storage.ports import ObjectStore
from .models import ShadowingClip
from .schemas import (
    ShadowingAnnotation,
    ShadowingClipCommand,
    ShadowingClipPage,
    ShadowingClipResponse,
    ShadowingExcerptResponse,
    ShadowingPhrase,
)

LIST_LIMIT = 500


class ShadowingError(Exception):
    """Base error safe to convert to a closed public problem response."""


class ShadowingNotFound(ShadowingError):
    """The owner-scoped clip, or its excerpt, does not exist."""


class ShadowingInvalid(ShadowingError):
    """The command names something that is not there or is out of bounds."""


class ShadowingConflict(ShadowingError):
    """The clip already has an excerpt; excerpts are write-once."""


class ShadowingUnavailable(ShadowingError):
    """The database or the object store cannot answer right now."""


class ShadowingClipService:
    def __init__(
        self,
        session: AsyncSession,
        object_store: ObjectStore,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._session = session
        self._objects = object_store
        self._clock = clock

    async def create(
        self, *, owner_id: int, command: ShadowingClipCommand
    ) -> ShadowingClipResponse:
        try:
            async with transaction_scope(self._session):
                now = self._clock()
                row = ShadowingClip(
                    owner_id=owner_id,
                    **_columns(command),
                    annotations=[],
                    preparation_state="pending",
                    created_at=now,
                    updated_at=now,
                )
                self._session.add(row)
                await self._session.flush()
                return _clip(row)
        except SQLAlchemyError:
            raise ShadowingUnavailable("the clip store is unavailable") from None

    async def list(self, *, owner_id: int) -> ShadowingClipPage:
        try:
            async with transaction_scope(self._session):
                rows = (
                    await self._session.scalars(
                        select(ShadowingClip)
                        .where(ShadowingClip.owner_id == owner_id)
                        .order_by(ShadowingClip.created_at.desc(), ShadowingClip.id.desc())
                        .limit(LIST_LIMIT)
                    )
                ).all()
                return ShadowingClipPage(items=tuple(_clip(row) for row in rows))
        except SQLAlchemyError:
            raise ShadowingUnavailable("the clip store is unavailable") from None

    async def get(self, *, owner_id: int, clip_id: int) -> ShadowingClipResponse:
        try:
            async with transaction_scope(self._session):
                return _clip(await self._require(owner_id=owner_id, clip_id=clip_id))
        except SQLAlchemyError:
            raise ShadowingUnavailable("the clip store is unavailable") from None

    async def replace(
        self, *, owner_id: int, clip_id: int, command: ShadowingClipCommand
    ) -> ShadowingClipResponse:
        try:
            async with transaction_scope(self._session):
                row = await self._require(owner_id=owner_id, clip_id=clip_id, lock=True)
                for name, value in _columns(command).items():
                    setattr(row, name, value)
                row.updated_at = self._clock()
                await self._session.flush()
                return _clip(row)
        except SQLAlchemyError:
            raise ShadowingUnavailable("the clip store is unavailable") from None

    async def delete(self, *, owner_id: int, clip_id: int) -> None:
        """Remove the row. The excerpt object stays: the store is immutable and has no delete."""
        try:
            async with transaction_scope(self._session):
                row = await self._require(owner_id=owner_id, clip_id=clip_id, lock=True)
                await self._session.delete(row)
        except SQLAlchemyError:
            raise ShadowingUnavailable("the clip store is unavailable") from None

    async def _require(
        self, *, owner_id: int, clip_id: int, lock: bool = False
    ) -> ShadowingClip:
        query = (
            select(ShadowingClip)
            .where(ShadowingClip.owner_id == owner_id)
            .where(ShadowingClip.id == clip_id)
        )
        if lock:
            query = query.with_for_update()
        row = await self._session.scalar(query)
        if row is None:
            raise ShadowingNotFound("the clip was not found")
        return row


def _columns(command: ShadowingClipCommand) -> dict[str, Any]:
    return {
        "title": command.title.strip(),
        "format": command.format,
        "skill_slug": command.skill_slug,
        "source_note": command.source_note.strip(),
        "license_note": command.license_note.strip(),
        "duration_ms": command.duration_ms,
        "phrases": [phrase.model_dump() for phrase in command.phrases],
    }


def _clip(row: ShadowingClip) -> ShadowingClipResponse:
    excerpt: ShadowingExcerptResponse | None = None
    if row.excerpt_object_key is not None:
        excerpt = ShadowingExcerptResponse(
            sha256=row.excerpt_object_key.rsplit("/", 1)[1],
            byte_length=cast(int, row.excerpt_byte_length),
            content_type=cast(Any, row.excerpt_content_type),
        )
    return ShadowingClipResponse(
        id=row.id,
        title=row.title,
        format=cast(Any, row.format),
        skill_slug=row.skill_slug,
        source_note=row.source_note,
        license_note=row.license_note,
        duration_ms=row.duration_ms,
        phrases=tuple(ShadowingPhrase.model_validate(item) for item in row.phrases),
        annotations=tuple(ShadowingAnnotation.model_validate(item) for item in row.annotations),
        preparation_state=cast(Any, row.preparation_state),
        excerpt=excerpt,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


__all__ = [
    "ShadowingClipService",
    "ShadowingConflict",
    "ShadowingError",
    "ShadowingInvalid",
    "ShadowingNotFound",
    "ShadowingUnavailable",
]

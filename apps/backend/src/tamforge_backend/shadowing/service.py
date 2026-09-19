"""Shadowing clips: owner-scoped rows whose excerpt lives in the object store."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import transaction_scope
from ..learning.schemas import PresignedUploadResponse
from ..models.base import utc_now
from ..storage.models import ObjectStoreError, PresignPutRequest, build_object_key
from ..storage.ports import ObjectStore
from .models import EXCERPT_CONTENT_TYPES, MAX_EXCERPT_BYTES, ShadowingClip
from .schemas import (
    ExcerptConfirmCommand,
    ExcerptDownloadResponse,
    ExcerptUploadCommand,
    ExcerptUploadResponse,
    ShadowingAnnotation,
    ShadowingClipCommand,
    ShadowingClipPage,
    ShadowingClipResponse,
    ShadowingExcerptResponse,
    ShadowingPhrase,
)

LIST_LIMIT = 500
UPLOAD_EXPIRES_SECONDS = 300
DOWNLOAD_EXPIRES_SECONDS = 300


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


def excerpt_object_key(*, owner_id: int, clip_id: int, sha256: str) -> str:
    """The only key an excerpt can have: class, owner, clip and the hash of its bytes."""
    return build_object_key(
        artifact_class="shadowing-excerpt",
        owner_id=str(owner_id),
        logical_id=f"clip-{clip_id}",
        sha256=sha256,
    )


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

    async def presign_excerpt(
        self, *, owner_id: int, clip_id: int, command: ExcerptUploadCommand
    ) -> ExcerptUploadResponse:
        """Sign one PUT that accepts exactly the declared bytes, type and hash."""
        try:
            async with transaction_scope(self._session):
                row = await self._require(owner_id=owner_id, clip_id=clip_id)
                if row.excerpt_object_key is not None:
                    raise ShadowingConflict("the clip already has its excerpt")
                signed = await self._objects.presign_put(
                    PresignPutRequest(
                        key=excerpt_object_key(
                            owner_id=owner_id, clip_id=clip_id, sha256=command.sha256
                        ),
                        sha256=command.sha256,
                        byte_length=command.byte_length,
                        content_type=command.content_type,
                        metadata={"owner-id": str(owner_id), "clip-id": str(clip_id)},
                        expires_seconds=UPLOAD_EXPIRES_SECONDS,
                    )
                )
                return ExcerptUploadResponse(
                    upload=PresignedUploadResponse(
                        url=signed.url,
                        method="PUT",
                        headers=dict(signed.headers),
                        expires_seconds=signed.expires_seconds,
                    )
                )
        except SQLAlchemyError:
            raise ShadowingUnavailable("the clip store is unavailable") from None
        except ObjectStoreError:
            raise ShadowingUnavailable("the excerpt store is unavailable") from None

    async def confirm_excerpt(
        self, *, owner_id: int, clip_id: int, command: ExcerptConfirmCommand
    ) -> ShadowingClipResponse:
        """Point the clip at its uploaded excerpt, once the store has the object.
        Repeating it for the same bytes changes nothing; other bytes are a conflict."""
        try:
            async with transaction_scope(self._session):
                row = await self._require(owner_id=owner_id, clip_id=clip_id, lock=True)
                key = excerpt_object_key(owner_id=owner_id, clip_id=clip_id, sha256=command.sha256)
                if row.excerpt_object_key is not None:
                    if row.excerpt_object_key == key:
                        return _clip(row)
                    raise ShadowingConflict("the clip already has its excerpt")
                stored = await self._objects.stat(key)
                if stored is None:
                    raise ShadowingInvalid("the excerpt was not uploaded")
                if (
                    stored.content_type not in EXCERPT_CONTENT_TYPES
                    or not 1 <= stored.byte_length <= MAX_EXCERPT_BYTES
                ):
                    raise ShadowingInvalid("the uploaded excerpt is not an accepted media file")
                row.excerpt_object_key = key
                row.excerpt_content_type = stored.content_type
                row.excerpt_byte_length = stored.byte_length
                row.updated_at = self._clock()
                await self._session.flush()
                return _clip(row)
        except SQLAlchemyError:
            raise ShadowingUnavailable("the clip store is unavailable") from None
        except ObjectStoreError:
            raise ShadowingUnavailable("the excerpt store is unavailable") from None

    async def excerpt_download(self, *, owner_id: int, clip_id: int) -> ExcerptDownloadResponse:
        """A short-lived signed GET for the Mac's local playback cache."""
        try:
            async with transaction_scope(self._session):
                row = await self._require(owner_id=owner_id, clip_id=clip_id)
                if row.excerpt_object_key is None:
                    raise ShadowingNotFound("the clip has no excerpt yet")
                url = await self._objects.presign_get(
                    row.excerpt_object_key, expires_seconds=DOWNLOAD_EXPIRES_SECONDS
                )
                return ExcerptDownloadResponse(
                    url=url,
                    expires_seconds=DOWNLOAD_EXPIRES_SECONDS,
                    sha256=row.excerpt_object_key.rsplit("/", 1)[1],
                    byte_length=cast(int, row.excerpt_byte_length),
                    content_type=cast(Any, row.excerpt_content_type),
                )
        except SQLAlchemyError:
            raise ShadowingUnavailable("the clip store is unavailable") from None
        except ObjectStoreError:
            raise ShadowingUnavailable("the excerpt store is unavailable") from None

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
    "DOWNLOAD_EXPIRES_SECONDS",
    "UPLOAD_EXPIRES_SECONDS",
    "ShadowingClipService",
    "ShadowingConflict",
    "ShadowingError",
    "ShadowingInvalid",
    "ShadowingNotFound",
    "ShadowingUnavailable",
    "excerpt_object_key",
]

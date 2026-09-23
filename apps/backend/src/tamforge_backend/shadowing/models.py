"""One shadowing clip: a short excerpt in the object store and the phrases to loop over."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..models.base import Base, utc_now

SHADOWING_FORMATS = ("solo", "dialogue")
PREPARATION_STATES = ("pending", "ready", "failed")
EXCERPT_CONTENT_TYPES = ("audio/mp4", "video/mp4", "video/quicktime")
MAX_CLIP_DURATION_MS = 120_000
MAX_EXCERPT_BYTES = 100 * 1024 * 1024


class ShadowingClip(Base):
    """The excerpt lives in the object store; this row holds its key, never its bytes.

    The three excerpt columns are set together by the confirm step, once the uploaded
    object has been seen in the store. `annotations` is filled by clip preparation.
    """

    __tablename__ = "shadowing_clips"
    __table_args__ = (
        UniqueConstraint("owner_id", "id", name="uq_shadowing_clips_owner_id_id"),
        UniqueConstraint("excerpt_object_key", name="uq_shadowing_clips_excerpt_object_key"),
        CheckConstraint("format IN ('solo', 'dialogue')", name="format_allowed"),
        CheckConstraint(
            "preparation_state IN ('pending', 'ready', 'failed')", name="preparation_state_allowed"
        ),
        CheckConstraint("btrim(title) <> '' AND octet_length(title) <= 800", name="title_bounded"),
        CheckConstraint(
            "octet_length(source_note) <= 2000 AND octet_length(license_note) <= 2000",
            name="notes_bounded",
        ),
        CheckConstraint("duration_ms BETWEEN 1000 AND 120000", name="duration_bounded"),
        CheckConstraint("jsonb_typeof(phrases) = 'array'", name="phrases_array"),
        CheckConstraint("jsonb_typeof(annotations) = 'array'", name="annotations_array"),
        CheckConstraint(
            "(excerpt_object_key IS NULL) = (excerpt_content_type IS NULL) "
            "AND (excerpt_object_key IS NULL) = (excerpt_byte_length IS NULL)",
            name="excerpt_complete_or_absent",
        ),
        CheckConstraint(
            "excerpt_content_type IS NULL "
            "OR excerpt_content_type IN ('audio/mp4', 'video/mp4', 'video/quicktime')",
            name="excerpt_content_type_allowed",
        ),
        CheckConstraint(
            "excerpt_byte_length IS NULL OR excerpt_byte_length BETWEEN 1 AND 104857600",
            name="excerpt_byte_length_bounded",
        ),
        Index("ix_shadowing_clips_owner_created", "owner_id", "created_at", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("owners.id", name="fk_shadowing_clips_owner_id_owners", ondelete="RESTRICT"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    format: Mapped[str] = mapped_column(Text, nullable=False)
    skill_slug: Mapped[str] = mapped_column(Text, nullable=False)
    source_note: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    license_note: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    phrases: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    annotations: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    preparation_state: Mapped[str] = mapped_column(
        Text, nullable=False, default="pending", server_default="pending"
    )
    excerpt_object_key: Mapped[str | None] = mapped_column(Text)
    excerpt_content_type: Mapped[str | None] = mapped_column(Text)
    excerpt_byte_length: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )


__all__ = [
    "EXCERPT_CONTENT_TYPES",
    "MAX_CLIP_DURATION_MS",
    "MAX_EXCERPT_BYTES",
    "PREPARATION_STATES",
    "SHADOWING_FORMATS",
    "ShadowingClip",
]

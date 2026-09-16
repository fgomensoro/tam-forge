"""Transcript-only interviews and the reference material the roles may cite."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Identity,
    Index,
    LargeBinary,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..models.base import Base, utc_now

TRANSCRIPT_ONLY = "transcript_only"
REFERENCE_KINDS = ("answer_bank", "story_catalog")


class InterviewTranscript(Base):
    """A transcript pasted for an interview that has no audio; one per interview."""

    __tablename__ = "interview_transcripts"
    __table_args__ = (
        UniqueConstraint("owner_id", "interview_id", name="uq_interview_transcripts_interview"),
        ForeignKeyConstraint(
            ["owner_id", "interview_id"],
            ["interviews.owner_id", "interviews.id"],
            name="fk_interview_transcripts_interview",
            ondelete="RESTRICT",
        ),
        CheckConstraint("source = 'transcript_only'", name="source_allowed"),
        CheckConstraint("btrim(text) <> '' AND octet_length(text) <= 1048576", name="text_bounded"),
        CheckConstraint("jsonb_typeof(turns) = 'array'", name="turns_array"),
        CheckConstraint("jsonb_typeof(metrics) = 'object'", name="metrics_object"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    interview_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False, default=TRANSCRIPT_ONLY)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    turns: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    analysis_version: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )


class ReferenceMaterial(Base):
    """One entry of the answer bank or story catalog, imported as reference, never evidence."""

    __tablename__ = "reference_materials"
    __table_args__ = (
        UniqueConstraint("owner_id", "content_hash", name="uq_reference_materials_content"),
        CheckConstraint("kind IN ('answer_bank', 'story_catalog')", name="kind_allowed"),
        CheckConstraint(
            "btrim(heading) <> '' AND octet_length(heading) <= 512", name="heading_bounded"
        ),
        CheckConstraint("octet_length(body) <= 65536", name="body_bounded"),
        CheckConstraint("octet_length(content_hash) = 32", name="content_hash_length"),
        Index("ix_reference_materials_owner_kind", "owner_id", "kind", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    document_title: Mapped[str] = mapped_column(Text, nullable=False)
    heading: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    readiness_label: Mapped[str] = mapped_column(Text, nullable=False, default="")
    readiness_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    content_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )


__all__ = ["REFERENCE_KINDS", "TRANSCRIPT_ONLY", "InterviewTranscript", "ReferenceMaterial"]

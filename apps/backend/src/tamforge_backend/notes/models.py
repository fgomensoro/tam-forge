"""One study note per activity, editable while a draft and frozen as evidence on approval."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Identity,
    Index,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..models.base import Base, utc_now

NOTE_STATUSES = ("draft", "approved")
NOTE_ASSISTANCE = ("independent", "coached")
NOTE_AUTHORS = ("learner", "coach")


class StudyNote(Base):
    __tablename__ = "study_notes"
    __table_args__ = (
        UniqueConstraint("owner_id", "id", name="uq_study_notes_owner_id_id"),
        UniqueConstraint("owner_id", "activity_instance_id", name="uq_study_notes_owner_activity"),
        ForeignKeyConstraint(
            ["owner_id", "activity_instance_id"],
            ["activity_instances.owner_id", "activity_instances.id"],
            name="fk_study_notes_owner_activity_activity_instances",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["owner_id", "artifact_id"],
            ["artifacts.owner_id", "artifacts.id"],
            name="fk_study_notes_owner_artifact_artifacts",
            ondelete="RESTRICT",
        ),
        CheckConstraint("status IN ('draft', 'approved')", name="status_allowed"),
        CheckConstraint("assistance IN ('independent', 'coached')", name="assistance_allowed"),
        CheckConstraint("drafted_by IN ('learner', 'coach')", name="drafted_by_allowed"),
        CheckConstraint(
            "(status = 'approved') = (artifact_id IS NOT NULL)", name="approved_has_artifact"
        ),
        CheckConstraint("btrim(title) <> '' AND octet_length(title) <= 1024", name="title_bounded"),
        Index("ix_study_notes_owner_status_updated", "owner_id", "status", "updated_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    activity_instance_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="draft")
    drafted_by: Mapped[str] = mapped_column(Text, nullable=False)
    assistance: Mapped[str] = mapped_column(Text, nullable=False)
    assessment_status: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    rule: Mapped[str] = mapped_column(Text, nullable=False, default="")
    explanation: Mapped[str] = mapped_column(Text, nullable=False, default="")
    example: Mapped[str] = mapped_column(Text, nullable=False, default="")
    misconceptions: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    validated_queries: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    sources: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    flashcards: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    artifact_id: Mapped[int | None] = mapped_column(BigInteger)
    content_sha256: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


__all__ = ["NOTE_ASSISTANCE", "NOTE_AUTHORS", "NOTE_STATUSES", "StudyNote"]

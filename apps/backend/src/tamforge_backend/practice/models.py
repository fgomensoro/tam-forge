"""One free-practice interview answer: the question, its recording, and its review."""

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


class PracticeAnswer(Base):
    """A recorded answer to one practice question; the review fills in when it has run.

    The reference answer is copied at the time of the practice, so a later edit of the
    answer bank never changes what a stored review was compared against.
    """

    __tablename__ = "practice_answers"
    __table_args__ = (
        UniqueConstraint("owner_id", "recording_id", name="uq_practice_answers_recording"),
        ForeignKeyConstraint(
            ["owner_id", "recording_id"],
            ["recordings.owner_id", "recordings.id"],
            name="fk_practice_answers_recording",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["reference_material_id"],
            ["reference_materials.id"],
            name="fk_practice_answers_reference",
            ondelete="SET NULL",
        ),
        CheckConstraint(
            "btrim(question) <> '' AND octet_length(question) <= 2048", name="question_bounded"
        ),
        CheckConstraint("octet_length(reference_answer) <= 65536", name="reference_bounded"),
        CheckConstraint(
            "outcome IS NULL OR jsonb_typeof(outcome) = 'object'", name="outcome_object"
        ),
        CheckConstraint(
            "(outcome IS NULL) = (reviewed_at IS NULL) AND (outcome IS NULL) = (model IS NULL) "
            "AND (outcome IS NULL) = (prompt_version IS NULL)",
            name="review_complete_or_absent",
        ),
        Index("ix_practice_answers_owner_created", "owner_id", "created_at", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    recording_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reference_material_id: Mapped[int | None] = mapped_column(BigInteger)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    reference_answer: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=""
    )
    model: Mapped[str | None] = mapped_column(Text)
    prompt_version: Mapped[str | None] = mapped_column(Text)
    outcome: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )


__all__ = ["PracticeAnswer"]

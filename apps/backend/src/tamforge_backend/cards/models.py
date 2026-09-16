"""Cards and their reviews. A card is content-addressed per owner so re-imports never duplicate."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..models.base import Base, utc_now

CARD_SOURCES = ("study_note", "evidence", "package", "coach", "manual")
CARD_ASSISTANCE = ("independent", "coached")
CARD_STATUSES = ("active", "suspended")
REVIEW_MODES = ("written", "spoken")


class Card(Base):
    __tablename__ = "cards"
    __table_args__ = (
        UniqueConstraint("owner_id", "id", name="uq_cards_owner_id_id"),
        UniqueConstraint("owner_id", "content_hash", name="uq_cards_owner_content_hash"),
        CheckConstraint(
            "source_kind IN ('study_note', 'evidence', 'package', 'coach', 'manual')",
            name="source_kind_allowed",
        ),
        CheckConstraint("assistance IN ('independent', 'coached')", name="assistance_allowed"),
        CheckConstraint("status IN ('active', 'suspended')", name="status_allowed"),
        CheckConstraint(
            "btrim(question) <> '' AND octet_length(question) <= 2048", name="question_bounded"
        ),
        CheckConstraint(
            "btrim(answer) <> '' AND octet_length(answer) <= 4096", name="answer_bounded"
        ),
        CheckConstraint("octet_length(content_hash) = 32", name="content_hash_length"),
        CheckConstraint("easiness >= 1.3", name="easiness_floor"),
        CheckConstraint("interval_days >= 0 AND repetitions >= 0", name="schedule_nonnegative"),
        Index("ix_cards_owner_due", "owner_id", "status", "due_on"),
        Index("ix_cards_owner_skill", "owner_id", "skill_slug"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("owners.id", name="fk_cards_owner_id_owners", ondelete="RESTRICT"),
        nullable=False,
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    source_kind: Mapped[str] = mapped_column(Text, nullable=False)
    source_ref: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    skill_slug: Mapped[str] = mapped_column(Text, nullable=False)
    assistance: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    scheduler_version: Mapped[str] = mapped_column(Text, nullable=False)
    easiness: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False)
    interval_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    repetitions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    due_on: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )


class CardReview(Base):
    __tablename__ = "card_reviews"
    __table_args__ = (
        UniqueConstraint("owner_id", "id", name="uq_card_reviews_owner_id_id"),
        ForeignKeyConstraint(
            ["owner_id", "card_id"],
            ["cards.owner_id", "cards.id"],
            name="fk_card_reviews_owner_card_cards",
            ondelete="RESTRICT",
        ),
        CheckConstraint("grade BETWEEN 0 AND 5", name="grade_bounded"),
        CheckConstraint("mode IN ('written', 'spoken')", name="mode_allowed"),
        Index("ix_card_reviews_owner_card", "owner_id", "card_id", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    card_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    grade: Mapped[int] = mapped_column(Integer, nullable=False)
    mode: Mapped[str] = mapped_column(Text, nullable=False, default="written")
    reviewed_on: Mapped[date] = mapped_column(Date, nullable=False)
    interval_before: Mapped[int] = mapped_column(Integer, nullable=False)
    interval_after: Mapped[int] = mapped_column(Integer, nullable=False)
    easiness_after: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False)
    due_after: Mapped[date] = mapped_column(Date, nullable=False)
    recording_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )


__all__ = ["CARD_ASSISTANCE", "CARD_SOURCES", "CARD_STATUSES", "REVIEW_MODES", "Card", "CardReview"]

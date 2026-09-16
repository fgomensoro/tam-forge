"""One English class session; its recordings' evidence maps to the TAM English skill."""

from __future__ import annotations

from datetime import datetime

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
)
from sqlalchemy.orm import Mapped, mapped_column

from ..models.base import Base, utc_now

ENGLISH_SKILL_SLUG = "tam_english"


class EnglishClass(Base):
    __tablename__ = "english_classes"
    __table_args__ = (
        UniqueConstraint("owner_id", "id", name="uq_english_classes_owner_id_id"),
        CheckConstraint(
            "btrim(teacher) <> '' AND octet_length(teacher) <= 256", name="teacher_bounded"
        ),
        CheckConstraint(
            "expected_duration_minutes BETWEEN 1 AND 480", name="expected_duration_bounded"
        ),
        CheckConstraint("octet_length(notes) <= 16384", name="notes_bounded"),
        CheckConstraint("skill_slug = 'tam_english'", name="skill_slug_tam_english"),
        Index("ix_english_classes_owner_starts", "owner_id", "starts_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("owners.id", name="fk_english_classes_owner_id_owners", ondelete="RESTRICT"),
        nullable=False,
    )
    teacher: Mapped[str] = mapped_column(Text, nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expected_duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    skill_slug: Mapped[str] = mapped_column(
        Text, nullable=False, default=ENGLISH_SKILL_SLUG, server_default=ENGLISH_SKILL_SLUG
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )


__all__ = ["ENGLISH_SKILL_SLUG", "EnglishClass"]

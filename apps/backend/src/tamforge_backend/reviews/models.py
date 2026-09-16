"""One AI review per activity: the reviewer's scores and reasoning, and what they recorded."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Identity,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..models.base import Base, utc_now


class ActivityReview(Base):
    __tablename__ = "activity_reviews"
    __table_args__ = (
        UniqueConstraint("owner_id", "id", name="uq_activity_reviews_owner_id_id"),
        UniqueConstraint(
            "owner_id", "activity_instance_id", name="uq_activity_reviews_owner_activity"
        ),
        ForeignKeyConstraint(
            ["owner_id", "activity_instance_id"],
            ["activity_instances.owner_id", "activity_instances.id"],
            name="fk_activity_reviews_owner_activity_activity_instances",
            ondelete="RESTRICT",
        ),
        CheckConstraint("jsonb_typeof(outcome) = 'object'", name="outcome_is_object"),
        CheckConstraint(
            "jsonb_typeof(evidence_event_ids) = 'array'", name="evidence_event_ids_array"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    activity_instance_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    attempt_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rubric_slug: Mapped[str] = mapped_column(Text, nullable=False)
    rubric_version: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[str] = mapped_column(Text, nullable=False)
    outcome: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    evidence_status: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_event_ids: Mapped[list[int]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )


__all__ = ["ActivityReview"]

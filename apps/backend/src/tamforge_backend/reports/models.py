from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..models.base import Base, utc_now

DELIVERY_STATUSES = ("pending", "sent", "failed", "skipped")


class WeeklyReport(Base):
    """One report per owner and week, kept with the aggregates it was written from."""

    __tablename__ = "weekly_reports"
    __table_args__ = (
        UniqueConstraint("owner_id", "week_start", name="uq_weekly_reports_owner_week"),
        CheckConstraint("week_end >= week_start", name="week_ordered"),
        CheckConstraint(
            "delivery_status IN ('pending', 'sent', 'failed', 'skipped')",
            name="delivery_status_allowed",
        ),
        CheckConstraint("jsonb_typeof(inputs) = 'object'", name="inputs_object"),
        CheckConstraint("jsonb_typeof(outcome) = 'object'", name="outcome_object"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("owners.id", name="fk_weekly_reports_owner", ondelete="RESTRICT"),
        nullable=False,
    )
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    week_end: Mapped[date] = mapped_column(Date, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[str] = mapped_column(Text, nullable=False)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    outcome: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    delivery_status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    delivery_detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )


class MonthlyReport(Base):
    """One report per owner and month: every skill against its targets, gaps first."""

    __tablename__ = "monthly_reports"
    __table_args__ = (
        UniqueConstraint("owner_id", "month_start", name="uq_monthly_reports_owner_month"),
        CheckConstraint("month_end >= month_start", name="month_ordered"),
        CheckConstraint(
            "delivery_status IN ('pending', 'sent', 'failed', 'skipped')",
            name="delivery_status_allowed",
        ),
        CheckConstraint("jsonb_typeof(inputs) = 'object'", name="inputs_object"),
        CheckConstraint("jsonb_typeof(outcome) = 'object'", name="outcome_object"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("owners.id", name="fk_monthly_reports_owner", ondelete="RESTRICT"),
        nullable=False,
    )
    month_start: Mapped[date] = mapped_column(Date, nullable=False)
    month_end: Mapped[date] = mapped_column(Date, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[str] = mapped_column(Text, nullable=False)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    outcome: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    delivery_status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    delivery_detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )


__all__ = ["DELIVERY_STATUSES", "MonthlyReport", "WeeklyReport"]

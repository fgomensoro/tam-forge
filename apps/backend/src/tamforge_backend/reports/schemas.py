from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReportSkillLine(StrictModel):
    skill_slug: str
    skill_name: str
    direction: Literal["up", "flat", "down"]
    note: str


class ReportSuggestion(StrictModel):
    change: str
    reason: str
    skill_slug: str


class WeeklyReportRequestCommand(StrictModel):
    """Ask for a week's report now; without a date, the last complete week."""

    week_start: date | None = None


class WeeklyReportResponse(StrictModel):
    """Where the report stands, then what it says. Suggestions are proposals, never applied."""

    week_start: date
    week_end: date
    status: Literal["not_requested", "queued", "running", "ready", "needs_attention"]
    failure_category: str | None = None
    report_id: int | None = None
    model: str | None = None
    delivery_status: Literal["pending", "sent", "failed", "skipped"] | None = None
    delivery_detail: str | None = None
    headline: str | None = None
    did: tuple[str, ...] = ()
    learned: tuple[str, ...] = ()
    improved: tuple[str, ...] = ()
    skills: tuple[ReportSkillLine, ...] = ()
    suggestions: tuple[ReportSuggestion, ...] = ()
    risks: tuple[str, ...] = ()
    decision_for_frank: str | None = None
    created_at: datetime | None = None


class WeeklyReportPage(StrictModel):
    items: tuple[WeeklyReportResponse, ...]


class MonthlyReportRequestCommand(StrictModel):
    """Ask for a month's report now; without a date, the last complete month."""

    month_start: date | None = None


class MonthlySkillTrajectory(StrictModel):
    skill_slug: str
    skill_name: str
    baseline: Decimal
    month_one_target: Decimal
    final_target: Decimal
    level_at_start: Decimal
    level_at_end: Decimal
    gap_to_month_one: Decimal
    gap_to_final: Decimal
    status: Literal["ahead", "on_track", "behind", "no_evidence"]
    note: str


class MonthlyReportResponse(StrictModel):
    """Where the report stands, then the trajectory with the largest gaps first."""

    month_start: date
    month_end: date
    status: Literal["not_requested", "queued", "running", "ready", "needs_attention"]
    failure_category: str | None = None
    report_id: int | None = None
    model: str | None = None
    delivery_status: Literal["pending", "sent", "failed", "skipped"] | None = None
    delivery_detail: str | None = None
    headline: str | None = None
    trajectory: tuple[MonthlySkillTrajectory, ...] = ()
    largest_gaps: tuple[str, ...] = ()
    coverage_verdict: str | None = None
    exit_criteria_verdict: str | None = None
    best_evidence: tuple[str, ...] = ()
    recommendation: Literal["keep", "reforecast", "change_scheme"] | None = None
    recommendation_reasoning: str | None = None
    next_month_priorities: tuple[str, ...] = ()
    created_at: datetime | None = None


class MonthlyReportPage(StrictModel):
    items: tuple[MonthlyReportResponse, ...]


__all__ = [
    "MonthlyReportPage",
    "MonthlyReportRequestCommand",
    "MonthlyReportResponse",
    "MonthlySkillTrajectory",
    "ReportSkillLine",
    "ReportSuggestion",
    "WeeklyReportPage",
    "WeeklyReportRequestCommand",
    "WeeklyReportResponse",
]

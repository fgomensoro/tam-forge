from __future__ import annotations

from datetime import date, datetime
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


__all__ = [
    "ReportSkillLine",
    "ReportSuggestion",
    "WeeklyReportPage",
    "WeeklyReportRequestCommand",
    "WeeklyReportResponse",
]

"""Daily and weekly reports, and the things they are not allowed to call progress.

A report answers one question: what did the evidence say. So it carries the competency
levels and the qualifying events that produced them, the two corrections that were open,
how far the learner's own score sat from the evaluated one, and how the interviews
actually went.

What it must never carry is the easy stuff. A streak counts days, not learning. A count
of finished activities counts effort, not evidence. Both feel like progress and both go
up while a weakness stays exactly where it was, so `FORBIDDEN_PROGRESS_SIGNALS` names
them and a test asserts no field here is one of them. The list is the point: without it,
the first person who wants the chart to go up adds one.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

PositiveId = Annotated[int, Field(strict=True, gt=0)]
Slug = Annotated[str, StringConstraints(strict=True, pattern=r"^[a-z][a-z0-9_]{0,63}$")]
Text = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=512, pattern=r"\S")]

CompetencyLevel = Literal["not_started", "practicing", "demonstrated"]
InterviewKind = Literal["practice", "mock", "real"]
InterviewOutcomeCode = Literal["advanced", "held", "ended", "no_decision_yet"]

# Two corrections at a time, the same number the feedback contract publishes.
MAX_OPEN_CORRECTIONS = 2

# Names a report may never carry. Each of them rises while a weakness stays put.
FORBIDDEN_PROGRESS_SIGNALS: frozenset[str] = frozenset(
    {
        "streak_days",
        "current_streak",
        "longest_streak",
        "activities_completed",
        "activity_count",
        "minutes_practiced",
        "sessions_this_week",
        "total_attempts",
    }
)


class ReportError(ValueError):
    """A report that would claim something its evidence does not support."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CompetencyLine(_StrictModel):
    """One competency, where it stands, and the events that put it there."""

    competency: Slug
    level: CompetencyLevel
    qualifying_event_ids: Annotated[tuple[PositiveId, ...], Field(max_length=64)] = ()

    @model_validator(mode="after")
    def a_level_cites_its_evidence(self) -> Self:
        if self.level != "not_started" and not self.qualifying_event_ids:
            raise ValueError("a level above not_started must cite its evidence")
        if len(set(self.qualifying_event_ids)) != len(self.qualifying_event_ids):
            raise ValueError("an event counts once")
        return self


class CalibrationDelta(_StrictModel):
    """How far the learner's own read sat from the evaluated one, and which way."""

    competency: Slug
    self_score: Annotated[Decimal, Field(ge=0, le=4, allow_inf_nan=False)]
    evaluated_score: Annotated[Decimal, Field(ge=0, le=4, allow_inf_nan=False)]

    @property
    def delta(self) -> Decimal:
        """Derived, never stored, so it cannot disagree with the two scores."""
        return self.self_score - self.evaluated_score

    @property
    def direction(self) -> Literal["overrated", "calibrated", "underrated"]:
        if self.delta > 0:
            return "overrated"
        if self.delta < 0:
            return "underrated"
        return "calibrated"


class OpenCorrection(_StrictModel):
    target_skill: Slug
    instruction: Text


class InterviewOutcome(_StrictModel):
    interview_id: PositiveId
    kind: InterviewKind
    outcome: InterviewOutcomeCode


class _Report(_StrictModel):
    owner_id: PositiveId
    competencies: Annotated[tuple[CompetencyLine, ...], Field(max_length=128)] = ()
    open_corrections: Annotated[
        tuple[OpenCorrection, ...], Field(max_length=MAX_OPEN_CORRECTIONS)
    ] = ()
    calibration: Annotated[tuple[CalibrationDelta, ...], Field(max_length=128)] = ()
    interviews: Annotated[tuple[InterviewOutcome, ...], Field(max_length=64)] = ()

    @model_validator(mode="after")
    def one_line_per_competency(self) -> Self:
        for label, names in (
            ("competency", [line.competency for line in self.competencies]),
            ("calibration", [line.competency for line in self.calibration]),
        ):
            if len(set(names)) != len(names):
                raise ValueError(f"one {label} line per competency")
        return self

    @model_validator(mode="after")
    def one_line_per_interview(self) -> Self:
        ids = [line.interview_id for line in self.interviews]
        if len(set(ids)) != len(ids):
            raise ValueError("one line per interview")
        return self


class DailyReport(_Report):
    report_date: date


class WeeklyReport(_Report):
    week_start: date
    week_end: date

    @model_validator(mode="after")
    def ordered_week(self) -> Self:
        if self.week_end <= self.week_start:
            raise ValueError("a week ends after it starts")
        if (self.week_end - self.week_start).days != 6:
            raise ValueError("a week is seven days")
        return self


__all__ = [
    "FORBIDDEN_PROGRESS_SIGNALS",
    "MAX_OPEN_CORRECTIONS",
    "CalibrationDelta",
    "CompetencyLevel",
    "CompetencyLine",
    "DailyReport",
    "InterviewKind",
    "InterviewOutcome",
    "InterviewOutcomeCode",
    "OpenCorrection",
    "ReportError",
    "WeeklyReport",
]

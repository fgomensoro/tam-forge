"""Pure study-time rules; asynchronous work never enters measured focus."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

DayType = Literal["weekday", "saturday", "sunday"]
FocusKind = Literal["focused", "real_interview", "async_processing"]


class TimePolicyError(ValueError):
    """A proposed study-time decision violates a fixed learner boundary."""


@dataclass(frozen=True, slots=True)
class DayBudget:
    day_type: DayType
    target_minutes: int
    acceptable_minimum: int
    maximum_minutes: int


@dataclass(frozen=True, slots=True)
class FocusEntry:
    kind: FocusKind
    minutes: int

    def __post_init__(self) -> None:
        if self.minutes < 0:
            raise TimePolicyError("focused minutes cannot be negative")


@dataclass(frozen=True, slots=True)
class CompletionGate:
    required_outputs_satisfied: bool
    pass_conditions_satisfied: bool


def budget_for(local_date: date) -> DayBudget:
    """Return the immutable budget for one learner-local calendar date."""
    if local_date.weekday() == 6:
        return DayBudget("sunday", 0, 0, 0)
    if local_date.weekday() == 5:
        return DayBudget("saturday", 120, 0, 120)
    return DayBudget("weekday", 240, 225, 255)


def budget_for_day(kind: str, budget_minutes: int) -> DayBudget:
    """Budget for one scheme day: the file decides the minutes, not the weekday.

    A weekday keeps the same 15-minute tolerance the fixed 240-minute day had; an
    assessment day is a hard cap with no floor, like the old Saturday.
    """
    if budget_minutes < 0:
        raise TimePolicyError("day budget cannot be negative")
    if kind == "assessment":
        return DayBudget("saturday", budget_minutes, 0, budget_minutes)
    if kind == "weekday":
        return DayBudget(
            "weekday", budget_minutes, max(budget_minutes - 15, 0), budget_minutes + 15
        )
    raise TimePolicyError("unknown scheme day kind")


def validate_planned_minutes(budget: DayBudget, planned_minutes: int) -> None:
    """Reject negative, Sunday, and over-limit plans without inventing filler."""
    if planned_minutes < 0:
        raise TimePolicyError("planned minutes cannot be negative")
    if planned_minutes > budget.maximum_minutes:
        raise TimePolicyError(
            f"{budget.day_type} study cannot exceed {budget.maximum_minutes} minutes"
        )


def hard_stop_recommended(budget: DayBudget, *, focused_minutes: int) -> bool:
    """Recommend a stop at the fixed cap; never extend the day automatically."""
    if focused_minutes < 0:
        raise TimePolicyError("focused minutes cannot be negative")
    return budget.maximum_minutes > 0 and focused_minutes >= budget.maximum_minutes


def counted_focused_minutes(entries: tuple[FocusEntry, ...]) -> int:
    """Count direct study and real interviews, excluding asynchronous processing."""
    return sum(item.minutes for item in entries if item.kind != "async_processing")


def can_finish_early(gates: tuple[CompletionGate, ...]) -> bool:
    """Allow an early finish only after every required output and pass gate succeeds."""
    return bool(gates) and all(
        item.required_outputs_satisfied and item.pass_conditions_satisfied for item in gates
    )

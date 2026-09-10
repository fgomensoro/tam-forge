"""Daily close and the rule that a missed day never lands on a later one.

The hard part of a study week is not planning it, it is what happens when a day does not
go as planned. Every answer that feels generous makes the next day worse: rolling
yesterday forward, stretching tomorrow, letting corrections pile up. So the rules here
are all forms of refusal.

Unfinished work is classified rather than left ambiguous. It carries forward only if it
fits somewhere it can actually fit, and otherwise it is replaced by something smaller or
dropped outright. Dropping is a real outcome, not a failure of the planner: a day that
absorbs everything that went wrong before it is a day nobody finishes either.

And a close carries at most two corrections into the next lesson, the same two the
feedback contract publishes. Corrections that accumulate stop being the next thing to fix
and become a backlog nobody works through.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

PositiveId = Annotated[int, Field(strict=True, gt=0)]
Slug = Annotated[str, StringConstraints(strict=True, pattern=r"^[a-z][a-z0-9_]{0,63}$")]
Text = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=512, pattern=r"\S")]

# The same two the feedback contract publishes. A close never carries more.
MAX_NEXT_CORRECTIONS = 2

# What happens to work a day did not finish.
UnfinishedDisposition = Literal["carry_forward", "replaced", "dropped"]

# Why it did not finish. A closed vocabulary, because "other" becomes every reason.
UnfinishedReason = Literal[
    "ran_out_of_time",
    "blocked_on_input",
    "interrupted",
    "not_started",
]


class CadenceError(ValueError):
    """A plan that would cram a day or stretch it past its budget."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class UnfinishedWork(_StrictModel):
    """One thing a day did not finish, and what becomes of it."""

    activity_id: PositiveId
    minutes_remaining: Annotated[int, Field(strict=True, ge=1, le=600)]
    reason: UnfinishedReason
    disposition: UnfinishedDisposition
    note: Text | None = None


class NextCorrection(_StrictModel):
    target_skill: Slug
    instruction: Text


class DailyClose(_StrictModel):
    """What one day ended with, and what it hands to the next."""

    owner_id: PositiveId
    closed_on: date
    completed_activity_ids: Annotated[tuple[PositiveId, ...], Field(max_length=32)] = ()
    unfinished: Annotated[tuple[UnfinishedWork, ...], Field(max_length=32)] = ()
    next_corrections: Annotated[
        tuple[NextCorrection, ...], Field(max_length=MAX_NEXT_CORRECTIONS)
    ] = ()

    @model_validator(mode="after")
    def each_activity_appears_once(self) -> Self:
        ids = [*self.completed_activity_ids, *(item.activity_id for item in self.unfinished)]
        if len(set(ids)) != len(ids):
            raise ValueError("an activity is either finished or unfinished, once")
        return self

    @model_validator(mode="after")
    def distinct_corrections(self) -> Self:
        skills = [correction.target_skill for correction in self.next_corrections]
        if len(set(skills)) != len(skills):
            raise ValueError("two corrections on one skill is one correction")
        return self

    @property
    def carried_forward(self) -> tuple[UnfinishedWork, ...]:
        return tuple(item for item in self.unfinished if item.disposition == "carry_forward")


def absorb(
    *, minutes_remaining: int, target_budget_minutes: int, target_planned_minutes: int
) -> UnfinishedDisposition:
    """Decide what a later day can honestly do with work that did not finish.

    It carries forward only into room the day already has. Nothing here can make a day
    longer, which is the whole point: the alternative is a plan that always fits on paper
    and never fits in an evening.
    """
    if minutes_remaining < 1:
        raise CadenceError("unfinished work has time remaining or it is finished")
    if target_budget_minutes < 0 or target_planned_minutes < 0:
        raise CadenceError("a day's budget and plan are not negative")
    free = target_budget_minutes - target_planned_minutes
    if free <= 0:
        return "dropped"
    if minutes_remaining <= free:
        return "carry_forward"
    # It does not fit whole. Something smaller can take its place, but the day does not
    # stretch to hold the original.
    return "replaced"


def replacement_minutes(
    *, target_budget_minutes: int, target_planned_minutes: int
) -> int:
    """How much a replacement may take: exactly the room that already exists."""
    if target_budget_minutes < 0 or target_planned_minutes < 0:
        raise CadenceError("a day's budget and plan are not negative")
    return max(0, target_budget_minutes - target_planned_minutes)


__all__ = [
    "MAX_NEXT_CORRECTIONS",
    "CadenceError",
    "DailyClose",
    "NextCorrection",
    "UnfinishedDisposition",
    "UnfinishedReason",
    "UnfinishedWork",
    "absorb",
    "replacement_minutes",
]

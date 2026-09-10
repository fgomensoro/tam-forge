"""Month exit: what has to be true, and what has to be approved, before the next one.

A month does not end because thirty days passed. It ends when the evidence says the exit
criteria are met, and the next month does not start until a specific version of it has
been imported and a person has approved it. Both halves matter. Without the first, a
roadmap advances on the calendar. Without the second, it advances on whatever happened to
be generated.

The link to the roadmap being left behind is required rather than optional. A month
transition that forgets what came before turns a sequence of months into a series of
unrelated plans, and the question "what was I working on when I demonstrated this" stops
having an answer.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

PositiveId = Annotated[int, Field(strict=True, gt=0)]
Slug = Annotated[str, StringConstraints(strict=True, pattern=r"^[a-z][a-z0-9_]{0,63}$")]
Text = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=512, pattern=r"\S")]
VersionKey = Annotated[str, StringConstraints(strict=True, pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")]

CompetencyLevel = Literal["not_started", "practicing", "demonstrated"]

# Ordered weakest to strongest, so "at least this level" is a comparison rather than a
# table of special cases.
LEVEL_ORDER: tuple[CompetencyLevel, ...] = ("not_started", "practicing", "demonstrated")


class TransitionError(ValueError):
    """A month that would end, or a roadmap that would start, without its evidence."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ExitCriterion(_StrictModel):
    competency: Slug
    required_level: CompetencyLevel

    @model_validator(mode="after")
    def a_criterion_requires_something(self) -> Self:
        if self.required_level == "not_started":
            raise ValueError("requiring not_started is not a criterion")
        return self


class ObservedLevel(_StrictModel):
    competency: Slug
    level: CompetencyLevel
    qualifying_event_ids: Annotated[tuple[PositiveId, ...], Field(max_length=64)] = ()

    @model_validator(mode="after")
    def a_level_cites_its_evidence(self) -> Self:
        if self.level != "not_started" and not self.qualifying_event_ids:
            raise ValueError("a level above not_started must cite its evidence")
        return self


class MonthExitReview(_StrictModel):
    """The comparison itself: what was required against what the evidence shows."""

    owner_id: PositiveId
    month_key: VersionKey
    criteria: Annotated[tuple[ExitCriterion, ...], Field(min_length=1, max_length=64)]
    observed: Annotated[tuple[ObservedLevel, ...], Field(max_length=128)] = ()

    @model_validator(mode="after")
    def one_line_each(self) -> Self:
        for label, names in (
            ("criterion", [item.competency for item in self.criteria]),
            ("observation", [item.competency for item in self.observed]),
        ):
            if len(set(names)) != len(names):
                raise ValueError(f"one {label} per competency")
        return self

    @property
    def unmet(self) -> tuple[ExitCriterion, ...]:
        """Every criterion the evidence does not reach. An unobserved competency is unmet."""
        levels = {item.competency: item.level for item in self.observed}
        return tuple(
            criterion
            for criterion in self.criteria
            if LEVEL_ORDER.index(levels.get(criterion.competency, "not_started"))
            < LEVEL_ORDER.index(criterion.required_level)
        )

    @property
    def met(self) -> bool:
        return not self.unmet


class NextRoadmapActivation(_StrictModel):
    """A specific next version, imported on purpose and approved by a person."""

    previous_roadmap_id: PositiveId
    next_version_key: VersionKey
    imported_at: datetime
    approved_at: datetime
    approved_by: Text

    @model_validator(mode="after")
    def imported_then_approved(self) -> Self:
        for moment in (self.imported_at, self.approved_at):
            if moment.tzinfo is None or moment.utcoffset() is None:
                raise ValueError("transition timestamps must be timezone-aware")
        if self.approved_at < self.imported_at:
            raise ValueError("a version is approved after it is imported, not before")
        return self


def activate_next_roadmap(
    review: MonthExitReview, activation: NextRoadmapActivation
) -> NextRoadmapActivation:
    """Return the activation, or refuse and say which half is missing."""
    if not review.met:
        missing = ", ".join(criterion.competency for criterion in review.unmet)
        raise TransitionError(f"exit criteria are not met: {missing}")
    return activation


__all__ = [
    "LEVEL_ORDER",
    "CompetencyLevel",
    "ExitCriterion",
    "MonthExitReview",
    "NextRoadmapActivation",
    "ObservedLevel",
    "TransitionError",
    "activate_next_roadmap",
]

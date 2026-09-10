"""Saturday assessments: no help, a hard cap, and only saved work counts.

One day a week the learner finds out what they can do unaided. That only means anything
if three things hold, and each of them is structural here rather than a convention
someone remembers.

No assistance at all. Not hints after committing, not a tutor waiting at the end: the
assistance code admits exactly one value, so an assisted assessment cannot be
constructed and therefore cannot be reported as one.

Two hours, and then it is over. An assessment that runs long stops measuring what the
learner can do in the time an interview actually gives them.

And nothing advances a competency except work that was saved. An assessment the learner
abandoned contributes no evidence, which is the honest outcome: it says nothing about
what they can do, so it should say nothing about what they have demonstrated.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

PositiveId = Annotated[int, Field(strict=True, gt=0)]
Slug = Annotated[str, StringConstraints(strict=True, pattern=r"^[a-z][a-z0-9_]{0,63}$")]

# `date.weekday()` counts from Monday, so Saturday is five.
SATURDAY = 5

# Two hours. Longer stops measuring what the learner can do in the time an interview
# actually gives them.
ASSESSMENT_MAX_MINUTES = 120

# The one assistance code an assessment may carry, and the one attempt kind. Both are
# single-valued literals rather than checks, so the wrong shape cannot be built at all.
AssessmentAssistance = Literal["no_ai"]
AssessmentAttemptKind = Literal["attempt_a"]


class AssessmentError(ValueError):
    """An assessment that would report more than it measured."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SaturdayAssessment(_StrictModel):
    assessment_id: PositiveId
    owner_id: PositiveId
    competency: Slug
    held_on: date
    minutes: Annotated[int, Field(strict=True, ge=1, le=ASSESSMENT_MAX_MINUTES)]
    assistance: AssessmentAssistance = "no_ai"
    attempt_kind: AssessmentAttemptKind = "attempt_a"
    saved_evidence_ids: Annotated[tuple[PositiveId, ...], Field(max_length=16)] = ()

    @model_validator(mode="after")
    def held_on_a_saturday(self) -> Self:
        if self.held_on.weekday() != SATURDAY:
            raise ValueError("a Saturday assessment is held on a Saturday")
        return self

    @model_validator(mode="after")
    def evidence_is_counted_once(self) -> Self:
        if len(set(self.saved_evidence_ids)) != len(self.saved_evidence_ids):
            raise ValueError("an evidence id counts once")
        return self

    @property
    def saved(self) -> bool:
        return bool(self.saved_evidence_ids)


def demonstrated_from(
    assessments: Iterable[SaturdayAssessment], *, competency: str, owner_id: int
) -> tuple[int, ...]:
    """Every evidence id this owner's saved assessments offer for one competency.

    An abandoned assessment contributes nothing. It says nothing about what the learner
    can do, so it should say nothing about what they have demonstrated.
    """
    if owner_id <= 0:
        raise AssessmentError("an owner id is required")
    collected: list[int] = []
    for assessment in assessments:
        if assessment.owner_id != owner_id or assessment.competency != competency:
            continue
        collected.extend(assessment.saved_evidence_ids)
    if len(set(collected)) != len(collected):
        raise AssessmentError("two assessments claim the same evidence")
    return tuple(collected)


__all__ = [
    "ASSESSMENT_MAX_MINUTES",
    "SATURDAY",
    "AssessmentAssistance",
    "AssessmentAttemptKind",
    "AssessmentError",
    "SaturdayAssessment",
    "demonstrated_from",
]

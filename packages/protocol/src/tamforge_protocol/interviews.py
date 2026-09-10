"""Interviews, and which of them may name an opportunity at all.

Three kinds, and the difference is not cosmetic. A real interview happened with a real
company and must name the opportunity it belongs to, or the evidence it produces cannot
be traced to anything. Practice and mock interviews are exercises: they must not name
one, because an exercise linked to a live opportunity is how practice material ends up
read as if it were the real conversation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

PositiveId = Annotated[int, Field(strict=True, gt=0)]
Text = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=512, pattern=r"\S")]

InterviewKind = Literal["practice", "mock", "real"]

# Only a real interview belongs to an opportunity. The other two are exercises.
OPPORTUNITY_LINKED_KINDS: frozenset[str] = frozenset({"real"})


class InterviewError(ValueError):
    """An interview whose link contradicts what kind of interview it is."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Interview(_StrictModel):
    interview_id: PositiveId
    owner_id: PositiveId
    kind: InterviewKind
    scheduled_for: datetime
    opportunity_id: PositiveId | None = None
    stage_label: Text | None = None

    @model_validator(mode="after")
    def timezone_aware(self) -> Self:
        if self.scheduled_for.tzinfo is None or self.scheduled_for.utcoffset() is None:
            raise ValueError("scheduled_for must be timezone-aware")
        return self

    @model_validator(mode="after")
    def link_matches_the_kind(self) -> Self:
        linked = self.opportunity_id is not None
        if (self.kind in OPPORTUNITY_LINKED_KINDS) != linked:
            raise ValueError("only a real interview names the opportunity it belongs to")
        if self.stage_label is not None and not linked:
            raise ValueError("an exercise has no stage in anyone's pipeline")
        return self

    @property
    def is_real(self) -> bool:
        return self.kind in OPPORTUNITY_LINKED_KINDS


__all__ = [
    "OPPORTUNITY_LINKED_KINDS",
    "Interview",
    "InterviewError",
    "InterviewKind",
]

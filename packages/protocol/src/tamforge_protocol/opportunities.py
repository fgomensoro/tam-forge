"""Opportunities: who, for what, where it stands, and what happens next.

An opportunity is the record a real interview hangs from, so it keeps the things that
stop being knowable later. The job description is a snapshot with its own hash and the
moment it was taken, because postings are edited and taken down and the version someone
prepared against is the one that matters afterwards. The stage history is append-only
and chronological rather than a single current stage, since "how long did the panel take
to answer" is a question only the history can answer.

Retrieval is owner-scoped and opportunity-scoped by construction. Nothing here takes a
bare id and hands back a row: the helpers require the owner, and the interview link check
requires both sides to agree before anything crosses between them.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

PositiveId = Annotated[int, Field(strict=True, gt=0)]
Hash = Annotated[str, StringConstraints(strict=True, pattern=r"^[a-f0-9]{64}$")]
Text = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=512, pattern=r"\S")]
SnapshotText = Annotated[
    str, StringConstraints(strict=True, min_length=1, max_length=32_768, pattern=r"\S")
]

OpportunityStage = Literal[
    "identified",
    "applied",
    "screen",
    "technical",
    "panel",
    "offer",
    "closed_won",
    "closed_lost",
]

# Nothing follows a close. A reopened search is a new opportunity, not an edit of the
# one that ended, or the history stops being a record of what happened.
TERMINAL_STAGES: frozenset[str] = frozenset({"closed_won", "closed_lost"})


class OpportunityError(ValueError):
    """A retrieval or link that would cross an owner or an opportunity boundary."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class JobDescriptionSnapshot(_StrictModel):
    """The posting as it read when the learner prepared against it."""

    captured_at: datetime
    sha256: Hash
    text: SnapshotText

    @model_validator(mode="after")
    def timezone_aware(self) -> Self:
        if self.captured_at.tzinfo is None or self.captured_at.utcoffset() is None:
            raise ValueError("captured_at must be timezone-aware")
        return self


class StageEvent(_StrictModel):
    stage: OpportunityStage
    occurred_at: datetime
    note: Text | None = None

    @model_validator(mode="after")
    def timezone_aware(self) -> Self:
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        return self


class Opportunity(_StrictModel):
    opportunity_id: PositiveId
    owner_id: PositiveId
    company: Text
    role: Text
    job_description: JobDescriptionSnapshot
    stage_history: Annotated[tuple[StageEvent, ...], Field(min_length=1, max_length=64)]
    next_action: Text | None = None
    interview_ids: Annotated[tuple[PositiveId, ...], Field(max_length=64)] = ()

    @property
    def current_stage(self) -> OpportunityStage:
        return self.stage_history[-1].stage

    @property
    def closed(self) -> bool:
        return self.current_stage in TERMINAL_STAGES

    @model_validator(mode="after")
    def ordered_history(self) -> Self:
        for earlier, later in zip(self.stage_history, self.stage_history[1:], strict=False):
            if later.occurred_at < earlier.occurred_at:
                raise ValueError("stage history must be chronological")
            if earlier.stage in TERMINAL_STAGES:
                raise ValueError("nothing follows a closed stage")
        return self

    @model_validator(mode="after")
    def distinct_interviews(self) -> Self:
        if len(set(self.interview_ids)) != len(self.interview_ids):
            raise ValueError("an interview is linked once")
        return self

    @model_validator(mode="after")
    def closed_opportunities_have_no_next_action(self) -> Self:
        if self.closed and self.next_action is not None:
            raise ValueError("a closed opportunity has no next action")
        return self


def owned_by(
    opportunities: Iterable[Opportunity], *, owner_id: int
) -> tuple[Opportunity, ...]:
    """Every opportunity this owner has, and never one belonging to anybody else."""
    if owner_id <= 0:
        raise OpportunityError("an owner id is required")
    return tuple(item for item in opportunities if item.owner_id == owner_id)


def require_linked(opportunity: Opportunity, *, interview_id: int, owner_id: int) -> None:
    """Raise unless this owner's opportunity really does link this interview."""
    if opportunity.owner_id != owner_id:
        raise OpportunityError("this opportunity belongs to another owner")
    if interview_id not in opportunity.interview_ids:
        raise OpportunityError("this interview belongs to another opportunity")


def visible_stage_history(
    opportunity: Opportunity, *, owner_id: int
) -> Sequence[StageEvent]:
    if opportunity.owner_id != owner_id:
        raise OpportunityError("this opportunity belongs to another owner")
    return opportunity.stage_history


__all__ = [
    "TERMINAL_STAGES",
    "JobDescriptionSnapshot",
    "Opportunity",
    "OpportunityError",
    "OpportunityStage",
    "StageEvent",
    "owned_by",
    "require_linked",
    "visible_stage_history",
]

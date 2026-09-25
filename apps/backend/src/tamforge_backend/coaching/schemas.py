from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

WORKING_CONTEXT_MAX_CHARS = 12000


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CoachEvidenceProposal(StrictModel):
    index: Annotated[int, Field(ge=0)]
    kind: Literal["note", "correction", "question", "card"]
    text: str
    answer: str = ""
    accepted: bool


class CoachMessageResponse(StrictModel):
    id: int
    speaker: Literal["learner", "coach"]
    text: str
    next_step: str | None
    proposed_evidence: list[CoachEvidenceProposal]
    created_at: datetime


class CoachThreadResponse(StrictModel):
    activity_id: int
    thread_id: int | None
    coaching_allowed: bool
    committed: bool
    assistance_mode: Literal["none", "coach_preparation", "hint_ladder"]
    next_step: str
    messages: list[CoachMessageResponse]


class CoachDraftField(StrictModel):
    name: Annotated[str, Field(min_length=1, max_length=64)]
    value: Annotated[str, Field(max_length=4000)]


class CoachWorkingContext(StrictModel):
    """Where the learner is standing: the task-guide step and the unsaved draft fields.

    It goes into that turn's prompt only; it is never stored and never evidence.
    """

    step: Annotated[str, Field(max_length=200)] = ""
    fields: Annotated[list[CoachDraftField], Field(max_length=20)] = []

    @model_validator(mode="after")
    def fits_the_total(self) -> CoachWorkingContext:
        total = len(self.step) + sum(len(f.name) + len(f.value) for f in self.fields)
        if total > WORKING_CONTEXT_MAX_CHARS:
            raise ValueError(f"the working context is over {WORKING_CONTEXT_MAX_CHARS} characters")
        return self


class CoachMessageCommand(StrictModel):
    text: Annotated[str, Field(min_length=1, max_length=8192)]
    # A factory, not an instance: an instance default puts a sibling "default" beside the
    # "$ref" in the native OpenAPI 3.0 input, which 3.0 ignores and the generator may not.
    context: CoachWorkingContext = Field(default_factory=CoachWorkingContext)


class AcceptEvidenceCommand(StrictModel):
    """Accept one proposal. A card may be edited on the way in; blank fields keep the proposal."""

    message_id: Annotated[int, Field(gt=0)]
    index: Annotated[int, Field(ge=0, le=4)]
    question: Annotated[str, Field(max_length=2048)] = ""
    answer: Annotated[str, Field(max_length=4096)] = ""


__all__ = [
    "AcceptEvidenceCommand",
    "CoachDraftField",
    "CoachEvidenceProposal",
    "CoachMessageCommand",
    "CoachMessageResponse",
    "CoachThreadResponse",
    "CoachWorkingContext",
]

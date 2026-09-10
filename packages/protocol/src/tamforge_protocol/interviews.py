"""Interviews, and which of them may name an opportunity at all.

Recording a real interview records another person, which is why the lock here is not a
formality. Permission is attested once, with a named person, a moment, and the exact
scopes it covers, and everything downstream asks the lock rather than assuming. A missing
attestation, a revoked one, or one that never covered this scope all mean the same thing:
locked.

Revocation reaches processing, not only capture. Material already recorded stops being
processable the moment permission is withdrawn, because the alternative is a system where
withdrawing consent changes nothing that has already happened.

Practice and mock interviews record only the learner, so the lock does not apply to them
and says so rather than pretending to be satisfied.

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


PermissionScope = Literal["record_audio", "store_transcript", "release_to_claude"]
LockReason = Literal[
    "none",
    "not_applicable",
    "permission_missing",
    "permission_revoked",
    "scope_not_granted",
]
LockState = Literal["locked", "unlocked"]


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


class RecordingPermission(_StrictModel):
    """One attestation: who said yes, when, and to exactly what."""

    interview_id: PositiveId
    attested_by: Text
    attested_at: datetime
    scopes: Annotated[tuple[PermissionScope, ...], Field(min_length=1, max_length=8)]
    revoked_at: datetime | None = None

    @model_validator(mode="after")
    def coherent(self) -> Self:
        for moment in (self.attested_at, self.revoked_at):
            if moment is not None and (moment.tzinfo is None or moment.utcoffset() is None):
                raise ValueError("permission timestamps must be timezone-aware")
        if self.revoked_at is not None and self.revoked_at < self.attested_at:
            raise ValueError("permission cannot be revoked before it was given")
        if len(set(self.scopes)) != len(self.scopes):
            raise ValueError("a scope is granted once")
        return self

    def active_at(self, moment: datetime) -> bool:
        return self.revoked_at is None or moment < self.revoked_at


def recording_lock(
    interview: Interview,
    permission: RecordingPermission | None,
    *,
    scope: PermissionScope,
    now: datetime,
) -> tuple[LockState, LockReason]:
    """Say whether this scope is open, and if not, exactly which rule closed it."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise InterviewError("the current time must be timezone-aware")
    if not interview.is_real:
        # An exercise records only the learner. Saying "not applicable" is honest;
        # returning unlocked would let a caller treat the two cases as the same.
        return "locked", "not_applicable"
    if permission is None or permission.interview_id != interview.interview_id:
        return "locked", "permission_missing"
    if not permission.active_at(now):
        return "locked", "permission_revoked"
    if scope not in permission.scopes:
        return "locked", "scope_not_granted"
    return "unlocked", "none"


def require_unlocked(
    interview: Interview,
    permission: RecordingPermission | None,
    *,
    scope: PermissionScope,
    now: datetime,
) -> None:
    """Raise unless this scope is open right now."""
    state, reason = recording_lock(interview, permission, scope=scope, now=now)
    if state != "unlocked":
        raise InterviewError(f"recording is locked: {reason}")


__all__ = [
    "OPPORTUNITY_LINKED_KINDS",
    "LockReason",
    "LockState",
    "PermissionScope",
    "RecordingPermission",
    "recording_lock",
    "require_unlocked",
    "Interview",
    "InterviewError",
    "InterviewKind",
]

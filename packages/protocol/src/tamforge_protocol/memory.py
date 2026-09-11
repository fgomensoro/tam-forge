"""What the system remembers about the learner, and why nothing here can be edited.

A memory is a claim somebody could later dispute: "prefers worked examples", "struggles
with window functions", "the recruiter at Northwind said the panel is three rounds". The
system will act on these, so each one carries what it rests on. A revision names its
evidence, says how confident it is, says how sensitive the claim is, and says which roles
may see it. A claim with no evidence is an opinion, and the contract refuses it.

Nothing is edited in place. Correcting a memory means writing a new revision that names
the one it supersedes; the old revision keeps its permanent id and stays readable, so the
question "what did the system believe when it gave that advice" always has an answer. A
revision that contradicts another says so explicitly, with a link, rather than quietly
winning by being newer.

Four kinds, kept apart because they age differently. An episodic memory is something that
happened and never becomes false. A semantic memory is a standing fact about the learner
that can go stale. A hypothesis is a guess awaiting evidence, and it must say so. A
procedural memory is how the learner does something. Working memory is scratch: it never
enters the ledger at all.

Visibility is decided before retrieval, not after. A role asks for what it may see, at a
moment, and gets only revisions that are approved, in force, unexpired, and scoped to it.
The Interviewer never receives another role's writable memory because it never receives
writable memory: the ledger has no mutation a caller could reach.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from types import MappingProxyType
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

PositiveId = Annotated[int, Field(strict=True, gt=0)]
Text = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=2000, pattern=r"\S")]
Confidence = Annotated[float, Field(strict=True, ge=0.0, le=1.0)]

# Working memory is scratch for one exchange and is deliberately absent: it never enters
# the ledger, so there is no kind for it to be recorded under.
MemoryKind = Literal["episodic", "semantic", "hypothesis", "procedural"]
LEDGER_KINDS: frozenset[str] = frozenset({"episodic", "semantic", "hypothesis", "procedural"})

MemoryScope = Literal["global", "role", "roadmap", "activity", "case", "opportunity", "interview"]
# Every scope except global points at one thing; global points at nothing.
SCOPED_KINDS: frozenset[str] = frozenset(
    {"role", "roadmap", "activity", "case", "opportunity", "interview"}
)

Sensitivity = Literal["routine", "personal", "real_interview"]
# Real-interview material stays out of practice contexts (see interviews.py). A role
# reading at a lower ceiling never sees a higher one.
SENSITIVITY_RANK: Mapping[Sensitivity, int] = MappingProxyType(
    {"routine": 0, "personal": 1, "real_interview": 2}
)

Role = Literal["planner", "tutor", "coach", "reviewer", "analyst", "interviewer"]

EvidenceKind = Literal[
    "activity", "assessment", "interview", "conversation", "report", "user_statement"
]

Approval = Literal["proposed", "approved", "rejected"]

# A hypothesis is a guess and must not be read as settled; it is never approved into a
# fact. Confirming one means writing a semantic revision that names it as evidence.
KINDS_NEVER_APPROVED: frozenset[str] = frozenset({"hypothesis"})


class MemoryError(ValueError):
    """A revision that would edit, skip, or contradict the ledger's own rules."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EvidenceLink(_StrictModel):
    kind: EvidenceKind
    reference_id: PositiveId


class Provenance(_StrictModel):
    """Who produced the claim and from what. A role name, or the learner themself."""

    author: Role | Literal["learner"]
    model_run_id: PositiveId | None = None

    @model_validator(mode="after")
    def _a_model_run_belongs_to_a_role(self) -> Self:
        if self.author == "learner" and self.model_run_id is not None:
            raise ValueError("a learner statement has no model run behind it")
        return self


class MemoryRevision(_StrictModel):
    memory_id: PositiveId
    revision_id: PositiveId
    revision_number: Annotated[int, Field(strict=True, ge=1)]
    kind: MemoryKind
    scope: MemoryScope
    scope_reference_id: PositiveId | None = None
    claim: Text
    confidence: Confidence
    sensitivity: Sensitivity
    visible_to: frozenset[Role]
    evidence: tuple[EvidenceLink, ...]
    provenance: Provenance
    valid_from: datetime
    valid_to: datetime | None = None
    expires_at: datetime | None = None
    supersedes_revision_id: PositiveId | None = None
    contradicts_revision_ids: frozenset[PositiveId] = frozenset()
    approval: Approval = "proposed"
    recorded_at: datetime

    @model_validator(mode="after")
    def _claims_rest_on_evidence(self) -> Self:
        if not self.evidence:
            raise ValueError("a memory with no evidence is an opinion; name what it rests on")
        return self

    @model_validator(mode="after")
    def _scopes_point_at_one_thing(self) -> Self:
        if self.scope == "global" and self.scope_reference_id is not None:
            raise ValueError("a global memory points at nothing")
        if self.scope in SCOPED_KINDS and self.scope_reference_id is None:
            raise ValueError(f"a {self.scope}-scoped memory must name which {self.scope}")
        return self

    @model_validator(mode="after")
    def _somebody_must_be_able_to_see_it(self) -> Self:
        if not self.visible_to:
            raise ValueError("a memory no role may see is a memory nobody can act on")
        return self

    @model_validator(mode="after")
    def _first_revisions_supersede_nothing(self) -> Self:
        if self.revision_number == 1 and self.supersedes_revision_id is not None:
            raise ValueError("the first revision of a memory has nothing to supersede")
        if self.revision_number > 1 and self.supersedes_revision_id is None:
            raise ValueError("a later revision must name the revision it supersedes")
        if self.supersedes_revision_id == self.revision_id:
            raise ValueError("a revision cannot supersede itself")
        return self

    @model_validator(mode="after")
    def _time_runs_forward(self) -> Self:
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("valid_to must come after valid_from")
        if self.expires_at is not None and self.expires_at <= self.valid_from:
            raise ValueError("expires_at must come after valid_from")
        return self

    @model_validator(mode="after")
    def _a_hypothesis_is_never_approved_into_a_fact(self) -> Self:
        if self.kind in KINDS_NEVER_APPROVED and self.approval == "approved":
            raise ValueError(
                "a hypothesis is a guess; confirming it means writing a semantic memory"
            )
        return self

    @model_validator(mode="after")
    def _episodes_do_not_expire(self) -> Self:
        if self.kind == "episodic" and self.expires_at is not None:
            raise ValueError("something that happened never becomes false; episodes do not expire")
        return self

    def in_force(self, *, at: datetime) -> bool:
        if at < self.valid_from:
            return False
        if self.valid_to is not None and at >= self.valid_to:
            return False
        return self.expires_at is None or at < self.expires_at


class MemoryLedger(_StrictModel):
    """Append-only. Every method that changes it returns a new ledger; none edits one."""

    revisions: tuple[MemoryRevision, ...] = ()

    @model_validator(mode="after")
    def _revision_ids_are_permanent(self) -> Self:
        seen: set[int] = set()
        for revision in self.revisions:
            if revision.revision_id in seen:
                raise ValueError(
                    f"revision {revision.revision_id} already exists and cannot be rewritten"
                )
            seen.add(revision.revision_id)
        return self

    def append(self, revision: MemoryRevision) -> MemoryLedger:
        if any(existing.revision_id == revision.revision_id for existing in self.revisions):
            raise MemoryError(
                f"revision {revision.revision_id} already exists and cannot be rewritten"
            )
        history = self.history(revision.memory_id)
        if not history:
            if revision.revision_number != 1:
                raise MemoryError("a memory starts at revision 1")
        else:
            latest = history[-1]
            if revision.revision_number != latest.revision_number + 1:
                expected = latest.revision_number + 1
                raise MemoryError(f"expected revision {expected}, got {revision.revision_number}")
            if revision.supersedes_revision_id != latest.revision_id:
                raise MemoryError("a new revision must supersede the current one, not an older one")
            if revision.kind != latest.kind:
                raise MemoryError("a memory keeps its kind; a different kind is a different memory")
        for contradicted in revision.contradicts_revision_ids:
            if not any(existing.revision_id == contradicted for existing in self.revisions):
                raise MemoryError(
                    f"cannot contradict revision {contradicted}: it is not in the ledger"
                )
        return MemoryLedger(revisions=(*self.revisions, revision))

    def history(self, memory_id: int) -> tuple[MemoryRevision, ...]:
        return tuple(r for r in self.revisions if r.memory_id == memory_id)

    def current(self, memory_id: int) -> MemoryRevision | None:
        history = self.history(memory_id)
        return history[-1] if history else None

    def visible(
        self,
        *,
        role: Role,
        at: datetime,
        ceiling: Sensitivity = "routine",
        scope: MemoryScope | None = None,
        scope_reference_id: int | None = None,
    ) -> tuple[MemoryRevision, ...]:
        """Current, approved, in-force revisions this role may read at this ceiling."""

        limit = SENSITIVITY_RANK[ceiling]
        out: list[MemoryRevision] = []
        for memory_id in _unique(r.memory_id for r in self.revisions):
            revision = self.current(memory_id)
            if revision is None or revision.approval != "approved":
                continue
            if role not in revision.visible_to:
                continue
            if SENSITIVITY_RANK[revision.sensitivity] > limit:
                continue
            if not revision.in_force(at=at):
                continue
            if scope is not None and (
                revision.scope != scope or revision.scope_reference_id != scope_reference_id
            ):
                continue
            out.append(revision)
        return tuple(out)


def _unique(ids: Iterable[int]) -> tuple[int, ...]:
    seen: dict[int, None] = {}
    for value in ids:
        seen.setdefault(value, None)
    return tuple(seen)


__all__ = [
    "KINDS_NEVER_APPROVED",
    "LEDGER_KINDS",
    "SCOPED_KINDS",
    "SENSITIVITY_RANK",
    "Approval",
    "EvidenceKind",
    "EvidenceLink",
    "MemoryError",
    "MemoryKind",
    "MemoryLedger",
    "MemoryRevision",
    "MemoryScope",
    "Provenance",
    "Role",
    "Sensitivity",
]

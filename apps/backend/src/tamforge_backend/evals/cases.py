"""Versioned, synthetic evaluation cases that live in Git and never contain a real learner.

A case is a seeded ledger and a question asked by one role for one owner at one ceiling,
with three answers written down in advance: the revisions that must come back, the ones
that would be relevant if they did, and the ones that must never come back. The fixture is
hashed so a report can say exactly which cases it ran, and the evaluator is versioned so
a change in scoring is visible as a change in the report, not as a silent shift.
"""

from __future__ import annotations

import json
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field
from tamforge_protocol.memory import (
    EvidenceLink,
    MemoryLedger,
    MemoryRevision,
    MemoryScope,
    Provenance,
    Role,
    Sensitivity,
)

EVALUATOR_VERSION: Final = "memory-eval-v1"

PositiveId = Annotated[int, Field(strict=True, gt=0)]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SeedRevision(_StrictModel):
    """The fixture's compact form of a ledger revision; expanded by `ledger()`."""

    memory_id: PositiveId
    revision_id: PositiveId
    owner_id: PositiveId
    claim: str
    kind: Literal["episodic", "semantic", "hypothesis", "procedural"] = "semantic"
    sensitivity: Sensitivity = "routine"
    visible_to: tuple[Role, ...] = ("planner", "tutor", "coach", "reviewer", "analyst")
    scope: MemoryScope = "global"
    scope_reference_id: PositiveId | None = None
    approval: Literal["proposed", "approved"] = "approved"
    supersedes_revision_id: PositiveId | None = None
    revision_number: Annotated[int, Field(strict=True, ge=1)] = 1
    expires_at: datetime | None = None


class MemoryQuery(_StrictModel):
    owner_id: PositiveId
    role: Role
    ceiling: Sensitivity
    text: str
    limit: Annotated[int, Field(strict=True, ge=1, le=32)] = 8
    scope: MemoryScope | None = None
    scope_reference_id: PositiveId | None = None


class MemoryCase(_StrictModel):
    case_id: Annotated[str, Field(pattern=r"^[a-z0-9-]{1,64}$")]
    query: MemoryQuery
    required_revision_ids: tuple[PositiveId, ...]
    relevant_revision_ids: tuple[PositiveId, ...]
    forbidden_revision_ids: tuple[PositiveId, ...]


class MemoryCaseSet(_StrictModel):
    fixture_version: Literal["memory-cases-v1"]
    recorded_at: datetime
    seed: tuple[SeedRevision, ...]
    cases: tuple[MemoryCase, ...]
    fixture_sha256: str = ""

    def ledger(self) -> MemoryLedger:
        book = MemoryLedger()
        for s in self.seed:
            book = book.append(
                MemoryRevision(
                    memory_id=s.memory_id,
                    revision_id=s.revision_id,
                    revision_number=s.revision_number,
                    kind=s.kind,
                    scope=s.scope,
                    scope_reference_id=s.scope_reference_id,
                    claim=s.claim,
                    confidence=0.7,
                    sensitivity=s.sensitivity,
                    visible_to=frozenset(s.visible_to),
                    evidence=(EvidenceLink(kind="activity", reference_id=1),),
                    provenance=Provenance(author="tutor", model_run_id=1),
                    valid_from=self.recorded_at,
                    expires_at=s.expires_at,
                    supersedes_revision_id=s.supersedes_revision_id,
                    approval=s.approval,
                    recorded_at=self.recorded_at,
                )
            )
        return book

    def owner_of(self) -> dict[int, int]:
        return {s.memory_id: s.owner_id for s in self.seed}


def load_memory_cases(path: Path) -> MemoryCaseSet:
    raw = path.read_bytes()
    body = json.loads(raw)
    body["fixture_sha256"] = sha256(raw).hexdigest()
    return MemoryCaseSet.model_validate(body)


__all__ = [
    "EVALUATOR_VERSION",
    "MemoryCase",
    "MemoryCaseSet",
    "MemoryQuery",
    "SeedRevision",
    "load_memory_cases",
]

"""Relational first, vectors second, and every selection written down.

A similarity search that runs before the filters is a leak with a ranking function: the
nearest neighbour to a coaching question may be a claim from a real interview, or a
memory another role wrote for itself. So retrieval here asks the ledger first. The owner,
the role asking, the sensitivity ceiling of the context, the scope, approval and time are
applied by `MemoryLedger.visible` before a single vector is compared, and what comes out
of that is the candidate set. Ranking only reorders candidates; it never adds one.

The result is not a text blob. Every selected memory comes back as its revision id, the
memory it belongs to, the sensitivity it carries, the score components that put it where
it is, and a reason code, so the model run that consumed it can record exactly which
revisions it saw. The Interviewer asks and gets nothing, by construction of its role
visibility, and that empty answer is still recorded.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal

from tamforge_protocol.memory import (
    SENSITIVITY_RANK,
    MemoryLedger,
    MemoryRevision,
    MemoryScope,
    Role,
    Sensitivity,
)

from .embeddings import EmbeddingStore, content_hash

ReasonCode = Literal["required_scope", "vector_neighbour", "text_match", "recent"]

# Weights are versioned with the contract; retrieval is deterministic for a fixed store.
WEIGHT_SIMILARITY: Final = 0.6
WEIGHT_TEXT: Final = 0.25
WEIGHT_FRESHNESS: Final = 0.15
FRESHNESS_HALF_LIFE_DAYS: Final = 30.0
MAX_PER_MEMORY: Final = 1


class RetrievalError(ValueError):
    """A query that would bypass a filter."""


@dataclass(frozen=True, slots=True)
class RetrievalQuery:
    owner_id: int
    role: Role
    ceiling: Sensitivity
    text: str
    at: datetime
    limit: int = 8
    scope: MemoryScope | None = None
    scope_reference_id: int | None = None
    query_vector: tuple[float, ...] | None = None

    def __post_init__(self) -> None:
        if self.owner_id <= 0:
            raise RetrievalError("retrieval is always for one owner")
        if self.limit <= 0:
            raise RetrievalError("limit must be positive")
        if self.ceiling not in SENSITIVITY_RANK:
            raise RetrievalError("unknown sensitivity ceiling")


@dataclass(frozen=True, slots=True)
class SelectedMemory:
    memory_id: int
    revision_id: int
    sensitivity: Sensitivity
    reason: ReasonCode
    similarity: float
    text_overlap: float
    freshness: float
    score: float


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    owner_id: int
    role: Role
    ceiling: Sensitivity
    candidates_after_filters: int
    selected: tuple[SelectedMemory, ...]

    @property
    def selected_revision_ids(self) -> tuple[int, ...]:
        return tuple(s.revision_id for s in self.selected)


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return 0.0 if na == 0 or nb == 0 else max(-1.0, min(1.0, dot / (na * nb)))


def _overlap(query: str, claim: str) -> float:
    q = {t for t in query.casefold().split() if len(t) > 2}
    c = {t for t in claim.casefold().split() if len(t) > 2}
    return 0.0 if not q else len(q & c) / len(q)


def _freshness(revision: MemoryRevision, at: datetime) -> float:
    age_days = max(0.0, (at - revision.recorded_at).total_seconds() / 86_400)
    return float(0.5 ** (age_days / FRESHNESS_HALF_LIFE_DAYS))


def retrieve(
    ledger: MemoryLedger,
    query: RetrievalQuery,
    *,
    owner_of: dict[int, int],
    embeddings: EmbeddingStore,
    model_key: str,
) -> RetrievalResult:
    """Filter by owner, role, sensitivity, scope, approval and time; then rank what is left."""
    visible = ledger.visible(
        role=query.role,
        at=query.at,
        ceiling=query.ceiling,
        scope=query.scope,
        scope_reference_id=query.scope_reference_id,
    )
    # Owner is the hardest filter of all and the ledger does not know it, so it is applied
    # here from the memory-to-owner map before anything is scored.
    candidates = tuple(r for r in visible if owner_of.get(r.memory_id) == query.owner_id)

    scored: list[SelectedMemory] = []
    for revision in candidates:
        similarity = 0.0
        if query.query_vector is not None:
            record = embeddings.get(model_key, content_hash(revision.claim))
            if record is not None:
                similarity = max(0.0, _cosine(query.query_vector, record.vector))
        overlap = _overlap(query.text, revision.claim)
        freshness = _freshness(revision, query.at)
        score = (
            WEIGHT_SIMILARITY * similarity + WEIGHT_TEXT * overlap + WEIGHT_FRESHNESS * freshness
        )
        if query.scope is not None:
            reason: ReasonCode = "required_scope"
        elif similarity >= overlap and similarity > 0:
            reason = "vector_neighbour"
        elif overlap > 0:
            reason = "text_match"
        else:
            reason = "recent"
        scored.append(
            SelectedMemory(
                memory_id=revision.memory_id,
                revision_id=revision.revision_id,
                sensitivity=revision.sensitivity,
                reason=reason,
                similarity=round(similarity, 6),
                text_overlap=round(overlap, 6),
                freshness=round(freshness, 6),
                score=round(score, 6),
            )
        )
    scored.sort(key=lambda s: (-s.score, s.revision_id))
    return RetrievalResult(
        owner_id=query.owner_id,
        role=query.role,
        ceiling=query.ceiling,
        candidates_after_filters=len(candidates),
        selected=tuple(scored[: query.limit]),
    )


__all__ = [
    "ReasonCode",
    "RetrievalError",
    "RetrievalQuery",
    "RetrievalResult",
    "SelectedMemory",
    "retrieve",
]

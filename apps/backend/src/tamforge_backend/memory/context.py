"""The smallest role-safe packet, in a fixed order, with a manifest of what was left out.

A model run does not get "the learner's memory". It gets a packet: the current assignment
first, then the prompt or source or case or interview it is working on, then the rubric
contract, then the two corrections the learner is currently acting on, then related
attempts and evidence, then the active company and role, then verified role memory, and
only if there is still room, broader history. That order is the approved hierarchy and it
does not move; a token budget trims from the bottom, never from the top.

Every candidate source is decided, and the decision is written down. What went in is
listed with its tier and position; what stayed out is listed with the one reason it stayed
out: the role may not see it, it is above the sensitivity ceiling, it belongs to another
owner or another company, it is no longer current, the Coach must not see the answer it
is coaching, or the budget ran out. The Interviewer is excluded from memory entirely and
its manifest says so for every memory source, so an empty packet is still an audited one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal

from tamforge_protocol.memory import SENSITIVITY_RANK, MemoryLedger, Role, Sensitivity

Tier = Literal[
    "current_assignment",
    "current_subject",
    "rubric_contract",
    "active_corrections",
    "related_evidence",
    "active_company",
    "verified_role_memory",
    "broader_history",
]
# The approved hierarchy. Position in this tuple is the sort key; nothing else reorders it.
HIERARCHY: Final[tuple[Tier, ...]] = (
    "current_assignment",
    "current_subject",
    "rubric_contract",
    "active_corrections",
    "related_evidence",
    "active_company",
    "verified_role_memory",
    "broader_history",
)

ExclusionReason = Literal[
    "interviewer_excluded",
    "role_not_allowed",
    "sensitivity_above_ceiling",
    "other_owner",
    "other_company",
    "not_current",
    "coach_current_answer_hidden",
    "over_budget",
]

# Which tiers each role may receive at all. The Interviewer receives its question bank
# through its own contract, never through a memory packet.
TIERS_BY_ROLE: Final[dict[Role, frozenset[Tier]]] = {
    "planner": frozenset(HIERARCHY),
    "tutor": frozenset(HIERARCHY) - {"broader_history"},
    "coach": frozenset(HIERARCHY),
    "reviewer": frozenset(HIERARCHY) - {"active_company", "broader_history"},
    "analyst": frozenset(HIERARCHY),
    "interviewer": frozenset(),
}

MAX_ACTIVE_CORRECTIONS: Final = 2
CHARS_PER_TOKEN: Final = 4


class ContextError(ValueError):
    """A request that could not be honoured without breaking a rule."""


@dataclass(frozen=True, slots=True)
class ContextSource:
    """One candidate for the packet. Memory sources name their ledger revision."""

    source_id: str
    tier: Tier
    owner_id: int
    text: str
    sensitivity: Sensitivity = "routine"
    company_id: int | None = None
    revision_id: int | None = None
    is_current_answer: bool = False

    @property
    def tokens(self) -> int:
        return max(1, len(self.text) // CHARS_PER_TOKEN)


@dataclass(frozen=True, slots=True)
class ContextRequest:
    owner_id: int
    role: Role
    ceiling: Sensitivity
    at: datetime
    token_budget: int
    company_id: int | None = None

    def __post_init__(self) -> None:
        if self.owner_id <= 0:
            raise ContextError("a packet is always for one owner")
        if self.token_budget <= 0:
            raise ContextError("token budget must be positive")


@dataclass(frozen=True, slots=True)
class Included:
    source_id: str
    tier: Tier
    position: int
    tokens: int
    revision_id: int | None


@dataclass(frozen=True, slots=True)
class Excluded:
    source_id: str
    tier: Tier
    reason: ExclusionReason


@dataclass(frozen=True, slots=True)
class ContextPacket:
    owner_id: int
    role: Role
    ceiling: Sensitivity
    token_budget: int
    tokens_used: int
    included: tuple[Included, ...]
    excluded: tuple[Excluded, ...]

    @property
    def manifest(self) -> tuple[tuple[str, str], ...]:
        """Every considered source, in decision order: (source_id, 'included' | reason)."""
        rows = [(i.source_id, "included") for i in self.included]
        rows += [(e.source_id, e.reason) for e in self.excluded]
        return tuple(sorted(rows))

    @property
    def sources_seen(self) -> int:
        return len(self.included) + len(self.excluded)


def _exclusion(
    source: ContextSource, request: ContextRequest, current_revisions: frozenset[int]
) -> ExclusionReason | None:
    if request.role == "interviewer":
        return "interviewer_excluded"
    if source.tier not in TIERS_BY_ROLE[request.role]:
        return "role_not_allowed"
    if source.owner_id != request.owner_id:
        return "other_owner"
    if SENSITIVITY_RANK[source.sensitivity] > SENSITIVITY_RANK[request.ceiling]:
        return "sensitivity_above_ceiling"
    if (
        source.company_id is not None
        and request.company_id is not None
        and source.company_id != request.company_id
    ):
        return "other_company"
    if source.revision_id is not None and source.revision_id not in current_revisions:
        return "not_current"
    if request.role == "coach" and source.is_current_answer:
        return "coach_current_answer_hidden"
    return None


def build_context(
    sources: tuple[ContextSource, ...],
    request: ContextRequest,
    *,
    ledger: MemoryLedger,
) -> ContextPacket:
    """Decide every source, order the survivors by hierarchy, trim from the bottom."""
    current_revisions = frozenset(
        r.revision_id
        for r in ledger.visible(role=request.role, at=request.at, ceiling=request.ceiling)
    )
    excluded: list[Excluded] = []
    survivors: list[ContextSource] = []
    for source in sources:
        reason = _exclusion(source, request, current_revisions)
        if reason is None:
            survivors.append(source)
        else:
            excluded.append(Excluded(source.source_id, source.tier, reason))

    # Hierarchy first, then a stable key so two runs produce the same packet.
    survivors.sort(key=lambda s: (HIERARCHY.index(s.tier), s.source_id))
    corrections_taken = 0
    included: list[Included] = []
    used = 0
    for source in survivors:
        if source.tier == "active_corrections":
            if corrections_taken >= MAX_ACTIVE_CORRECTIONS:
                excluded.append(Excluded(source.source_id, source.tier, "over_budget"))
                continue
            corrections_taken += 1
        if used + source.tokens > request.token_budget:
            excluded.append(Excluded(source.source_id, source.tier, "over_budget"))
            continue
        used += source.tokens
        included.append(
            Included(
                source.source_id, source.tier, len(included), source.tokens, source.revision_id
            )
        )
    return ContextPacket(
        owner_id=request.owner_id,
        role=request.role,
        ceiling=request.ceiling,
        token_budget=request.token_budget,
        tokens_used=used,
        included=tuple(included),
        excluded=tuple(excluded),
    )


__all__ = [
    "HIERARCHY",
    "MAX_ACTIVE_CORRECTIONS",
    "TIERS_BY_ROLE",
    "ContextError",
    "ContextPacket",
    "ContextRequest",
    "ContextSource",
    "Excluded",
    "ExclusionReason",
    "Included",
    "Tier",
    "build_context",
]

"""Portfolio triage: five dimensions, a 0-20 composite, and no room for volume.

Every dimension points the same way. Higher means more urgent, which is why the
workaround factor is recorded as a gap rather than a quality: a good workaround makes a
problem less urgent, and mixing directions inside one sum is how a composite quietly
stops meaning anything.

What is deliberately not a dimension is how large or how loud the account is. Account
size has no field here at all, so the biggest customer cannot become priority one by
arithmetic; it becomes priority one only when its impact, risk, time sensitivity,
workaround gap and strategic context actually say so. That absence is the feature.

Every score carries the rationale that produced it, and rescoring produces a new score
beside the old one rather than editing it. Priorities that change without a trace are
priorities nobody can argue with later.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from typing import Literal

# Five dimensions, each on the same 0-4 scale the rubrics use, summing to 0-20.
PORTFOLIO_DIMENSIONS: tuple[str, ...] = (
    "impact",
    "risk",
    "time_sensitivity",
    "workaround_gap",
    "strategic_context",
)
DIMENSION_MAX = 4
COMPOSITE_MAX = DIMENSION_MAX * len(PORTFOLIO_DIMENSIONS)

DiagnosticConfidence = Literal["low", "medium", "high"]

# Things a triage may decide to do. Doing nothing on purpose is one of them, and
# protected proactive work is another, because a queue that only reacts never gets ahead.
TriageAction = Literal[
    "work_now",
    "delegate",
    "escalate",
    "communicate_and_wait",
    "protected_proactive",
]


class PortfolioError(ValueError):
    """A score or an ordering that cannot be justified."""


@dataclass(frozen=True, slots=True)
class PortfolioScore:
    impact: int
    risk: int
    time_sensitivity: int
    workaround_gap: int
    strategic_context: int
    rationale: str
    diagnostic_confidence: DiagnosticConfidence

    def __post_init__(self) -> None:
        for dimension in PORTFOLIO_DIMENSIONS:
            value = getattr(self, dimension)
            if type(value) is not int or not 0 <= value <= DIMENSION_MAX:
                raise PortfolioError(f"{dimension} must be an integer from 0 to {DIMENSION_MAX}")
        if not self.rationale.strip():
            raise PortfolioError("a score carries the reasoning that produced it")

    @property
    def composite(self) -> int:
        """Derived, so a stored total can never disagree with its dimensions."""
        return sum(getattr(self, dimension) for dimension in PORTFOLIO_DIMENSIONS)


@dataclass(frozen=True, slots=True)
class PortfolioItem:
    item_id: str
    account: str
    score: PortfolioScore
    action: TriageAction

    def __post_init__(self) -> None:
        if not self.item_id.strip() or not self.account.strip():
            raise PortfolioError("an item names itself and whose it is")


def prioritize(items: Iterable[PortfolioItem]) -> tuple[PortfolioItem, ...]:
    """Order by composite, highest first, with the item id breaking ties.

    The tie-break is the id rather than the account, so ordering is reproducible and no
    account gets a systematic advantage from how the list happened to be built.
    """
    ordered = sorted(items, key=lambda item: (-item.score.composite, item.item_id))
    ids = [item.item_id for item in ordered]
    if len(set(ids)) != len(ids):
        raise PortfolioError("an item appears once in a portfolio")
    return tuple(ordered)


def rescore(item: PortfolioItem, score: PortfolioScore) -> PortfolioItem:
    """Return the item at its new score. The one passed in is untouched."""
    return replace(item, score=score)


def reprioritize(
    items: Sequence[PortfolioItem], *, rescored: PortfolioItem
) -> tuple[PortfolioItem, ...]:
    """Fold one changed item back into the order without rebuilding the rest."""
    if not any(item.item_id == rescored.item_id for item in items):
        raise PortfolioError("that item is not in this portfolio")
    return prioritize(
        [rescored if item.item_id == rescored.item_id else item for item in items]
    )


__all__ = [
    "COMPOSITE_MAX",
    "DIMENSION_MAX",
    "PORTFOLIO_DIMENSIONS",
    "DiagnosticConfidence",
    "PortfolioError",
    "PortfolioItem",
    "PortfolioScore",
    "TriageAction",
    "prioritize",
    "reprioritize",
    "rescore",
]

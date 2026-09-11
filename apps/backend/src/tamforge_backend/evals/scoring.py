"""Code-enforced thresholds. Nothing here reads prose quality.

Recall is the share of required revisions that came back. Relevance is the share of what
came back that was on the relevant list. Provenance is whether every selected item names
a revision. Leakage is any forbidden revision appearing at all, and it is counted, not
averaged: one leak across the whole set is a failed set.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from ..memory.retrieval import RetrievalResult
from .cases import MemoryCase


@dataclass(frozen=True, slots=True)
class Thresholds:
    required_recall: float
    top_k_relevance: float
    max_leaks: int


# Plan Task 28: required recall at least 95%, top-k relevance at least 90%, zero leakage.
THRESHOLDS: Final = Thresholds(required_recall=0.95, top_k_relevance=0.90, max_leaks=0)


@dataclass(frozen=True, slots=True)
class CaseScore:
    case_id: str
    required: int
    recalled: int
    selected: int
    relevant_selected: int
    leaked_revision_ids: tuple[int, ...]
    provenance_complete: bool

    @property
    def recall(self) -> float:
        return 1.0 if self.required == 0 else self.recalled / self.required

    @property
    def relevance(self) -> float:
        return 1.0 if self.selected == 0 else self.relevant_selected / self.selected


def score_case(case: MemoryCase, result: RetrievalResult) -> CaseScore:
    selected_ids = set(result.selected_revision_ids)
    required = set(case.required_revision_ids)
    relevant = set(case.relevant_revision_ids) | required
    forbidden = set(case.forbidden_revision_ids)
    return CaseScore(
        case_id=case.case_id,
        required=len(required),
        recalled=len(required & selected_ids),
        selected=len(selected_ids),
        relevant_selected=len(relevant & selected_ids),
        leaked_revision_ids=tuple(sorted(forbidden & selected_ids)),
        provenance_complete=all(s.revision_id > 0 and s.memory_id > 0 for s in result.selected),
    )


__all__ = ["THRESHOLDS", "CaseScore", "Thresholds", "score_case"]

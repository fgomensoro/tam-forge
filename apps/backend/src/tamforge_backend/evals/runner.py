"""Run every case against the real retrieval path and say, with numbers, whether it passed."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from ..memory.embeddings import EmbeddingStore
from ..memory.retrieval import RetrievalQuery, retrieve
from .cases import EVALUATOR_VERSION, MemoryCaseSet
from .scoring import THRESHOLDS, CaseScore, Thresholds, score_case


@dataclass(frozen=True, slots=True)
class MemoryEvalReport:
    evaluator_version: str
    fixture_version: str
    fixture_sha256: str
    thresholds: Thresholds
    scores: tuple[CaseScore, ...]

    @property
    def required_recall(self) -> float:
        required = sum(s.required for s in self.scores)
        return 1.0 if required == 0 else sum(s.recalled for s in self.scores) / required

    @property
    def top_k_relevance(self) -> float:
        selected = sum(s.selected for s in self.scores)
        return 1.0 if selected == 0 else sum(s.relevant_selected for s in self.scores) / selected

    @property
    def leaks(self) -> tuple[tuple[str, int], ...]:
        return tuple((s.case_id, rid) for s in self.scores for rid in s.leaked_revision_ids)

    @property
    def provenance_complete(self) -> bool:
        return all(s.provenance_complete for s in self.scores)

    @property
    def passed(self) -> bool:
        return (
            self.required_recall >= self.thresholds.required_recall
            and self.top_k_relevance >= self.thresholds.top_k_relevance
            and len(self.leaks) <= self.thresholds.max_leaks
            and self.provenance_complete
        )

    def render(self) -> str:
        body = {
            "evaluator_version": self.evaluator_version,
            "fixture_version": self.fixture_version,
            "fixture_sha256": self.fixture_sha256,
            "thresholds": {
                "required_recall": self.thresholds.required_recall,
                "top_k_relevance": self.thresholds.top_k_relevance,
                "max_leaks": self.thresholds.max_leaks,
            },
            "required_recall": round(self.required_recall, 4),
            "top_k_relevance": round(self.top_k_relevance, 4),
            "leaks": [{"case_id": c, "revision_id": r} for c, r in self.leaks],
            "provenance_complete": self.provenance_complete,
            "passed": self.passed,
            "cases": [
                {
                    "case_id": s.case_id,
                    "recall": round(s.recall, 4),
                    "relevance": round(s.relevance, 4),
                    "selected": s.selected,
                    "leaked": list(s.leaked_revision_ids),
                }
                for s in self.scores
            ],
        }
        return json.dumps(body, indent=2, sort_keys=True) + "\n"


def run_memory_cases(
    cases: MemoryCaseSet, *, at: datetime, thresholds: Thresholds = THRESHOLDS
) -> MemoryEvalReport:
    ledger = cases.ledger()
    owner_of = cases.owner_of()
    scores: list[CaseScore] = []
    for case in cases.cases:
        query = RetrievalQuery(
            owner_id=case.query.owner_id,
            role=case.query.role,
            ceiling=case.query.ceiling,
            text=case.query.text,
            at=at,
            limit=case.query.limit,
            scope=case.query.scope,
            scope_reference_id=case.query.scope_reference_id,
        )
        result = retrieve(
            ledger, query, owner_of=owner_of, embeddings=EmbeddingStore(), model_key="none"
        )
        scores.append(score_case(case, result))
    return MemoryEvalReport(
        evaluator_version=EVALUATOR_VERSION,
        fixture_version=cases.fixture_version,
        fixture_sha256=cases.fixture_sha256,
        thresholds=thresholds,
        scores=tuple(scores),
    )


__all__ = ["MemoryEvalReport", "run_memory_cases"]

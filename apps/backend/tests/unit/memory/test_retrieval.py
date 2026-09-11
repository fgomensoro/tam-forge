"""Retrieval: the filters run first, ranking only reorders, and every selection is recorded."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from tamforge_backend.memory import (
    EmbeddingRecord,
    EmbeddingStore,
    RetrievalError,
    RetrievalQuery,
    content_hash,
    retrieve,
)
from tamforge_protocol.memory import EvidenceLink, MemoryLedger, MemoryRevision, Provenance

NOW = datetime(2026, 9, 12, 15, tzinfo=UTC)
MODEL = "bge-small-en@v1.5"


def revision(memory_id: int, **overrides: object) -> MemoryRevision:
    data: dict[str, object] = {
        "memory_id": memory_id,
        "revision_id": memory_id * 100,
        "revision_number": 1,
        "kind": "semantic",
        "scope": "global",
        "claim": f"claim {memory_id}",
        "confidence": 0.7,
        "sensitivity": "routine",
        "visible_to": frozenset({"tutor", "coach"}),
        "evidence": (EvidenceLink(kind="activity", reference_id=8),),
        "provenance": Provenance(author="tutor", model_run_id=3),
        "valid_from": NOW - timedelta(days=10),
        "approval": "approved",
        "recorded_at": NOW - timedelta(days=10),
    }
    data.update(overrides)
    return MemoryRevision.model_validate(data)


def ledger(*revisions: MemoryRevision) -> MemoryLedger:
    out = MemoryLedger()
    for r in revisions:
        out = out.append(r)
    return out


def query(**overrides: object) -> RetrievalQuery:
    data: dict[str, object] = {
        "owner_id": 1,
        "role": "coach",
        "ceiling": "routine",
        "text": "how does the learner prefer to practice pace",
        "at": NOW,
    }
    data.update(overrides)
    return RetrievalQuery(**data)  # type: ignore[arg-type]


def embedding(revision_id: int, claim: str, vector: tuple[float, ...]) -> EmbeddingRecord:
    return EmbeddingRecord(
        revision_id=revision_id,
        content_sha256=content_hash(claim),
        model_key=MODEL,
        dimensions=len(vector),
        vector=vector,
        generated_at=NOW,
    )


def test_owner_role_and_sensitivity_filters_run_before_any_ranking() -> None:
    store = EmbeddingStore()
    # The forbidden memories are the closest vectors; they must never appear.
    for mid, claim in ((1, "claim 1"), (2, "claim 2"), (3, "claim 3"), (4, "claim 4")):
        store.put(embedding(mid * 100, claim, (1.0, 0.0)))
    book = ledger(
        revision(1),
        revision(2, visible_to=frozenset({"analyst"})),
        revision(3, sensitivity="real_interview"),
        revision(4),
    )
    result = retrieve(
        book,
        query(query_vector=(1.0, 0.0)),
        owner_of={1: 1, 2: 1, 3: 1, 4: 2},
        embeddings=store,
        model_key=MODEL,
    )
    assert result.candidates_after_filters == 1
    assert result.selected_revision_ids == (100,)


def test_the_interviewer_gets_nothing_and_that_is_recorded() -> None:
    book = ledger(revision(1), revision(2))
    result = retrieve(
        book,
        query(role="interviewer"),
        owner_of={1: 1, 2: 1},
        embeddings=EmbeddingStore(),
        model_key=MODEL,
    )
    assert (
        result.role == "interviewer"
        and result.selected == ()
        and result.candidates_after_filters == 0
    )


def test_raising_the_ceiling_admits_more_but_never_another_owner() -> None:
    book = ledger(revision(1, sensitivity="personal"), revision(2, sensitivity="personal"))
    result = retrieve(
        book,
        query(ceiling="personal"),
        owner_of={1: 1, 2: 9},
        embeddings=EmbeddingStore(),
        model_key=MODEL,
    )
    assert result.selected_revision_ids == (100,)


def test_scope_narrows_to_one_thing_and_marks_the_reason() -> None:
    book = ledger(
        revision(1, scope="opportunity", scope_reference_id=4),
        revision(2, scope="opportunity", scope_reference_id=5),
        revision(3),
    )
    result = retrieve(
        book,
        query(scope="opportunity", scope_reference_id=4),
        owner_of={1: 1, 2: 1, 3: 1},
        embeddings=EmbeddingStore(),
        model_key=MODEL,
    )
    (only,) = result.selected
    assert (only.memory_id, only.reason) == (1, "required_scope")


def test_vectors_reorder_candidates_and_the_components_are_reported() -> None:
    store = EmbeddingStore()
    store.put(embedding(100, "claim 1", (0.0, 1.0)))
    store.put(embedding(200, "claim 2", (1.0, 0.0)))
    book = ledger(revision(1), revision(2))
    result = retrieve(
        book,
        query(query_vector=(1.0, 0.0)),
        owner_of={1: 1, 2: 1},
        embeddings=store,
        model_key=MODEL,
    )
    first, second = result.selected
    assert (first.memory_id, first.reason, first.similarity) == (2, "vector_neighbour", 1.0)
    assert (second.memory_id, second.similarity) == (1, 0.0)
    assert first.score > second.score


def test_text_overlap_and_freshness_rank_when_there_is_no_vector() -> None:
    book = ledger(
        revision(1, claim="the learner likes to practice pace with a timer"),
        revision(2, claim="unrelated note about invoices"),
        revision(3, claim="another unrelated note", recorded_at=NOW - timedelta(days=1)),
    )
    result = retrieve(
        book, query(), owner_of={1: 1, 2: 1, 3: 1}, embeddings=EmbeddingStore(), model_key=MODEL
    )
    assert [s.memory_id for s in result.selected] == [1, 3, 2]
    assert result.selected[0].reason == "text_match" and result.selected[1].reason == "recent"


def test_only_the_current_revision_of_a_memory_is_ever_selected() -> None:
    old = revision(1, claim="old claim")
    new = MemoryRevision.model_validate(
        {
            **old.model_dump(),
            "revision_id": 101,
            "revision_number": 2,
            "supersedes_revision_id": 100,
            "claim": "new claim",
        }
    )
    book = ledger(old, new)
    result = retrieve(
        book, query(text="old claim"), owner_of={1: 1}, embeddings=EmbeddingStore(), model_key=MODEL
    )
    assert result.selected_revision_ids == (101,)


def test_the_limit_bounds_the_selection_and_the_order_is_deterministic() -> None:
    book = ledger(*[revision(i) for i in range(1, 7)])
    result = retrieve(
        book,
        query(limit=3),
        owner_of={i: 1 for i in range(1, 7)},
        embeddings=EmbeddingStore(),
        model_key=MODEL,
    )
    assert len(result.selected) == 3
    again = retrieve(
        book,
        query(limit=3),
        owner_of={i: 1 for i in range(1, 7)},
        embeddings=EmbeddingStore(),
        model_key=MODEL,
    )
    assert again.selected == result.selected


def test_a_query_without_an_owner_or_with_a_bad_limit_is_refused() -> None:
    with pytest.raises(RetrievalError, match="one owner"):
        query(owner_id=0)
    with pytest.raises(RetrievalError, match="limit"):
        query(limit=0)


def test_the_result_is_ids_and_components_never_a_text_blob() -> None:
    book = ledger(revision(1, claim="a very specific sentence"))
    result = retrieve(book, query(), owner_of={1: 1}, embeddings=EmbeddingStore(), model_key=MODEL)
    (selected,) = result.selected
    assert not hasattr(selected, "claim") and not hasattr(selected, "text")
    assert selected.sensitivity == "routine" and selected.revision_id == 100

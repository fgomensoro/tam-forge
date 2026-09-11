"""Embeddings: local only, pinned, deduplicated, and never for what must not be embedded."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import pytest
from tamforge_backend.memory import (
    EmbeddingError,
    EmbeddingModelPin,
    EmbeddingStore,
    LocalEmbeddingAdapter,
    content_hash,
    embeddable,
)
from tamforge_protocol.memory import EvidenceLink, MemoryRevision, Provenance

NOW = datetime(2026, 9, 12, 15, tzinfo=UTC)
PIN = EmbeddingModelPin(
    name="bge-small-en", revision="v1.5", dimensions=4, artifact_sha256="a" * 64
)
OTHER = EmbeddingModelPin(
    name="bge-small-en", revision="v2.0", dimensions=4, artifact_sha256="b" * 64
)


class FakeEmbedder:
    """Deterministic: a vector from the text's character counts. Records every call."""

    def __init__(self, pin: EmbeddingModelPin = PIN, *, dimensions: int | None = None) -> None:
        self._pin = pin
        self._dimensions = dimensions or pin.dimensions
        self.calls: list[list[str]] = []

    @property
    def pin(self) -> EmbeddingModelPin:
        return self._pin

    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        self.calls.append(list(texts))
        out = []
        for text in texts:
            base = [float(text.count(c) + 1) for c in "aeio"]
            out.append((base + [1.0] * self._dimensions)[: self._dimensions])
        return out


def revision(**overrides: object) -> MemoryRevision:
    data: dict[str, object] = {
        "memory_id": 1,
        "revision_id": 100,
        "revision_number": 1,
        "kind": "semantic",
        "scope": "global",
        "claim": "Prefers worked examples before abstract rules.",
        "confidence": 0.7,
        "sensitivity": "routine",
        "visible_to": frozenset({"tutor", "coach"}),
        "evidence": (EvidenceLink(kind="activity", reference_id=8),),
        "provenance": Provenance(author="tutor", model_run_id=3),
        "valid_from": NOW,
        "approval": "approved",
        "recorded_at": NOW,
    }
    data.update(overrides)
    return MemoryRevision.model_validate(data)


def adapter(
    embedder: FakeEmbedder | None = None, **kwargs: object
) -> tuple[LocalEmbeddingAdapter, EmbeddingStore, FakeEmbedder]:
    embedder = embedder or FakeEmbedder()
    store = EmbeddingStore()
    return LocalEmbeddingAdapter(embedder, store, expected=PIN, **kwargs), store, embedder  # type: ignore[arg-type]


def test_vectors_are_unit_length_and_carry_model_dimension_and_time() -> None:
    a, store, _ = adapter()
    outcome = a.embed_revisions([revision()], now=NOW)
    (record,) = outcome.embedded
    assert abs(sum(v * v for v in record.vector) - 1.0) < 1e-9
    assert (record.model_key, record.dimensions, record.generated_at) == (
        "bge-small-en@v1.5",
        4,
        NOW,
    )
    assert store.get("bge-small-en@v1.5", content_hash(revision().claim)) == record


def test_the_same_claim_is_embedded_once_per_model() -> None:
    a, _, embedder = adapter()
    first = a.embed_revisions([revision()], now=NOW)
    second = a.embed_revisions(
        [
            revision(
                memory_id=2,
                revision_id=200,
                claim="  prefers WORKED examples before abstract rules. ",
            )
        ],
        now=NOW,
    )
    assert len(first.embedded) == 1 and second.embedded == () and len(second.reused) == 1
    assert len(embedder.calls) == 1


def test_a_different_model_revision_makes_every_stored_vector_stale() -> None:
    a, store, _ = adapter()
    a.embed_revisions([revision()], now=NOW)
    upgraded = LocalEmbeddingAdapter(FakeEmbedder(OTHER), store, expected=OTHER)
    assert [r.model_key for r in upgraded.stale_records()] == ["bge-small-en@v1.5"]
    outcome = upgraded.embed_revisions([revision()], now=NOW)
    assert len(outcome.embedded) == 1 and outcome.reused == ()


def test_an_embedder_that_is_not_the_pinned_model_is_refused() -> None:
    with pytest.raises(EmbeddingError, match="pinned model"):
        LocalEmbeddingAdapter(FakeEmbedder(OTHER), EmbeddingStore(), expected=PIN)


def test_a_model_returning_the_wrong_dimension_is_refused() -> None:
    a, _, _ = adapter(FakeEmbedder(dimensions=5))
    with pytest.raises(EmbeddingError, match="dimensions"):
        a.embed_revisions([revision()], now=NOW)


@pytest.mark.parametrize(
    ("overrides", "why"),
    [
        ({"approval": "proposed"}, "not approved"),
        ({"sensitivity": "real_interview"}, "above the ceiling"),
        ({"kind": "hypothesis", "approval": "proposed"}, "a guess"),
    ],
)
def test_content_that_must_not_be_embedded_is_refused_not_embedded(
    overrides: dict[str, object], why: str
) -> None:
    r = revision(**overrides)
    assert embeddable(r) is False, why
    a, store, embedder = adapter()
    outcome = a.embed_revisions([r], now=NOW)
    assert outcome.refused == (100,) and outcome.embedded == ()
    assert embedder.calls == [] and store.records == {}


def test_batching_respects_the_batch_size_and_keeps_order() -> None:
    a, _, embedder = adapter(batch_size=2)
    revisions = [
        revision(memory_id=i, revision_id=100 + i, claim=f"claim number {i} about pace")
        for i in range(1, 6)
    ]
    outcome = a.embed_revisions(revisions, now=NOW)
    assert outcome.batches == 3 and [len(c) for c in embedder.calls] == [2, 2, 1]
    assert [r.revision_id for r in outcome.embedded] == [101, 102, 103, 104, 105]


def test_the_embedder_contract_has_no_network_shape() -> None:
    # A local embedder is a pin and an embed method; there is no endpoint or key to set.
    assert not {"endpoint", "api_key", "base_url"} & set(dir(FakeEmbedder()))
    with pytest.raises(EmbeddingError):
        EmbeddingModelPin(name="x", revision="1", dimensions=4, artifact_sha256="not-a-digest")

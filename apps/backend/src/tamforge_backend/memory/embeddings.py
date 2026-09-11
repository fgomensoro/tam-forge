"""Embeddings for learner memory, computed here and nowhere else.

An embedding is a derived view of a claim about the learner, so it is produced by a model
that runs on this server, pinned by name, revision, checksum and dimension, and never by
a hosted endpoint. The adapter below is the only door: it takes a local embedder, refuses
content that must not be embedded at all (revisions that are not approved, and anything
above the sensitivity ceiling embeddings are allowed to hold), normalises every vector so
cosine distance is a dot product, and keys the result by a content hash so the same text
is never embedded twice under the same model. A new model revision invalidates every
stored vector, because vectors from different models do not live in the same space.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
from typing import Final, Protocol

from tamforge_protocol.memory import SENSITIVITY_RANK, MemoryRevision, Sensitivity

EMBEDDING_CONTRACT_VERSION: Final = "memory-embeddings-v1"

# Real-interview material is retrieved by relational filters only; its text never becomes
# a vector that a similarity search could surface into a practice context by accident.
EMBEDDABLE_SENSITIVITY_CEILING: Final[Sensitivity] = "personal"

DEFAULT_BATCH_SIZE: Final = 32


class EmbeddingError(ValueError):
    """Content that must not be embedded, or a model that is not the pinned one."""


@dataclass(frozen=True, slots=True)
class EmbeddingModelPin:
    """The one model whose vectors may enter the store."""

    name: str
    revision: str
    dimensions: int
    artifact_sha256: str

    def __post_init__(self) -> None:
        if not self.name or not self.revision:
            raise EmbeddingError("an embedding model is pinned by name and revision")
        if self.dimensions <= 0:
            raise EmbeddingError("dimensions must be positive")
        if len(self.artifact_sha256) != 64 or set(self.artifact_sha256) - set("0123456789abcdef"):
            raise EmbeddingError("artifact_sha256 must be a lowercase hex digest")

    @property
    def key(self) -> str:
        return f"{self.name}@{self.revision}"


class LocalEmbedder(Protocol):
    """A model running in this process. No URL, no API key, no network."""

    @property
    def pin(self) -> EmbeddingModelPin: ...

    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]: ...


@dataclass(frozen=True, slots=True)
class EmbeddingRecord:
    revision_id: int
    content_sha256: str
    model_key: str
    dimensions: int
    vector: tuple[float, ...]
    generated_at: datetime


def content_hash(text: str) -> str:
    return sha256(text.strip().casefold().encode("utf-8")).hexdigest()


def embeddable(revision: MemoryRevision) -> bool:
    """Only approved claims at or under the ceiling may become vectors."""
    return (
        revision.approval == "approved"
        and SENSITIVITY_RANK[revision.sensitivity]
        <= SENSITIVITY_RANK[EMBEDDABLE_SENSITIVITY_CEILING]
    )


def _normalise(vector: Sequence[float], dimensions: int) -> tuple[float, ...]:
    if len(vector) != dimensions:
        raise EmbeddingError(f"model returned {len(vector)} dimensions, pin says {dimensions}")
    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0:
        raise EmbeddingError("a zero vector embeds nothing")
    return tuple(v / norm for v in vector)


@dataclass
class EmbeddingStore:
    """In-memory store keyed by (model, content hash); the relational store mirrors this."""

    records: dict[tuple[str, str], EmbeddingRecord] = field(default_factory=dict)

    def get(self, model_key: str, content_sha256: str) -> EmbeddingRecord | None:
        return self.records.get((model_key, content_sha256))

    def put(self, record: EmbeddingRecord) -> None:
        self.records[(record.model_key, record.content_sha256)] = record

    def for_model(self, model_key: str) -> tuple[EmbeddingRecord, ...]:
        return tuple(r for (key, _), r in self.records.items() if key == model_key)


@dataclass(frozen=True, slots=True)
class EmbeddingOutcome:
    embedded: tuple[EmbeddingRecord, ...]
    reused: tuple[EmbeddingRecord, ...]
    refused: tuple[int, ...]
    batches: int


class LocalEmbeddingAdapter:
    """The only way vectors reach the store."""

    def __init__(
        self,
        embedder: LocalEmbedder,
        store: EmbeddingStore,
        *,
        expected: EmbeddingModelPin,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        if embedder.pin != expected:
            raise EmbeddingError(
                f"embedder is {embedder.pin.key}, the pinned model is {expected.key}"
            )
        if batch_size <= 0:
            raise EmbeddingError("batch size must be positive")
        self._embedder = embedder
        self._store = store
        self._pin = expected
        self._batch_size = batch_size

    @property
    def pin(self) -> EmbeddingModelPin:
        return self._pin

    def embed_revisions(
        self, revisions: Iterable[MemoryRevision], *, now: datetime
    ) -> EmbeddingOutcome:
        pending: list[tuple[MemoryRevision, str]] = []
        reused: list[EmbeddingRecord] = []
        refused: list[int] = []
        for revision in revisions:
            if not embeddable(revision):
                refused.append(revision.revision_id)
                continue
            digest = content_hash(revision.claim)
            existing = self._store.get(self._pin.key, digest)
            if existing is not None:
                reused.append(existing)
                continue
            pending.append((revision, digest))

        embedded: list[EmbeddingRecord] = []
        batches = 0
        for start in range(0, len(pending), self._batch_size):
            batch = pending[start : start + self._batch_size]
            batches += 1
            vectors = self._embedder.embed([r.claim for r, _ in batch])
            if len(vectors) != len(batch):
                raise EmbeddingError("model returned a different number of vectors than texts")
            for (revision, digest), vector in zip(batch, vectors, strict=True):
                record = EmbeddingRecord(
                    revision_id=revision.revision_id,
                    content_sha256=digest,
                    model_key=self._pin.key,
                    dimensions=self._pin.dimensions,
                    vector=_normalise(vector, self._pin.dimensions),
                    generated_at=now,
                )
                self._store.put(record)
                embedded.append(record)
        return EmbeddingOutcome(
            embedded=tuple(embedded), reused=tuple(reused), refused=tuple(refused), batches=batches
        )

    def stale_records(self) -> tuple[EmbeddingRecord, ...]:
        """Vectors from any model other than the pinned one; they must be re-embedded."""
        return tuple(r for (key, _), r in self._store.records.items() if key != self._pin.key)


__all__ = [
    "DEFAULT_BATCH_SIZE",
    "EMBEDDABLE_SENSITIVITY_CEILING",
    "EMBEDDING_CONTRACT_VERSION",
    "EmbeddingError",
    "EmbeddingModelPin",
    "EmbeddingOutcome",
    "EmbeddingRecord",
    "EmbeddingStore",
    "LocalEmbedder",
    "LocalEmbeddingAdapter",
    "content_hash",
    "embeddable",
]

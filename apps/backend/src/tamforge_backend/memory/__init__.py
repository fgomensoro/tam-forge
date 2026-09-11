"""Learner memory on the server: local embeddings and relational-first retrieval."""

from __future__ import annotations

from .embeddings import (
    EMBEDDING_CONTRACT_VERSION,
    EmbeddingError,
    EmbeddingModelPin,
    EmbeddingRecord,
    EmbeddingStore,
    LocalEmbedder,
    LocalEmbeddingAdapter,
    content_hash,
    embeddable,
)
from .retrieval import (
    RetrievalError,
    RetrievalQuery,
    RetrievalResult,
    SelectedMemory,
    retrieve,
)

__all__ = [
    "EMBEDDING_CONTRACT_VERSION",
    "EmbeddingError",
    "EmbeddingModelPin",
    "EmbeddingRecord",
    "EmbeddingStore",
    "LocalEmbedder",
    "LocalEmbeddingAdapter",
    "RetrievalError",
    "RetrievalQuery",
    "RetrievalResult",
    "SelectedMemory",
    "content_hash",
    "embeddable",
    "retrieve",
]

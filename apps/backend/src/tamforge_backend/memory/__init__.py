"""Learner memory on the server: local embeddings and relational-first retrieval."""

from __future__ import annotations

from .context import (
    HIERARCHY,
    ContextError,
    ContextPacket,
    ContextRequest,
    ContextSource,
    build_context,
)
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
from .policy import (
    MIN_EVENTS_FOR_TRAIT,
    Decision,
    MemoryProposal,
    PolicyError,
    PolicyOutcome,
    decide,
)
from .retrieval import (
    RetrievalError,
    RetrievalQuery,
    RetrievalResult,
    SelectedMemory,
    retrieve,
)
from .service import MemoryReview, ProposalRecord, ReviewError

__all__ = [
    "HIERARCHY",
    "ContextError",
    "ContextPacket",
    "ContextRequest",
    "ContextSource",
    "build_context",
    "EMBEDDING_CONTRACT_VERSION",
    "EmbeddingError",
    "EmbeddingModelPin",
    "EmbeddingRecord",
    "EmbeddingStore",
    "LocalEmbedder",
    "MIN_EVENTS_FOR_TRAIT",
    "Decision",
    "MemoryProposal",
    "MemoryReview",
    "PolicyError",
    "PolicyOutcome",
    "ProposalRecord",
    "ReviewError",
    "decide",
    "LocalEmbeddingAdapter",
    "RetrievalError",
    "RetrievalQuery",
    "RetrievalResult",
    "SelectedMemory",
    "content_hash",
    "embeddable",
    "retrieve",
]

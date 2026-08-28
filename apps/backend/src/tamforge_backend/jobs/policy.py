"""Pure priority, retry, and failure policy for durable jobs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from ..notifications.models import ERROR_CATEGORIES

RetryDisposition = Literal["retry_wait", "needs_attention"]
_RETRYABLE_CATEGORIES = frozenset({"transient_dependency", "resource_exhausted"})


class JobPolicyError(ValueError):
    """A job command violates bounded operational policy."""


@dataclass(frozen=True, slots=True)
class ClaimCandidate:
    id: int
    priority: int
    available_at: datetime


def order_claim_candidates(
    candidates: tuple[ClaimCandidate, ...],
) -> tuple[ClaimCandidate, ...]:
    """Higher numeric priority wins; equal priority is strict FIFO then ID."""
    return tuple(
        sorted(
            candidates,
            key=lambda item: (-item.priority, item.available_at, item.id),
        )
    )


def retry_disposition(
    *,
    attempt_count: int,
    max_attempts: int,
    category: str,
) -> RetryDisposition:
    if category not in ERROR_CATEGORIES:
        raise JobPolicyError("job failure category is invalid")
    if not 1 <= attempt_count <= max_attempts <= 100:
        raise JobPolicyError("job attempt bounds are invalid")
    if category in _RETRYABLE_CATEGORIES and attempt_count < max_attempts:
        return "retry_wait"
    return "needs_attention"


__all__ = [
    "ClaimCandidate",
    "JobPolicyError",
    "RetryDisposition",
    "order_claim_candidates",
    "retry_disposition",
]

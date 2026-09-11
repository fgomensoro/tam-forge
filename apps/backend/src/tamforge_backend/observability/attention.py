"""One failure, one transition: the job, the component, the log line, the notification.

A worker that hits the subscription quota, a credential that has expired, and a worker
that simply died all end the same way for the learner: something they were waiting for
is not coming, and someone has to act. What differs is what must not happen next. Quota
and authentication failures are never retried in a loop, because the retry spends the
same quota or presents the same refused credential; they mark the Claude capability as
needing attention while everything that does not need Claude stays ready. A transient
service failure is retried inside the job's own bound and only then becomes attention.

Everything this produces is content-safe by construction. The log line is built from
allowlisted fields, so the exception text, which may carry a token or a transcript
phrase, is never even offered to it. The notification is one of the five approved
types, built through the same policy every other notification passes, and it is sent
once per subject: a second failure on the same subject updates the state and is not a
second push.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal

from ..jobs.policy import RetryDisposition, retry_disposition
from ..notifications.policy import NotificationCandidate, notification_candidate_from_event
from .logging import safe_event

WorkerFailure = Literal[
    "quota_exhausted",
    "authentication_rejected",
    "service_unavailable",
    "timeout",
    "output_invalid",
    "turns_exceeded",
    "worker_crashed",
]
Component = Literal["claude", "speech"]

# Failure -> (error category for the job record, reason code for logs and health).
_CLASSIFICATION: Final[dict[str, tuple[str, str]]] = {
    "quota_exhausted": ("resource_exhausted", "quota"),
    "authentication_rejected": ("permission_required", "auth"),
    "service_unavailable": ("transient_dependency", "service"),
    "timeout": ("transient_dependency", "timeout"),
    "output_invalid": ("processing_failure", "processing_failure"),
    "turns_exceeded": ("processing_failure", "processing_failure"),
    "worker_crashed": ("internal_error", "internal_error"),
}

# Never retried in a loop: the next attempt spends the same quota or presents the same
# refused credential.
NEVER_RETRIED: Final[frozenset[str]] = frozenset({"quota_exhausted", "authentication_rejected"})

# Failures that say something about the capability, not only about this job.
CAPABILITY_FAILURES: Final[frozenset[str]] = frozenset(
    {"quota_exhausted", "authentication_rejected", "service_unavailable"}
)


class AttentionError(ValueError):
    """A failure this module does not know how to classify."""


@dataclass(frozen=True, slots=True)
class AttentionTransition:
    job_id: int
    failure: str
    job_disposition: RetryDisposition
    error_category: str
    reason: str
    component: Component
    component_status: Literal["ok", "needs_attention"]
    log_line: str
    notification: NotificationCandidate | None

    @property
    def needs_attention(self) -> bool:
        return self.job_disposition == "needs_attention"


def transition(
    *,
    failure: str,
    job_id: int,
    attempt_count: int,
    max_attempts: int,
    component: Component,
    subject_id: int,
    occurred_at: datetime,
    timezone: str,
    already_notified: frozenset[int] = frozenset(),
) -> AttentionTransition:
    """Classify one failure and produce everything that must change because of it."""
    if failure not in _CLASSIFICATION:
        raise AttentionError("unknown worker failure")
    category, reason = _CLASSIFICATION[failure]
    if failure in NEVER_RETRIED:
        disposition: RetryDisposition = "needs_attention"
    else:
        disposition = retry_disposition(
            attempt_count=attempt_count, max_attempts=max_attempts, category=category
        )
    component_status: Literal["ok", "needs_attention"] = (
        "needs_attention"
        if failure in CAPABILITY_FAILURES and disposition == "needs_attention"
        else "ok"
    )
    log_line = safe_event(
        "job_completed",
        job_id=job_id,
        status="needs_attention" if disposition == "needs_attention" else "queued",
        error_code=reason,
    )
    notification: NotificationCandidate | None = None
    if disposition == "needs_attention" and subject_id not in already_notified:
        notification = notification_candidate_from_event(
            event_type="processing_status.needs_attention",
            aggregate_type="processing_status",
            subject_id=subject_id,
            occurred_at=occurred_at,
            timezone=timezone,
        )
    return AttentionTransition(
        job_id=job_id,
        failure=failure,
        job_disposition=disposition,
        error_category=category,
        reason=reason,
        component=component,
        component_status=component_status,
        log_line=log_line,
        notification=notification,
    )


__all__ = [
    "CAPABILITY_FAILURES",
    "NEVER_RETRIED",
    "AttentionError",
    "AttentionTransition",
    "Component",
    "WorkerFailure",
    "transition",
]

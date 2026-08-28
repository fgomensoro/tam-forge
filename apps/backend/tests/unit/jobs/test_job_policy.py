"""Deterministic policy tests for the PostgreSQL durable-job primitive."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest


def test_higher_priority_then_fifo_order_is_deterministic() -> None:
    from tamforge_backend.jobs.policy import ClaimCandidate, order_claim_candidates

    now = datetime(2026, 8, 28, 12, tzinfo=UTC)
    ordered = order_claim_candidates(
        (
            ClaimCandidate(id=4, priority=20, available_at=now),
            ClaimCandidate(id=3, priority=80, available_at=now + timedelta(seconds=1)),
            ClaimCandidate(id=2, priority=80, available_at=now),
            ClaimCandidate(id=1, priority=80, available_at=now),
        )
    )

    assert tuple(item.id for item in ordered) == (1, 2, 3, 4)


@pytest.mark.parametrize(
    ("attempt_count", "max_attempts", "category", "expected"),
    (
        (1, 3, "transient_dependency", "retry_wait"),
        (2, 3, "resource_exhausted", "retry_wait"),
        (3, 3, "transient_dependency", "needs_attention"),
        (1, 3, "invalid_input", "needs_attention"),
        (1, 3, "permission_required", "needs_attention"),
    ),
)
def test_retry_policy_is_bounded_and_typed(
    attempt_count: int,
    max_attempts: int,
    category: str,
    expected: str,
) -> None:
    from tamforge_backend.jobs.policy import retry_disposition

    assert retry_disposition(
        attempt_count=attempt_count,
        max_attempts=max_attempts,
        category=category,
    ) == expected


def test_job_commands_reject_unbounded_or_content_bearing_payloads() -> None:
    from pydantic import ValidationError
    from tamforge_backend.jobs.schemas import EnqueueJobCommand

    now = datetime(2026, 8, 28, 12, tzinfo=UTC)
    command = EnqueueJobCommand(
        kind="transcribe_activity",
        payload={"schema_version": 1, "subject_id": 7},
        priority=80,
        available_at=now,
        max_attempts=3,
    )
    assert command.payload.subject_id == 7

    with pytest.raises(ValidationError):
        EnqueueJobCommand(
            kind="transcribe_activity",
            payload={
                "schema_version": 1,
                "subject_id": 7,
                "transcript": "content must never enter queue payloads",
            },
            priority=80,
            available_at=now,
            max_attempts=3,
        )
    with pytest.raises(ValidationError):
        EnqueueJobCommand(
            kind="transcribe_activity",
            payload={"schema_version": 1, "subject_id": 7},
            priority=101,
            available_at=now,
            max_attempts=3,
        )


def test_lease_and_worker_identifiers_are_strictly_bounded() -> None:
    from pydantic import ValidationError
    from tamforge_backend.jobs.schemas import ClaimJobCommand, HeartbeatJobCommand

    claim = ClaimJobCommand(
        worker_id="speech-worker-1",
        kinds=("transcribe_activity",),
        lease_seconds=120,
    )
    assert claim.lease_seconds == 120

    with pytest.raises(ValidationError):
        ClaimJobCommand(worker_id="bad worker", kinds=(), lease_seconds=120)
    with pytest.raises(ValidationError):
        HeartbeatJobCommand(worker_id="worker-1", lease_seconds=3601)


def test_never_started_job_can_be_canceled_without_fabricating_an_attempt() -> None:
    from tamforge_backend.notifications.models import (
        BackgroundJob,
        validate_background_job,
    )

    now = datetime(2026, 8, 28, 12, tzinfo=UTC)
    job = BackgroundJob(
        owner_id=1,
        kind="transcribe_activity",
        payload_schema_version=1,
        payload={"schema_version": 1, "subject_id": 7},
        priority=80,
        state="canceled",
        idempotency_key="job-7",
        available_at=now,
        attempt_count=0,
        max_attempts=3,
        lease_owner=None,
        lease_expires_at=None,
        last_error_category=None,
        last_error_details=None,
        created_at=now,
        updated_at=now,
        started_at=None,
        completed_at=now,
    )

    validate_background_job(None, None, job)

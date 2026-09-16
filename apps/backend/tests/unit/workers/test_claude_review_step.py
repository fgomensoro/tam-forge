"""The review step queues, scores, completes, retries or parks; the beat never raises."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from tamforge_backend.agents.roles.reviewer import ReviewerService
from tamforge_backend.jobs.schemas import EnqueueJobCommand, ReferencePayload
from tamforge_backend.jobs.service import JobService
from tamforge_backend.reviews.service import ReviewInvalid, ReviewsUnavailable
from tamforge_backend.testing.jobs import FakeJobStore
from tamforge_backend.workers import claude as claude_worker

NOW = datetime(2026, 9, 16, 12, tzinfo=UTC)


class _Session:
    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def rollback(self) -> None:
        return None


def _queue(store: FakeJobStore, activity: int) -> int:
    result = asyncio.run(
        JobService(store).enqueue(
            owner_id=1,
            command=EnqueueJobCommand(
                kind="claude_review",
                payload=ReferencePayload(subject_id=activity, related_id=activity + 100),
                priority=40,
                available_at=NOW,
            ),
            idempotency_key=f"claude-review-a{activity}",
        )
    )
    return result.job.id


def _run(monkeypatch: pytest.MonkeyPatch, store: FakeJobStore, process) -> list[tuple[int, str]]:  # type: ignore[no-untyped-def]
    failed: list[tuple[int, str]] = []

    class Service:
        def __init__(self, session: object, *, reviewer: object, evidence: object = None) -> None:
            pass

        async def enqueue_pending(self, *, limit: int = 20) -> int:
            return 0

        async def process(self, *, owner_id: int, activity_id: int) -> object:
            return process(activity_id)

        async def mark_failed(self, *, owner_id: int, activity_id: int, category: str) -> None:
            failed.append((activity_id, category))

    class Repo:
        def __init__(self, session: object) -> None:
            pass

    import tamforge_backend.evidence.repository as evidence_repository
    import tamforge_backend.jobs.repository as jobs_repository
    import tamforge_backend.jobs.service as jobs_service
    import tamforge_backend.reviews.service as reviews_module

    monkeypatch.setattr(reviews_module, "ReviewService", Service)
    monkeypatch.setattr(jobs_repository, "SqlAlchemyJobRepository", Repo)
    monkeypatch.setattr(evidence_repository, "SqlAlchemyEvidenceRepository", Repo)
    monkeypatch.setattr(jobs_service, "JobService", lambda repository: JobService(store))
    monkeypatch.setattr(claude_worker, "REVIEW_JOBS_PER_STEP", 1)
    reviewer = ReviewerService(None, model="m")
    asyncio.run(claude_worker.review_step(lambda: _Session(), reviewer=reviewer))  # type: ignore[arg-type]
    return failed


def test_a_scored_review_completes_its_job(monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeJobStore(now=NOW)
    job_id = _queue(store, 41)
    seen: list[int] = []

    _run(monkeypatch, store, lambda activity: seen.append(activity))

    assert seen == [41] and store.jobs[job_id].state == "succeeded"


def test_an_unreviewable_attempt_parks_the_job_and_marks_the_activity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FakeJobStore(now=NOW)
    job_id = _queue(store, 41)

    def broken(activity: int) -> object:
        raise ReviewInvalid("no output")

    failed = _run(monkeypatch, store, broken)

    assert store.jobs[job_id].state == "failed"
    assert store.jobs[job_id].last_error_category == "invalid_input"
    assert failed == [(41, "invalid_input")]


def test_a_spent_quota_parks_with_its_own_category_and_a_transport_failure_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FakeJobStore(now=NOW)
    quota_job = _queue(store, 41)

    def quota(activity: int) -> object:
        raise ReviewsUnavailable("the subscription quota is spent")

    failed = _run(monkeypatch, store, quota)
    assert store.jobs[quota_job].last_error_category == "resource_exhausted"
    assert store.jobs[quota_job].state == "queued" and not failed

    store = FakeJobStore(now=NOW)
    flaky_job = _queue(store, 42)

    def flaky(activity: int) -> object:
        raise ReviewsUnavailable("down")

    _run(monkeypatch, store, flaky)
    assert store.jobs[flaky_job].last_error_category == "transient_dependency"
    assert store.jobs[flaky_job].state == "queued"

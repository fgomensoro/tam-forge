"""The practice review step runs one queued review and closes every job state."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from tamforge_backend.agents.roles.practice_review import PracticeReviewService
from tamforge_backend.jobs.schemas import EnqueueJobCommand, ReferencePayload
from tamforge_backend.jobs.service import JobService
from tamforge_backend.practice.service import PracticeInvalid, PracticeUnavailable
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


def _queue(store: FakeJobStore, answer_id: int) -> int:
    result = asyncio.run(
        JobService(store).enqueue(
            owner_id=1,
            command=EnqueueJobCommand(
                kind="claude_practice_review",
                payload=ReferencePayload(subject_id=answer_id),
                priority=40,
                available_at=NOW,
            ),
            idempotency_key=f"claude-practice-a{answer_id}",
        )
    )
    return result.job.id


def _run(monkeypatch: pytest.MonkeyPatch, store: FakeJobStore, process) -> int:  # type: ignore[no-untyped-def]
    class Service:
        def __init__(self, session: object, *, reviewer: object) -> None:
            pass

        async def process(self, *, owner_id: int, answer_id: int) -> object:
            return process(answer_id)

    class Repo:
        def __init__(self, session: object) -> None:
            pass

    import tamforge_backend.jobs.repository as jobs_repository
    import tamforge_backend.jobs.service as jobs_service
    import tamforge_backend.practice.service as practice_module

    monkeypatch.setattr(practice_module, "PracticeAnswerService", Service)
    monkeypatch.setattr(jobs_repository, "SqlAlchemyJobRepository", Repo)
    monkeypatch.setattr(jobs_service, "JobService", lambda repository: JobService(store))
    reviewer = PracticeReviewService(None, model="m")
    return asyncio.run(claude_worker.practice_review_step(lambda: _Session(), reviewer=reviewer))  # type: ignore[arg-type]


def test_a_stored_review_completes_its_job(monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeJobStore(now=NOW)
    job_id = _queue(store, 3)
    seen: list[int] = []
    assert _run(monkeypatch, store, lambda answer_id: seen.append(answer_id)) == 1
    assert seen == [3] and store.jobs[job_id].state == "succeeded"


def test_failures_park_or_retry_with_their_category(monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeJobStore(now=NOW)
    invalid_job = _queue(store, 3)

    def invalid(answer_id: int) -> object:
        raise PracticeInvalid("too short")

    assert _run(monkeypatch, store, invalid) == 0
    assert store.jobs[invalid_job].state == "failed"
    assert store.jobs[invalid_job].last_error_category == "invalid_input"

    store = FakeJobStore(now=NOW)
    down_job = _queue(store, 4)

    def down(answer_id: int) -> object:
        raise PracticeUnavailable("down")

    _run(monkeypatch, store, down)
    assert store.jobs[down_job].last_error_category == "transient_dependency"
    assert store.jobs[down_job].state == "queued"

    store = FakeJobStore(now=NOW)
    quota_job = _queue(store, 5)

    def quota(answer_id: int) -> object:
        raise PracticeUnavailable("the subscription quota is exhausted")

    _run(monkeypatch, store, quota)
    assert store.jobs[quota_job].last_error_category == "resource_exhausted"

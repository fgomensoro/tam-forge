"""The class analysis step runs one requested analysis and closes every job state."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from tamforge_backend.agents.roles.class_analysis import ClassAnalysisService
from tamforge_backend.classes.service import ClassesUnavailable, ClassInvalid
from tamforge_backend.jobs.schemas import EnqueueJobCommand, ReferencePayload
from tamforge_backend.jobs.service import JobService
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


def _queue(store: FakeJobStore, class_id: int) -> int:
    result = asyncio.run(
        JobService(store).enqueue(
            owner_id=1,
            command=EnqueueJobCommand(
                kind="claude_class_analysis",
                payload=ReferencePayload(subject_id=class_id),
                priority=40,
                available_at=NOW,
            ),
            idempotency_key=f"claude-class-c{class_id}",
        )
    )
    return result.job.id


def _run(monkeypatch: pytest.MonkeyPatch, store: FakeJobStore, process) -> int:  # type: ignore[no-untyped-def]
    class Service:
        def __init__(self, session: object, *, analyst: object) -> None:
            pass

        async def process(self, *, owner_id: int, class_id: int) -> object:
            return process(class_id)

    class Repo:
        def __init__(self, session: object) -> None:
            pass

    import tamforge_backend.classes.analysis as analysis_module
    import tamforge_backend.jobs.repository as jobs_repository
    import tamforge_backend.jobs.service as jobs_service

    monkeypatch.setattr(analysis_module, "EnglishClassAnalysisService", Service)
    monkeypatch.setattr(jobs_repository, "SqlAlchemyJobRepository", Repo)
    monkeypatch.setattr(jobs_service, "JobService", lambda repository: JobService(store))
    analyst = ClassAnalysisService(None, model="m")
    return asyncio.run(claude_worker.class_analysis_step(lambda: _Session(), analyst=analyst))  # type: ignore[arg-type]


def test_a_stored_analysis_completes_its_job(monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeJobStore(now=NOW)
    job_id = _queue(store, 3)
    seen: list[int] = []
    assert _run(monkeypatch, store, lambda class_id: seen.append(class_id)) == 1
    assert seen == [3] and store.jobs[job_id].state == "succeeded"


def test_failures_park_or_retry_with_their_category(monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeJobStore(now=NOW)
    invalid_job = _queue(store, 3)

    def invalid(class_id: int) -> object:
        raise ClassInvalid("no recording")

    assert _run(monkeypatch, store, invalid) == 0
    assert store.jobs[invalid_job].state == "failed"
    assert store.jobs[invalid_job].last_error_category == "invalid_input"

    store = FakeJobStore(now=NOW)
    down_job = _queue(store, 4)

    def down(class_id: int) -> object:
        raise ClassesUnavailable("down")

    _run(monkeypatch, store, down)
    assert store.jobs[down_job].last_error_category == "transient_dependency"
    assert store.jobs[down_job].state == "queued"

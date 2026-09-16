"""The debrief step runs one requested debrief; every failure ends in a closed job state."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from tamforge_backend.agents.roles.debrief import DebriefService
from tamforge_backend.interviews.service import InterviewInvalid, InterviewsUnavailable
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


def _queue(store: FakeJobStore, interview: int) -> int:
    result = asyncio.run(
        JobService(store).enqueue(
            owner_id=1,
            command=EnqueueJobCommand(
                kind="claude_debrief",
                payload=ReferencePayload(subject_id=interview),
                priority=40,
                available_at=NOW,
            ),
            idempotency_key=f"claude-debrief-i{interview}",
        )
    )
    return result.job.id


def _run(monkeypatch: pytest.MonkeyPatch, store: FakeJobStore, process) -> int:  # type: ignore[no-untyped-def]
    class Service:
        def __init__(self, session: object, *, debriefer: object) -> None:
            pass

        async def process(self, *, owner_id: int, interview_id: int) -> object:
            return process(interview_id)

    class Repo:
        def __init__(self, session: object) -> None:
            pass

    import tamforge_backend.interviews.debriefs as debriefs_module
    import tamforge_backend.jobs.repository as jobs_repository
    import tamforge_backend.jobs.service as jobs_service

    monkeypatch.setattr(debriefs_module, "InterviewDebriefService", Service)
    monkeypatch.setattr(jobs_repository, "SqlAlchemyJobRepository", Repo)
    monkeypatch.setattr(jobs_service, "JobService", lambda repository: JobService(store))
    debriefer = DebriefService(None, model="m")
    return asyncio.run(claude_worker.debrief_step(lambda: _Session(), debriefer=debriefer))  # type: ignore[arg-type]


def test_a_stored_debrief_completes_its_job(monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeJobStore(now=NOW)
    job_id = _queue(store, 7)
    seen: list[int] = []

    processed = _run(monkeypatch, store, lambda interview: seen.append(interview))

    assert processed == 1 and seen == [7]
    assert store.jobs[job_id].state == "succeeded"


def test_failures_park_or_retry_with_their_category(monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeJobStore(now=NOW)
    invalid_job = _queue(store, 7)

    def invalid(interview: int) -> object:
        raise InterviewInvalid("no transcript")

    assert _run(monkeypatch, store, invalid) == 0
    assert store.jobs[invalid_job].state == "failed"
    assert store.jobs[invalid_job].last_error_category == "invalid_input"

    store = FakeJobStore(now=NOW)
    quota_job = _queue(store, 8)

    def quota(interview: int) -> object:
        raise InterviewsUnavailable("the subscription quota is spent")

    _run(monkeypatch, store, quota)
    assert store.jobs[quota_job].last_error_category == "resource_exhausted"
    assert store.jobs[quota_job].state == "queued"

    store = FakeJobStore(now=NOW)
    crash_job = _queue(store, 9)

    def crash(interview: int) -> object:
        raise RuntimeError("boom")

    _run(monkeypatch, store, crash)
    assert store.jobs[crash_job].last_error_category == "processing_failure"

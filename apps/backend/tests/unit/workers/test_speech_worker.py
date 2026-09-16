"""The speech worker completes, retries or parks each job; the step never raises."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import OperationalError
from tamforge_backend.jobs.service import JobService
from tamforge_backend.speech.analysis import SpeechAnalysisInvalid
from tamforge_backend.speech.jobs import enqueue_speech_analysis
from tamforge_backend.testing.jobs import FakeJobStore
from tamforge_backend.workers import speech as speech_worker

NOW = datetime(2026, 9, 15, 12, tzinfo=UTC)


class _Session:
    """A session stand-in: the worker only rolls it back on a store failure."""

    def __init__(self) -> None:
        self.rollbacks = 0

    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def rollback(self) -> None:
        self.rollbacks += 1


def _run(
    monkeypatch: pytest.MonkeyPatch, store: FakeJobStore, process: Callable[..., object]
) -> list[_Session]:
    sessions: list[_Session] = []

    def factory() -> _Session:
        session = _Session()
        sessions.append(session)
        return session

    class Analysis:
        def __init__(self, session: object) -> None:
            del session

        async def process(self, *, owner_id: int, recording_pk: int) -> object:
            return process(owner_id=owner_id, recording_pk=recording_pk)

    class Repository:
        def __init__(self, session: object) -> None:
            del session

    monkeypatch.setattr(speech_worker, "SpeechAnalysisService", Analysis)
    monkeypatch.setattr(speech_worker, "SqlAlchemyJobRepository", Repository)
    monkeypatch.setattr(speech_worker, "JobService", lambda repository: JobService(store))
    assert asyncio.run(speech_worker.analysis_step(factory)) is None  # type: ignore[arg-type]
    return sessions


def _enqueue(store: FakeJobStore, recording: int, transcript: int) -> int:
    job, _ = asyncio.run(
        enqueue_speech_analysis(
            JobService(store),
            owner_id=1,
            recording_id=recording,
            transcript_id=transcript,
            available_at=NOW,
        )
    )
    return job.id


def test_a_processed_job_is_completed_and_the_worker_drains_the_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FakeJobStore(now=NOW)
    first, second = _enqueue(store, 10, 100), _enqueue(store, 11, 101)
    processed: list[int] = []

    _run(monkeypatch, store, lambda owner_id, recording_pk: processed.append(recording_pk))

    assert processed == [10, 11]
    assert {store.jobs[first].state, store.jobs[second].state} == {"succeeded"}


def test_an_unanalysable_transcript_parks_the_job_as_needs_attention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FakeJobStore(now=NOW)
    job_id = _enqueue(store, 10, 100)

    def broken(**kwargs: object) -> object:
        raise SpeechAnalysisInvalid("the microphone transcript is not stored")

    _run(monkeypatch, store, broken)

    job = store.jobs[job_id]
    assert job.state == "failed"
    assert job.last_error_category == "invalid_input"


def test_a_store_failure_is_retried_and_the_session_rolled_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FakeJobStore(now=NOW)
    job_id = _enqueue(store, 10, 100)

    def flaky(**kwargs: object) -> object:
        raise OperationalError("SELECT 1", {}, Exception("connection lost"))

    # One claim per step here: the fake queue has a frozen clock, so a requeued job
    # would otherwise be claimed again within the same step until its attempts ran out.
    monkeypatch.setattr(speech_worker, "JOBS_PER_STEP", 1)
    sessions = _run(monkeypatch, store, flaky)

    job = store.jobs[job_id]
    assert job.state == "queued" and job.attempt_count == 1
    assert job.last_error_category == "transient_dependency"
    assert sessions[0].rollbacks == 1

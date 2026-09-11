"""Recovery of speech jobs is the queue's own reclaim, picked up again in priority order."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from tamforge_backend.jobs.schemas import ClaimJobCommand, CompleteJobCommand
from tamforge_backend.jobs.service import JobService
from tamforge_backend.speech.jobs import (
    SPEECH_ANALYSIS_KIND,
    SPEECH_LEASE_SECONDS,
    SpeechScheduler,
    SpeechWorkerRegistration,
    enqueue_speech_analysis,
    outbox_status,
    recover_speech_jobs,
)
from tamforge_backend.testing.jobs import FakeJobStore

NOW = datetime(2026, 9, 12, 15, tzinfo=UTC)
pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def store() -> FakeJobStore:
    return FakeJobStore(now=NOW)


@pytest.fixture
def service(store: FakeJobStore) -> JobService:
    return JobService(store)


async def test_a_dead_speech_worker_loses_its_lease_and_the_job_is_requeued(
    service: JobService, store: FakeJobStore
) -> None:
    job, _ = await enqueue_speech_analysis(
        service, owner_id=1, recording_id=7, transcript_id=3, available_at=NOW
    )
    dead = SpeechScheduler(service, SpeechWorkerRegistration(worker_id="speech-dead"))
    held = await dead.claim_next()
    assert held is not None and held.state == "running"

    # Nothing to reclaim while the lease is live.
    assert await recover_speech_jobs(service) == (0, 0)
    store.now = NOW + timedelta(seconds=SPEECH_LEASE_SECONDS + 1)
    assert await recover_speech_jobs(service) == (1, 0)
    assert outbox_status(store.jobs[job.id]) == "queued"

    alive = SpeechScheduler(service, SpeechWorkerRegistration(worker_id="speech-alive"))
    picked = await alive.claim_next()
    assert picked is not None and picked.id == job.id and picked.attempt_count == 2


async def test_a_job_whose_leases_keep_expiring_ends_in_needs_attention_not_a_loop(
    service: JobService, store: FakeJobStore
) -> None:
    job, _ = await enqueue_speech_analysis(
        service, owner_id=1, recording_id=7, transcript_id=3, available_at=NOW
    )
    for attempt in range(1, job.max_attempts + 1):
        claimed = await service.claim(
            ClaimJobCommand(worker_id=f"w{attempt}", kinds=(SPEECH_ANALYSIS_KIND,))
        )
        assert claimed is not None
        store.now = store.now + timedelta(seconds=SPEECH_LEASE_SECONDS + 1)
        retried, attention = await recover_speech_jobs(service)
        if attempt < job.max_attempts:
            assert (retried, attention) == (1, 0)
        else:
            assert (retried, attention) == (0, 1)
    assert outbox_status(store.jobs[job.id]) == "needs_attention"
    assert (
        await service.claim(ClaimJobCommand(worker_id="w9", kinds=(SPEECH_ANALYSIS_KIND,))) is None
    )


async def test_recovery_never_touches_a_completed_job_or_a_live_lease(
    service: JobService, store: FakeJobStore
) -> None:
    done, _ = await enqueue_speech_analysis(
        service, owner_id=1, recording_id=7, transcript_id=3, available_at=NOW
    )
    live, _ = await enqueue_speech_analysis(
        service, owner_id=1, recording_id=8, transcript_id=4, available_at=NOW
    )
    await service.claim(ClaimJobCommand(worker_id="w1", kinds=(SPEECH_ANALYSIS_KIND,)))
    await service.complete(job_id=done.id, command=CompleteJobCommand(worker_id="w1"))
    store.now = NOW + timedelta(seconds=SPEECH_LEASE_SECONDS + 1)
    await service.claim(ClaimJobCommand(worker_id="w2", kinds=(SPEECH_ANALYSIS_KIND,)))
    assert await recover_speech_jobs(service) == (0, 0)
    assert outbox_status(store.jobs[done.id]) == "published"
    assert outbox_status(store.jobs[live.id]) == "running"


async def test_a_replayed_enqueue_after_recovery_returns_the_same_job(
    service: JobService, store: FakeJobStore
) -> None:
    job, _ = await enqueue_speech_analysis(
        service, owner_id=1, recording_id=7, transcript_id=3, available_at=NOW
    )
    await service.claim(ClaimJobCommand(worker_id="w1", kinds=(SPEECH_ANALYSIS_KIND,)))
    store.now = NOW + timedelta(seconds=SPEECH_LEASE_SECONDS + 1)
    await recover_speech_jobs(service)
    again, replayed = await enqueue_speech_analysis(
        service, owner_id=1, recording_id=7, transcript_id=3, available_at=store.now
    )
    assert replayed and again.id == job.id

"""Speech analysis on the shared queue: identity, priority, one at a time, and outbox status."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from tamforge_backend.jobs.schemas import (
    ClaimJobCommand,
    CompleteJobCommand,
    EnqueueJobCommand,
    JobFailure,
    ReferencePayload,
    RetryJobCommand,
)
from tamforge_backend.jobs.service import JobService
from tamforge_backend.speech.jobs import (
    CLAUDE_ANALYSIS_PRIORITY,
    INGEST_PRIORITY,
    SPEECH_ANALYSIS_KIND,
    SPEECH_PRIORITY,
    SpeechScheduler,
    SpeechSchedulingError,
    SpeechWorkerRegistration,
    enqueue_speech_analysis,
    outbox_status,
    speech_idempotency_key,
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


async def test_one_recording_and_transcript_enqueue_one_job_however_often_replayed(
    service: JobService,
) -> None:
    first, replayed_first = await enqueue_speech_analysis(
        service, owner_id=1, recording_id=7, transcript_id=3, available_at=NOW
    )
    second, replayed_second = await enqueue_speech_analysis(
        service, owner_id=1, recording_id=7, transcript_id=3, available_at=NOW
    )
    assert (replayed_first, replayed_second) == (False, True)
    assert first.id == second.id and first.kind == SPEECH_ANALYSIS_KIND
    assert first.payload == ReferencePayload(subject_id=7, related_id=3)
    assert first.idempotency_key == speech_idempotency_key(recording_id=7, transcript_id=3)


async def test_a_new_transcript_for_the_same_recording_is_a_new_job(service: JobService) -> None:
    a, _ = await enqueue_speech_analysis(
        service, owner_id=1, recording_id=7, transcript_id=3, available_at=NOW
    )
    b, _ = await enqueue_speech_analysis(
        service, owner_id=1, recording_id=7, transcript_id=4, available_at=NOW
    )
    assert a.id != b.id


def test_speech_sits_below_ingest_and_above_claude_on_the_shared_queue() -> None:
    assert INGEST_PRIORITY > SPEECH_PRIORITY > CLAUDE_ANALYSIS_PRIORITY


async def test_the_shared_queue_hands_out_ingest_before_speech_before_claude(
    service: JobService,
) -> None:
    await service.enqueue(
        owner_id=1,
        command=EnqueueJobCommand(
            kind="claude_analysis",
            payload=ReferencePayload(subject_id=1),
            priority=CLAUDE_ANALYSIS_PRIORITY,
            available_at=NOW,
        ),
        idempotency_key="c1",
    )
    await enqueue_speech_analysis(
        service, owner_id=1, recording_id=7, transcript_id=3, available_at=NOW
    )
    await service.enqueue(
        owner_id=1,
        command=EnqueueJobCommand(
            kind="ingest_ack",
            payload=ReferencePayload(subject_id=1),
            priority=INGEST_PRIORITY,
            available_at=NOW,
        ),
        idempotency_key="i1",
    )
    order = []
    while True:
        job = await service.claim(
            ClaimJobCommand(
                worker_id="w", kinds=("ingest_ack", SPEECH_ANALYSIS_KIND, "claude_analysis")
            )
        )
        if job is None:
            break
        order.append(job.kind)
    assert order == ["ingest_ack", SPEECH_ANALYSIS_KIND, "claude_analysis"]


async def test_the_speech_worker_claims_only_its_own_kind(service: JobService) -> None:
    await service.enqueue(
        owner_id=1,
        command=EnqueueJobCommand(
            kind="ingest_ack",
            payload=ReferencePayload(subject_id=1),
            priority=INGEST_PRIORITY,
            available_at=NOW,
        ),
        idempotency_key="i1",
    )
    scheduler = SpeechScheduler(service, SpeechWorkerRegistration(worker_id="speech-1"))
    assert await scheduler.claim_next() is None
    await enqueue_speech_analysis(
        service, owner_id=1, recording_id=7, transcript_id=3, available_at=NOW
    )
    job = await scheduler.claim_next()
    assert job is not None and job.kind == SPEECH_ANALYSIS_KIND and job.lease_owner == "speech-1"


async def test_one_speech_job_runs_at_a_time(service: JobService) -> None:
    for t in (3, 4):
        await enqueue_speech_analysis(
            service, owner_id=1, recording_id=7, transcript_id=t, available_at=NOW
        )
    scheduler = SpeechScheduler(service, SpeechWorkerRegistration(worker_id="speech-1"))
    first = await scheduler.claim_next()
    assert first is not None
    with pytest.raises(SpeechSchedulingError, match="one speech job"):
        await scheduler.claim_next()
    await service.complete(job_id=first.id, command=CompleteJobCommand(worker_id="speech-1"))
    scheduler.release()
    second = await scheduler.claim_next()
    assert second is not None and second.id != first.id


async def test_outbox_status_follows_the_queue_state(
    service: JobService, store: FakeJobStore
) -> None:
    job, _ = await enqueue_speech_analysis(
        service, owner_id=1, recording_id=7, transcript_id=3, available_at=NOW
    )
    assert outbox_status(job) == "queued"
    running = await service.claim(
        ClaimJobCommand(worker_id="speech-1", kinds=(SPEECH_ANALYSIS_KIND,))
    )
    assert running is not None and outbox_status(running) == "running"
    retried = await service.retry(
        job_id=job.id,
        command=RetryJobCommand(
            worker_id="speech-1",
            failure=JobFailure(category="transient_dependency", retry_after_seconds=5),
        ),
    )
    assert retried.disposition == "retry_wait" and outbox_status(retried.job) == "queued"
    store.now = NOW + timedelta(seconds=10)
    again = await service.claim(
        ClaimJobCommand(worker_id="speech-1", kinds=(SPEECH_ANALYSIS_KIND,))
    )
    assert again is not None
    done = await service.complete(job_id=job.id, command=CompleteJobCommand(worker_id="speech-1"))
    assert outbox_status(done) == "published"


async def test_a_permanent_failure_reads_as_needs_attention(service: JobService) -> None:
    job, _ = await enqueue_speech_analysis(
        service, owner_id=1, recording_id=7, transcript_id=3, available_at=NOW
    )
    await service.claim(ClaimJobCommand(worker_id="speech-1", kinds=(SPEECH_ANALYSIS_KIND,)))
    result = await service.retry(
        job_id=job.id,
        command=RetryJobCommand(worker_id="speech-1", failure=JobFailure(category="invalid_input")),
    )
    assert (
        result.disposition == "needs_attention" and outbox_status(result.job) == "needs_attention"
    )


def test_a_speech_job_must_name_a_recording_and_a_transcript() -> None:
    with pytest.raises(SpeechSchedulingError):
        speech_idempotency_key(recording_id=0, transcript_id=1)

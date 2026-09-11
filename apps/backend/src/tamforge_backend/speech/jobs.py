"""Speech analysis on the queue that already exists, and nothing that does not.

The server has one durable job queue, in PostgreSQL, with claims, leases, heartbeats,
bounded retries and reclaim of expired leases. Speech analysis reuses it whole. What this
module owns is only the part that is specific to speech: which kind the speech worker
registers for, where it sits in priority (below ingest acknowledgement, which is what the
learner is waiting on, and above Claude analysis, which is what speech feeds), how a job's
state reads back as a recording's processing status, and the rule that one speech job runs
at a time on the Mac-sized host.

Idempotency is by identity: one recording and one transcript enqueue the same job however
many times the request is replayed, so a retried upload never produces a second analysis.
Recovery is the queue's own reclaim of expired leases; the speech worker adds nothing to it
except the promise that a reclaimed job is picked up again in priority order.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal

from ..jobs.schemas import ClaimJobCommand, EnqueueJobCommand, JobResponse, ReferencePayload
from ..jobs.service import JobService

SPEECH_ANALYSIS_KIND: Final = "speech_analysis"

# Priorities on the shared queue. Ingest acknowledgement is what the learner waits on and
# outranks everything; speech analysis feeds Claude analysis, so it runs before it.
INGEST_PRIORITY: Final = 100
SPEECH_PRIORITY: Final = 60
CLAUDE_ANALYSIS_PRIORITY: Final = 40

SPEECH_MAX_ATTEMPTS: Final = 3
SPEECH_LEASE_SECONDS: Final = 600

ProcessingStatus = Literal["queued", "running", "published", "needs_attention", "canceled"]


class SpeechSchedulingError(ValueError):
    """A speech job command that breaks the one-at-a-time or identity rules."""


def speech_idempotency_key(*, recording_id: int, transcript_id: int) -> str:
    if recording_id <= 0 or transcript_id <= 0:
        raise SpeechSchedulingError("a speech job names a recording and a transcript")
    return f"speech-analysis-r{recording_id}-t{transcript_id}"


def speech_analysis_command(
    *, recording_id: int, transcript_id: int, available_at: datetime
) -> EnqueueJobCommand:
    return EnqueueJobCommand(
        kind=SPEECH_ANALYSIS_KIND,
        payload=ReferencePayload(subject_id=recording_id, related_id=transcript_id),
        priority=SPEECH_PRIORITY,
        available_at=available_at,
        max_attempts=SPEECH_MAX_ATTEMPTS,
    )


async def enqueue_speech_analysis(
    service: JobService,
    *,
    owner_id: int,
    recording_id: int,
    transcript_id: int,
    available_at: datetime,
) -> tuple[JobResponse, bool]:
    """Enqueue once per (recording, transcript); a replay returns the existing job."""
    result = await service.enqueue(
        owner_id=owner_id,
        command=speech_analysis_command(
            recording_id=recording_id, transcript_id=transcript_id, available_at=available_at
        ),
        idempotency_key=speech_idempotency_key(
            recording_id=recording_id, transcript_id=transcript_id
        ),
    )
    return result.job, result.replayed


@dataclass(frozen=True, slots=True)
class SpeechWorkerRegistration:
    """The speech worker's claim: one kind, one lease length, one job at a time."""

    worker_id: str
    lease_seconds: int = SPEECH_LEASE_SECONDS

    def claim_command(self) -> ClaimJobCommand:
        return ClaimJobCommand(
            worker_id=self.worker_id,
            kinds=(SPEECH_ANALYSIS_KIND,),
            lease_seconds=self.lease_seconds,
        )


class SpeechScheduler:
    """Claims speech jobs through the shared queue, never more than one at a time."""

    def __init__(self, service: JobService, registration: SpeechWorkerRegistration) -> None:
        self._service = service
        self._registration = registration
        self._held: JobResponse | None = None

    @property
    def held(self) -> JobResponse | None:
        return self._held

    async def claim_next(self) -> JobResponse | None:
        if self._held is not None:
            raise SpeechSchedulingError("one speech job runs at a time; release the current one")
        job = await self._service.claim(self._registration.claim_command())
        if job is not None and job.kind != SPEECH_ANALYSIS_KIND:
            raise SpeechSchedulingError("the queue handed the speech worker a job of another kind")
        self._held = job
        return job

    def release(self) -> None:
        self._held = None


def outbox_status(job: JobResponse) -> ProcessingStatus:
    """How a queue state reads back to the recording's processing status."""
    if job.state == "queued":
        return "queued"
    if job.state == "running":
        return "running"
    if job.state == "succeeded":
        return "published"
    if job.state == "canceled":
        return "canceled"
    return "needs_attention"


async def recover_speech_jobs(service: JobService, *, limit: int = 100) -> tuple[int, int]:
    """Reclaim expired leases through the queue's own recovery; returns (retried, attention)."""
    result = await service.reclaim_expired(limit=limit)
    return len(result.retried_job_ids), len(result.needs_attention_job_ids)


__all__ = [
    "CLAUDE_ANALYSIS_PRIORITY",
    "INGEST_PRIORITY",
    "SPEECH_ANALYSIS_KIND",
    "SPEECH_LEASE_SECONDS",
    "SPEECH_MAX_ATTEMPTS",
    "SPEECH_PRIORITY",
    "ProcessingStatus",
    "SpeechScheduler",
    "SpeechSchedulingError",
    "SpeechWorkerRegistration",
    "enqueue_speech_analysis",
    "outbox_status",
    "recover_speech_jobs",
    "speech_analysis_command",
    "speech_idempotency_key",
]

"""An in-memory JobStore with the queue's real rules, for tests that need no database."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from tamforge_backend.jobs.policy import ClaimCandidate, order_claim_candidates, retry_disposition

from ..jobs.schemas import (
    ClaimJobCommand,
    CompleteJobCommand,
    EnqueueJobCommand,
    EnqueueResult,
    HeartbeatJobCommand,
    JobResponse,
    ReclaimResult,
    RetryJobCommand,
    RetryResult,
)
from ..jobs.service import JobConflict, JobNotFound


@dataclass
class FakeJobStore:
    now: datetime
    jobs: dict[int, JobResponse] = field(default_factory=dict)
    _next: int = 1

    def _put(self, job: JobResponse) -> JobResponse:
        self.jobs[job.id] = job
        return job

    async def enqueue(
        self, *, owner_id: int, command: EnqueueJobCommand, idempotency_key: str
    ) -> EnqueueResult:
        for job in self.jobs.values():
            if job.owner_id == owner_id and job.idempotency_key == idempotency_key:
                return EnqueueResult(job=job, replayed=True)
        job = JobResponse(
            id=self._next,
            owner_id=owner_id,
            kind=command.kind,
            payload=command.payload,
            priority=command.priority,
            state="queued",
            idempotency_key=idempotency_key,
            available_at=command.available_at,
            attempt_count=0,
            max_attempts=command.max_attempts,
            lease_owner=None,
            lease_expires_at=None,
            last_error_category=None,
            last_error_details=None,
            created_at=self.now,
            updated_at=self.now,
            started_at=None,
            completed_at=None,
        )
        self._next += 1
        return EnqueueResult(job=self._put(job), replayed=False)

    async def claim(self, *, command: ClaimJobCommand) -> JobResponse | None:
        candidates = [
            ClaimCandidate(id=j.id, priority=j.priority, available_at=j.available_at)
            for j in self.jobs.values()
            if j.state == "queued" and j.kind in command.kinds and j.available_at <= self.now
        ]
        ordered = order_claim_candidates(tuple(candidates))
        if not ordered:
            return None
        job = self.jobs[ordered[0].id]
        return self._put(
            job.model_copy(
                update={
                    "state": "running",
                    "attempt_count": job.attempt_count + 1,
                    "lease_owner": command.worker_id,
                    "lease_expires_at": self.now + timedelta(seconds=command.lease_seconds),
                    "started_at": self.now,
                    "updated_at": self.now,
                }
            )
        )

    async def heartbeat(self, *, job_id: int, command: HeartbeatJobCommand) -> JobResponse:
        job = self._running(job_id, command.worker_id)
        return self._put(
            job.model_copy(
                update={"lease_expires_at": self.now + timedelta(seconds=command.lease_seconds)}
            )
        )

    async def complete(self, *, job_id: int, command: CompleteJobCommand) -> JobResponse:
        job = self._running(job_id, command.worker_id)
        return self._put(
            job.model_copy(
                update={
                    "state": "succeeded",
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "completed_at": self.now,
                    "updated_at": self.now,
                }
            )
        )

    async def retry(self, *, job_id: int, command: RetryJobCommand) -> RetryResult:
        job = self._running(job_id, command.worker_id)
        disposition = retry_disposition(
            attempt_count=job.attempt_count,
            max_attempts=job.max_attempts,
            category=command.failure.category,
        )
        state = "queued" if disposition == "retry_wait" else "failed"
        delay = timedelta(seconds=command.failure.retry_after_seconds or 0)
        return RetryResult(
            job=self._put(
                job.model_copy(
                    update={
                        "state": state,
                        "lease_owner": None,
                        "lease_expires_at": None,
                        "available_at": self.now + delay,
                        "last_error_category": command.failure.category,
                        "updated_at": self.now,
                    }
                )
            ),
            disposition=disposition,
        )

    async def cancel(self, *, owner_id: int, job_id: int) -> JobResponse:
        job = self.jobs.get(job_id)
        if job is None or job.owner_id != owner_id:
            raise JobNotFound("job not found")
        if job.state not in {"queued", "running"}:
            raise JobConflict("job is finished")
        return self._put(
            job.model_copy(
                update={"state": "canceled", "lease_owner": None, "lease_expires_at": None}
            )
        )

    async def reclaim_expired(self, *, limit: int) -> ReclaimResult:
        retried: list[int] = []
        attention: list[int] = []
        for job in list(self.jobs.values())[:limit]:
            if job.state != "running" or job.lease_expires_at is None:
                continue
            if job.lease_expires_at > self.now:
                continue
            if job.attempt_count < job.max_attempts:
                retried.append(job.id)
                self._put(
                    job.model_copy(
                        update={"state": "queued", "lease_owner": None, "lease_expires_at": None}
                    )
                )
            else:
                attention.append(job.id)
                self._put(
                    job.model_copy(
                        update={"state": "failed", "lease_owner": None, "lease_expires_at": None}
                    )
                )
        return ReclaimResult(
            retried_job_ids=tuple(retried), needs_attention_job_ids=tuple(attention)
        )

    def _running(self, job_id: int, worker_id: str) -> JobResponse:
        job = self.jobs.get(job_id)
        if job is None:
            raise JobNotFound("job not found")
        if job.state != "running" or job.lease_owner != worker_id:
            raise JobConflict("job is not leased to this worker")
        return job


__all__ = ["FakeJobStore"]

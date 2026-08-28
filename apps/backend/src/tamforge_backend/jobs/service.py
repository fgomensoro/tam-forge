"""Application service for durable job lifecycle commands."""

from __future__ import annotations

import re
from typing import Protocol

from .schemas import (
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

_SAFE_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class JobError(Exception):
    """Base safe durable-job error."""


class JobNotFound(JobError):
    """The owner-scoped job does not exist."""


class JobConflict(JobError):
    """The job state, lease, or idempotency lineage conflicts."""


class JobInvalidRequest(JobError):
    """The job command is outside bounded policy."""


class JobStore(Protocol):
    async def enqueue(
        self,
        *,
        owner_id: int,
        command: EnqueueJobCommand,
        idempotency_key: str,
    ) -> EnqueueResult: ...

    async def claim(self, *, command: ClaimJobCommand) -> JobResponse | None: ...

    async def heartbeat(
        self, *, job_id: int, command: HeartbeatJobCommand
    ) -> JobResponse: ...

    async def complete(
        self, *, job_id: int, command: CompleteJobCommand
    ) -> JobResponse: ...

    async def retry(
        self, *, job_id: int, command: RetryJobCommand
    ) -> RetryResult: ...

    async def cancel(self, *, owner_id: int, job_id: int) -> JobResponse: ...

    async def reclaim_expired(self, *, limit: int) -> ReclaimResult: ...


class JobService:
    """Validate bounded commands and delegate one transactional mutation."""

    def __init__(self, store: JobStore) -> None:
        self._store = store

    async def enqueue(
        self,
        *,
        owner_id: int,
        command: EnqueueJobCommand,
        idempotency_key: str,
    ) -> EnqueueResult:
        if owner_id <= 0:
            raise JobInvalidRequest("owner is invalid")
        if _SAFE_KEY.fullmatch(idempotency_key) is None:
            raise JobInvalidRequest("Idempotency-Key is invalid")
        return await self._store.enqueue(
            owner_id=owner_id,
            command=command,
            idempotency_key=idempotency_key,
        )

    async def claim(self, command: ClaimJobCommand) -> JobResponse | None:
        return await self._store.claim(command=command)

    async def heartbeat(
        self, *, job_id: int, command: HeartbeatJobCommand
    ) -> JobResponse:
        self._positive_job_id(job_id)
        return await self._store.heartbeat(job_id=job_id, command=command)

    async def complete(
        self, *, job_id: int, command: CompleteJobCommand
    ) -> JobResponse:
        self._positive_job_id(job_id)
        return await self._store.complete(job_id=job_id, command=command)

    async def retry(
        self, *, job_id: int, command: RetryJobCommand
    ) -> RetryResult:
        self._positive_job_id(job_id)
        return await self._store.retry(job_id=job_id, command=command)

    async def cancel(self, *, owner_id: int, job_id: int) -> JobResponse:
        if owner_id <= 0:
            raise JobInvalidRequest("owner is invalid")
        self._positive_job_id(job_id)
        return await self._store.cancel(owner_id=owner_id, job_id=job_id)

    async def reclaim_expired(self, *, limit: int = 100) -> ReclaimResult:
        if not 1 <= limit <= 100:
            raise JobInvalidRequest("reclaim limit is invalid")
        return await self._store.reclaim_expired(limit=limit)

    @staticmethod
    def _positive_job_id(job_id: int) -> None:
        if job_id <= 0:
            raise JobInvalidRequest("job ID is invalid")


__all__ = [
    "JobConflict",
    "JobError",
    "JobInvalidRequest",
    "JobNotFound",
    "JobService",
    "JobStore",
]

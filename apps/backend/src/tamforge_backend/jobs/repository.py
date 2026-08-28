"""Transactional PostgreSQL queue with leases, retries, and crash recovery."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import cast

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.models import Owner
from ..database import transaction_scope
from ..models.base import utc_now
from ..notifications.models import BackgroundJob, OutboxEvent
from .policy import retry_disposition
from .schemas import (
    ClaimJobCommand,
    CompleteJobCommand,
    EnqueueJobCommand,
    EnqueueResult,
    HeartbeatJobCommand,
    JobResponse,
    JobState,
    ReclaimResult,
    ReferencePayload,
    RetryJobCommand,
    RetryResult,
)
from .service import JobConflict, JobInvalidRequest, JobNotFound


class SqlAlchemyJobRepository:
    """Store durable commands using database locks as the concurrency boundary."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._session = session
        self._clock = clock

    async def enqueue(
        self,
        *,
        owner_id: int,
        command: EnqueueJobCommand,
        idempotency_key: str,
    ) -> EnqueueResult:
        now = self._now()
        payload = command.payload.model_dump(mode="json", exclude_none=True)
        async with transaction_scope(self._session):
            owner = await self._session.scalar(
                select(Owner.id).where(Owner.id == owner_id).with_for_update()
            )
            if owner is None:
                raise JobNotFound("job owner was not found")
            existing = await self._session.scalar(
                select(BackgroundJob)
                .where(BackgroundJob.owner_id == owner_id)
                .where(BackgroundJob.idempotency_key == idempotency_key)
                .with_for_update()
            )
            if existing is not None:
                if not self._same_enqueue(existing, command, payload):
                    raise JobConflict("Idempotency-Key was reused for another job")
                return EnqueueResult(job=self._response(existing), replayed=True)
            job = BackgroundJob(
                owner_id=owner_id,
                kind=command.kind,
                payload_schema_version=1,
                payload=payload,
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
                created_at=now,
                updated_at=now,
                started_at=None,
                completed_at=None,
            )
            self._session.add(job)
            await self._session.flush()
            await self._status_event(job=job, event_type="background_job.queued", now=now)
            return EnqueueResult(job=self._response(job), replayed=False)

    async def claim(self, *, command: ClaimJobCommand) -> JobResponse | None:
        now = self._now()
        async with transaction_scope(self._session):
            job = await self._session.scalar(
                select(BackgroundJob)
                .where(BackgroundJob.state == "queued")
                .where(BackgroundJob.available_at <= now)
                .where(BackgroundJob.attempt_count < BackgroundJob.max_attempts)
                .where(BackgroundJob.kind.in_(command.kinds))
                .order_by(
                    BackgroundJob.priority.desc(),
                    BackgroundJob.available_at,
                    BackgroundJob.id,
                )
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if job is None:
                return None
            started_at = job.started_at or now
            await self._session.execute(
                update(BackgroundJob)
                .where(BackgroundJob.id == job.id)
                .values(
                    state="running",
                    attempt_count=job.attempt_count + 1,
                    lease_owner=command.worker_id,
                    lease_expires_at=now + timedelta(seconds=command.lease_seconds),
                    last_error_category=None,
                    last_error_details=None,
                    started_at=started_at,
                    updated_at=now,
                )
            )
            current = await self._reload(job.id)
            await self._status_event(
                job=current,
                event_type="background_job.running",
                now=now,
            )
            return self._response(current)

    async def heartbeat(
        self, *, job_id: int, command: HeartbeatJobCommand
    ) -> JobResponse:
        now = self._now()
        async with transaction_scope(self._session):
            job = await self._running_job(job_id, command.worker_id, now)
            assert job.lease_expires_at is not None
            lease_base = max(now, job.lease_expires_at)
            await self._session.execute(
                update(BackgroundJob)
                .where(BackgroundJob.id == job.id)
                .values(
                    lease_expires_at=lease_base
                    + timedelta(seconds=command.lease_seconds),
                    updated_at=now,
                )
            )
            return self._response(await self._reload(job.id))

    async def complete(
        self, *, job_id: int, command: CompleteJobCommand
    ) -> JobResponse:
        now = self._now()
        async with transaction_scope(self._session):
            job = await self._running_job(job_id, command.worker_id, now)
            await self._session.execute(
                update(BackgroundJob)
                .where(BackgroundJob.id == job.id)
                .values(
                    state="succeeded",
                    lease_owner=None,
                    lease_expires_at=None,
                    completed_at=now,
                    updated_at=now,
                )
            )
            current = await self._reload(job.id)
            await self._status_event(
                job=current,
                event_type="background_job.succeeded",
                now=now,
            )
            return self._response(current)

    async def retry(
        self, *, job_id: int, command: RetryJobCommand
    ) -> RetryResult:
        now = self._now()
        async with transaction_scope(self._session):
            job = await self._running_job(job_id, command.worker_id, now)
            disposition = retry_disposition(
                attempt_count=job.attempt_count,
                max_attempts=job.max_attempts,
                category=command.failure.category,
            )
            details = self._error_details(job.attempt_count, command)
            if disposition == "retry_wait":
                delay = command.failure.retry_after_seconds
                if delay is None:
                    delay = min(300, 5 * (2 ** (job.attempt_count - 1)))
                values: dict[str, object] = {
                    "state": "queued",
                    "available_at": now + timedelta(seconds=delay),
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "last_error_category": command.failure.category,
                    "last_error_details": details,
                    "updated_at": now,
                }
                event_type = "background_job.retry_wait"
            else:
                values = {
                    "state": "failed",
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "last_error_category": command.failure.category,
                    "last_error_details": details,
                    "completed_at": now,
                    "updated_at": now,
                }
                event_type = "background_job.needs_attention"
            await self._session.execute(
                update(BackgroundJob)
                .where(BackgroundJob.id == job.id)
                .values(**values)
            )
            current = await self._reload(job.id)
            await self._status_event(job=current, event_type=event_type, now=now)
            return RetryResult(job=self._response(current), disposition=disposition)

    async def cancel(self, *, owner_id: int, job_id: int) -> JobResponse:
        now = self._now()
        async with transaction_scope(self._session):
            job = await self._session.scalar(
                select(BackgroundJob)
                .where(BackgroundJob.owner_id == owner_id)
                .where(BackgroundJob.id == job_id)
                .with_for_update()
            )
            if job is None:
                raise JobNotFound("job was not found")
            if job.state == "canceled":
                return self._response(job)
            if job.state in {"succeeded", "failed"}:
                raise JobConflict("terminal job cannot be canceled")
            await self._session.execute(
                update(BackgroundJob)
                .where(BackgroundJob.id == job.id)
                .values(
                    state="canceled",
                    lease_owner=None,
                    lease_expires_at=None,
                    last_error_category=None,
                    last_error_details=None,
                    completed_at=now,
                    updated_at=now,
                )
            )
            current = await self._reload(job.id)
            await self._status_event(
                job=current,
                event_type="background_job.canceled",
                now=now,
            )
            return self._response(current)

    async def reclaim_expired(self, *, limit: int) -> ReclaimResult:
        now = self._now()
        retried: list[int] = []
        needs_attention: list[int] = []
        async with transaction_scope(self._session):
            jobs = tuple(
                (
                    await self._session.scalars(
                        select(BackgroundJob)
                        .where(BackgroundJob.state == "running")
                        .where(BackgroundJob.lease_expires_at <= now)
                        .order_by(BackgroundJob.lease_expires_at, BackgroundJob.id)
                        .limit(limit)
                        .with_for_update(skip_locked=True)
                    )
                ).all()
            )
            for job in jobs:
                details = {"schema_version": 1, "attempt": job.attempt_count}
                if job.attempt_count < job.max_attempts:
                    await self._session.execute(
                        update(BackgroundJob)
                        .where(BackgroundJob.id == job.id)
                        .values(
                            state="queued",
                            available_at=now,
                            lease_owner=None,
                            lease_expires_at=None,
                            last_error_category="transient_dependency",
                            last_error_details=details,
                            updated_at=now,
                        )
                    )
                    event_type = "background_job.retry_wait"
                    retried.append(job.id)
                else:
                    await self._session.execute(
                        update(BackgroundJob)
                        .where(BackgroundJob.id == job.id)
                        .values(
                            state="failed",
                            lease_owner=None,
                            lease_expires_at=None,
                            last_error_category="processing_failure",
                            last_error_details=details,
                            completed_at=now,
                            updated_at=now,
                        )
                    )
                    event_type = "background_job.needs_attention"
                    needs_attention.append(job.id)
                current = await self._reload(job.id)
                await self._status_event(job=current, event_type=event_type, now=now)
        return ReclaimResult(
            retried_job_ids=tuple(retried),
            needs_attention_job_ids=tuple(needs_attention),
        )

    async def _running_job(
        self, job_id: int, worker_id: str, now: datetime
    ) -> BackgroundJob:
        job = await self._session.scalar(
            select(BackgroundJob)
            .where(BackgroundJob.id == job_id)
            .with_for_update()
        )
        if job is None:
            raise JobNotFound("job was not found")
        if job.state != "running" or job.lease_owner != worker_id:
            raise JobConflict("worker does not own the running job lease")
        if job.lease_expires_at is None or job.lease_expires_at <= now:
            raise JobConflict("job lease has expired")
        return job

    async def _reload(self, job_id: int) -> BackgroundJob:
        self._session.expire_all()
        job = await self._session.get(BackgroundJob, job_id)
        if job is None:
            raise JobNotFound("job was not found")
        return job

    async def _status_event(
        self, *, job: BackgroundJob, event_type: str, now: datetime
    ) -> None:
        self._session.add(
            OutboxEvent(
                owner_id=job.owner_id,
                aggregate_type="background_job",
                aggregate_id=job.id,
                event_type=event_type,
                payload_schema_version=1,
                payload={"schema_version": 1, "subject_id": job.id},
                occurred_at=now,
                published_at=None,
                attempts=0,
                idempotency_key=(
                    f"job:{job.id}:{event_type}:{job.attempt_count}"
                ),
            )
        )
        await self._session.flush()

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise JobInvalidRequest("repository clock must be timezone-aware")
        return now

    @staticmethod
    def _same_enqueue(
        job: BackgroundJob,
        command: EnqueueJobCommand,
        payload: dict[str, object],
    ) -> bool:
        return (
            job.kind == command.kind
            and job.payload == payload
            and job.priority == command.priority
            and job.available_at == command.available_at
            and job.max_attempts == command.max_attempts
        )

    @staticmethod
    def _error_details(
        attempt: int, command: RetryJobCommand
    ) -> dict[str, int]:
        details = {"schema_version": 1, "attempt": attempt}
        if command.failure.retry_after_seconds is not None:
            details["retry_after_seconds"] = command.failure.retry_after_seconds
        if command.failure.http_status is not None:
            details["http_status"] = command.failure.http_status
        return details

    @staticmethod
    def _response(job: BackgroundJob) -> JobResponse:
        return JobResponse(
            id=job.id,
            owner_id=job.owner_id,
            kind=job.kind,
            payload=ReferencePayload.model_validate(job.payload),
            priority=job.priority,
            state=cast(JobState, job.state),
            idempotency_key=job.idempotency_key,
            available_at=job.available_at,
            attempt_count=job.attempt_count,
            max_attempts=job.max_attempts,
            lease_owner=job.lease_owner,
            lease_expires_at=job.lease_expires_at,
            last_error_category=job.last_error_category,
            last_error_details=job.last_error_details,
            created_at=job.created_at,
            updated_at=job.updated_at,
            started_at=job.started_at,
            completed_at=job.completed_at,
        )


__all__ = ["SqlAlchemyJobRepository"]

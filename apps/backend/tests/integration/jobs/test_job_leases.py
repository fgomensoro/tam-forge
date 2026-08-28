"""PostgreSQL lease, retry, idempotency, and crash-recovery tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

pytestmark = pytest.mark.integration


def test_durable_jobs_are_idempotent_leased_bounded_and_cancelable(
    test_database_url: str,
) -> None:
    from alembic import command as alembic_command
    from alembic.config import Config
    from sqlalchemy import create_engine, func, select, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from tamforge_backend.database import database_url_to_sync
    from tamforge_backend.jobs.repository import SqlAlchemyJobRepository
    from tamforge_backend.jobs.schemas import (
        ClaimJobCommand,
        CompleteJobCommand,
        EnqueueJobCommand,
        HeartbeatJobCommand,
        RetryJobCommand,
    )
    from tamforge_backend.jobs.service import JobService
    from tamforge_backend.notifications.models import BackgroundJob, OutboxEvent

    config = Config("apps/backend/alembic.ini")
    config.attributes["database_url"] = test_database_url
    alembic_command.downgrade(config, "base")
    alembic_command.upgrade(config, "head")
    sync_engine = create_engine(database_url_to_sync(test_database_url))
    try:
        with sync_engine.begin() as connection:
            owner_id = connection.execute(
                text(
                    "INSERT INTO owners (github_user_id, github_login) "
                    "VALUES (102269369, 'fgomensoro') RETURNING id"
                )
            ).scalar_one()
    finally:
        sync_engine.dispose()

    async def exercise() -> None:
        engine = create_async_engine(
            make_url(test_database_url).set(drivername="postgresql+asyncpg")
        )
        factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        start = datetime(2026, 8, 28, 12, tzinfo=UTC)

        async def enqueue(
            *, key: str, priority: int, max_attempts: int = 2
        ):  # type: ignore[no-untyped-def]
            async with factory() as session:
                return await JobService(
                    SqlAlchemyJobRepository(session, clock=lambda: start)
                ).enqueue(
                    owner_id=owner_id,
                    command=EnqueueJobCommand(
                        kind="transcribe_activity",
                        payload={"schema_version": 1, "subject_id": priority + 1},
                        priority=priority,
                        available_at=start - timedelta(minutes=1),
                        max_attempts=max_attempts,
                    ),
                    idempotency_key=key,
                )

        try:
            low = await enqueue(key="job-low", priority=20)
            high_a = await enqueue(key="job-high-a", priority=80)
            high_b = await enqueue(key="job-high-b", priority=80)
            replay = await enqueue(key="job-high-a", priority=80)
            assert replay.replayed is True
            assert replay.job.id == high_a.job.id

            async def claim(worker: str):  # type: ignore[no-untyped-def]
                async with factory() as session:
                    return await JobService(
                        SqlAlchemyJobRepository(session, clock=lambda: start)
                    ).claim(
                        ClaimJobCommand(
                            worker_id=worker,
                            kinds=("transcribe_activity",),
                            lease_seconds=30,
                        )
                    )

            first, second = await asyncio.gather(claim("worker-1"), claim("worker-2"))
            assert first is not None and second is not None
            assert {first.id, second.id} == {high_a.job.id, high_b.job.id}
            assert low.job.id not in {first.id, second.id}

            async with factory() as session:
                repository = SqlAlchemyJobRepository(session, clock=lambda: start)
                service = JobService(repository)
                extended = await service.heartbeat(
                    job_id=first.id,
                    command=HeartbeatJobCommand(
                        worker_id=first.lease_owner or "",
                        lease_seconds=30,
                    ),
                )
                assert extended.lease_expires_at is not None
                assert first.lease_expires_at is not None
                assert extended.lease_expires_at > first.lease_expires_at
                completed = await service.complete(
                    job_id=first.id,
                    command=CompleteJobCommand(
                        worker_id=first.lease_owner or "",
                    ),
                )
                assert completed.state == "succeeded"

            async with factory() as session:
                retried = await JobService(
                    SqlAlchemyJobRepository(session, clock=lambda: start)
                ).retry(
                    job_id=second.id,
                    command=RetryJobCommand(
                        worker_id=second.lease_owner or "",
                        failure={
                            "category": "transient_dependency",
                            "retry_after_seconds": 30,
                        },
                    ),
                )
                assert retried.disposition == "retry_wait"
                assert retried.job.state == "queued"

            async with factory() as session:
                canceled = await JobService(
                    SqlAlchemyJobRepository(session, clock=lambda: start)
                ).cancel(owner_id=owner_id, job_id=low.job.id)
                assert canceled.state == "canceled"
                assert canceled.attempt_count == 0

            async with factory() as session:
                not_ready = await JobService(
                    SqlAlchemyJobRepository(
                        session,
                        clock=lambda: start + timedelta(seconds=29),
                    )
                ).claim(
                    ClaimJobCommand(
                        worker_id="worker-3",
                        kinds=("transcribe_activity",),
                        lease_seconds=30,
                    )
                )
                assert not_ready is None

            async with factory() as session:
                reclaimed_claim = await JobService(
                    SqlAlchemyJobRepository(
                        session,
                        clock=lambda: start + timedelta(seconds=31),
                    )
                ).claim(
                    ClaimJobCommand(
                        worker_id="worker-crashed",
                        kinds=("transcribe_activity",),
                        lease_seconds=30,
                    )
                )
                assert reclaimed_claim is not None
                assert reclaimed_claim.id == second.id
                assert reclaimed_claim.attempt_count == 2

            async with factory() as session:
                recovered = await JobService(
                    SqlAlchemyJobRepository(
                        session,
                        clock=lambda: start + timedelta(seconds=62),
                    )
                ).reclaim_expired()
                assert recovered.retried_job_ids == ()
                assert recovered.needs_attention_job_ids == (second.id,)

            async with factory() as session:
                failed = await session.get(BackgroundJob, second.id)
                assert failed is not None
                assert failed.state == "failed"
                assert failed.last_error_category == "processing_failure"
                assert await session.scalar(
                    select(func.count()).select_from(BackgroundJob)
                ) == 3
                assert await session.scalar(
                    select(func.count()).select_from(OutboxEvent)
                ) == 10
        finally:
            await engine.dispose()

    try:
        asyncio.run(exercise())
    finally:
        # The migration deliberately refuses to downgrade canceled jobs. Remove
        # this test's isolated rows so the shared integration database remains
        # reversible for the next test.
        cleanup_engine = create_engine(database_url_to_sync(test_database_url))
        try:
            with cleanup_engine.begin() as connection:
                connection.execute(
                    text("DELETE FROM outbox_events WHERE owner_id = :owner"),
                    {"owner": owner_id},
                )
                connection.execute(
                    text("DELETE FROM background_jobs WHERE owner_id = :owner"),
                    {"owner": owner_id},
                )
                connection.execute(
                    text("DELETE FROM owners WHERE id = :owner"),
                    {"owner": owner_id},
                )
        finally:
            cleanup_engine.dispose()

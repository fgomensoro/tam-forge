"""The housekeeping worker: deliver the outbox and reclaim expired job leases."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..jobs.repository import SqlAlchemyJobRepository
from ..jobs.service import JobService
from ..notifications.repository import SqlAlchemyNotificationRepository
from .runtime import run_main

WORKER_NAME = "general"
INTERVAL_SECONDS = 15.0
BATCH_LIMIT = 100


async def housekeeping_step(sessions: async_sessionmaker[AsyncSession]) -> str | None:
    async with sessions() as session:
        await SqlAlchemyNotificationRepository(session).deliver_outbox(limit=BATCH_LIMIT)
    async with sessions() as session:
        await JobService(SqlAlchemyJobRepository(session)).reclaim_expired(limit=BATCH_LIMIT)
    return None


def main() -> int:
    return run_main(WORKER_NAME, housekeeping_step, interval_seconds=INTERVAL_SECONDS)


if __name__ == "__main__":  # pragma: no cover - process entrypoint
    raise SystemExit(main())

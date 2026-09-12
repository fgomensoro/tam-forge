"""Worker heartbeats cross the process boundary through one small table.

The health registry lives in the API process; a worker is another process on the
same host. Each worker writes one row per beat, and the API reads the rows on its
own heartbeat and reports them into the registry, which still applies its own
expiry: a worker that stops writing becomes `stale`, never silently `ok`.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from types import MappingProxyType

from sqlalchemy import DateTime, Text, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from ..models.base import Base, utc_now
from .health import HealthRegistry
from .logging import REASONS

# Worker name -> the health component it stands for. Workers without a component
# still beat (ops can read the table); readiness only knows these.
WORKER_COMPONENTS: Mapping[str, str] = MappingProxyType(
    {"general": "resources", "speech": "speech", "claude": "claude"}
)
MAX_HEARTBEAT_AGE = timedelta(seconds=60)


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"

    worker: Mapped[str] = mapped_column(Text, primary_key=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WorkerHeartbeatStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = session_factory

    async def beat(self, *, worker: str, status: str, reason: str) -> None:
        if status not in {"ok", "needs_attention", "unknown"} or reason not in REASONS:
            raise ValueError("invalid worker heartbeat")
        async with self._sessions() as session, session.begin():
            statement = insert(WorkerHeartbeat).values(
                worker=worker, status=status, reason=reason, observed_at=utc_now()
            )
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=[WorkerHeartbeat.worker],
                    set_={
                        "status": statement.excluded.status,
                        "reason": statement.excluded.reason,
                        "observed_at": statement.excluded.observed_at,
                    },
                )
            )

    async def recent(self, *, now: datetime) -> dict[str, tuple[str, str]]:
        """Beats younger than the registry lifetime, keyed by worker."""
        async with self._sessions() as session:
            rows = (await session.execute(select(WorkerHeartbeat))).scalars()
            result = {
                row.worker: (row.status, row.reason)
                for row in rows
                if timedelta(0) <= now - row.observed_at <= MAX_HEARTBEAT_AGE
            }
            await session.rollback()
            return result


async def report_worker_heartbeats(
    registry: HealthRegistry, store: WorkerHeartbeatStore, *, now: datetime
) -> None:
    """Report every fresh worker beat into the registry; absent workers stay unknown."""
    recent = await store.recent(now=now)
    for worker, component in WORKER_COMPONENTS.items():
        beat = recent.get(worker)
        if beat is None:
            continue
        status, reason = beat
        registry.report(component, status, reason)


__all__ = [
    "MAX_HEARTBEAT_AGE",
    "WORKER_COMPONENTS",
    "WorkerHeartbeat",
    "WorkerHeartbeatStore",
    "report_worker_heartbeats",
]

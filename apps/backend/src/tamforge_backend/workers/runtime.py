"""The loop every worker process shares: beat, do one step, sleep, repeat.

A step that raises is reported as `needs_attention` with a closed reason and the
loop keeps going; the process only exits on cancellation (systemd stop). Nothing
about the exception text is logged, because a step's error can carry owner content.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..database import HasDatabaseUrl, create_database_resources
from ..observability.heartbeats import WorkerHeartbeatStore
from ..observability.logging import safe_event

Step = Callable[[async_sessionmaker[AsyncSession]], Awaitable[str | None]]
"""One unit of work. Returns None when healthy, or a REASONS entry to report."""

logger = logging.getLogger("tamforge.workers")


async def run_worker(
    name: str,
    step: Step,
    *,
    settings: HasDatabaseUrl | None = None,
    interval_seconds: float = 15.0,
    iterations: int | None = None,
) -> None:
    from .settings import WorkerSettings

    configured = settings or WorkerSettings()
    database = create_database_resources(configured)
    store = WorkerHeartbeatStore(database.session_factory)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(signum, stop.set)
        except (NotImplementedError, RuntimeError):  # pragma: no cover - platform-specific
            pass
    logger.info(safe_event("worker_started", worker=name))
    try:
        count = 0
        while not stop.is_set() and (iterations is None or count < iterations):
            count += 1
            try:
                reason = await step(database.session_factory)
            except asyncio.CancelledError:
                raise
            except Exception:
                reason = "processing_failure"
            status = "ok" if reason is None else "needs_attention"
            try:
                await store.beat(worker=name, status=status, reason=reason or "none")
            except Exception:
                logger.warning(safe_event("worker_heartbeat_failed", worker=name))
            logger.info(safe_event("worker_step", worker=name, status=status))
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
            except TimeoutError:
                continue
    finally:
        await database.dispose()
        logger.info(safe_event("worker_stopped", worker=name))


def run_main(name: str, step: Step, *, interval_seconds: float) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        asyncio.run(run_worker(name, step, interval_seconds=interval_seconds))
    except KeyboardInterrupt:  # pragma: no cover - interactive stop
        pass
    return 0


__all__ = ["Step", "run_main", "run_worker"]

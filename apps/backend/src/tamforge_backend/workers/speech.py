"""The speech worker: turn each submitted transcript into stored turns and metrics.

One job at a time from the shared queue. A transient store failure retries under the
queue's own policy; a transcript that cannot be analysed ends the job in
`needs_attention` with a closed category the app can show. Nothing is dropped: the
job row keeps the outcome, and `GET /recordings/{id}/analysis` reads it back.
"""

from __future__ import annotations

import socket

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..jobs.repository import SqlAlchemyJobRepository
from ..jobs.schemas import CompleteJobCommand, JobFailure, RetryJobCommand
from ..jobs.service import JobService
from ..speech.analysis import SpeechAnalysisInvalid, SpeechAnalysisService
from ..speech.jobs import SpeechScheduler, SpeechWorkerRegistration
from .runtime import run_main

WORKER_NAME = "speech"
INTERVAL_SECONDS = 5.0
JOBS_PER_STEP = 10


def worker_id() -> str:
    host = "".join(ch if ch.isalnum() else "-" for ch in socket.gethostname())[:40]
    return f"speech-{host or 'worker'}"


async def analysis_step(sessions: async_sessionmaker[AsyncSession]) -> str | None:
    """Drain up to a few queued speech jobs; the heartbeat says whether the worker is fine."""
    registration = SpeechWorkerRegistration(worker_id=worker_id())
    for _ in range(JOBS_PER_STEP):
        async with sessions() as session:
            service = JobService(SqlAlchemyJobRepository(session))
            scheduler = SpeechScheduler(service, registration)
            job = await scheduler.claim_next()
            if job is None:
                return None
            try:
                await SpeechAnalysisService(session).process(
                    owner_id=job.owner_id, recording_pk=job.payload.subject_id
                )
            except SpeechAnalysisInvalid:
                await service.retry(
                    job_id=job.id,
                    command=RetryJobCommand(
                        worker_id=registration.worker_id,
                        failure=JobFailure(category="invalid_input"),
                    ),
                )
            except SQLAlchemyError:
                await session.rollback()
                await service.retry(
                    job_id=job.id,
                    command=RetryJobCommand(
                        worker_id=registration.worker_id,
                        failure=JobFailure(category="transient_dependency"),
                    ),
                )
            else:
                await service.complete(
                    job_id=job.id, command=CompleteJobCommand(worker_id=registration.worker_id)
                )
            finally:
                scheduler.release()
    return None


def main() -> int:
    return run_main(WORKER_NAME, analysis_step, interval_seconds=INTERVAL_SECONDS)


if __name__ == "__main__":  # pragma: no cover - process entrypoint
    raise SystemExit(main())

"""The one worker allowed to run Claude, with one lease and one published result.

Three properties matter more than the handler's shape. Only one Claude job runs at a
time, because a personal subscription is not a pool. A job that already published its
result is never invoked again, so retrying a crashed worker costs nothing and cannot
publish twice. And a failure publishes nothing at all, which is what keeps a Claude
outage from erasing the deterministic work that was already durable.

Quota and authentication failures are not retried. Neither improves by being asked
again inside the same minute, and both need a human.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..agents.roles.class_analysis import ClassAnalysisService
from ..agents.roles.debrief import DebriefService
from ..agents.roles.reviewer import ReviewerService
from ..agents.runtime import (
    AgentAuthenticationFailed,
    AgentOutputInvalid,
    AgentQuotaExhausted,
    AgentServiceUnavailable,
    AgentTimeout,
    AgentTurnsExceeded,
    BoundedClaudeRuntime,
    PreparedAgentRun,
    ValidatedAgentResult,
)

CLAUDE_JOB_TYPES: tuple[str, ...] = (
    "claude.review",
    "claude.analyze",
    "claude.plan",
    "claude.followup",
)

# Two extra tries for a transient dependency, then stop. A third is rarely the one
# that works and always the one that spends quota.
MAX_TRANSIENT_RETRIES = 2

Outcome = Literal["published", "replayed", "deferred", "needs_attention"]

# Every failure this worker can report, mapped from the runtime's error vocabulary.
FAILURE_REASONS: Mapping[type[Exception], str] = {
    AgentQuotaExhausted: "quota_exhausted",
    AgentAuthenticationFailed: "authentication_rejected",
    AgentOutputInvalid: "output_invalid",
    AgentTimeout: "timeout",
    AgentTurnsExceeded: "turns_exceeded",
    AgentServiceUnavailable: "service_unavailable",
}


@dataclass(frozen=True, slots=True)
class WorkerOutcome:
    outcome: Outcome
    reason: str
    result: ValidatedAgentResult | None = None


class RunLedger(Protocol):
    """Durable record of what has already been published, keyed by run."""

    async def published(self, run_key: str) -> ValidatedAgentResult | None: ...

    async def publish(self, result: ValidatedAgentResult) -> None: ...


class ConcurrencyLease(Protocol):
    """The single Claude lease. `acquire` returns False when someone else holds it."""

    async def acquire(self, run_key: str) -> bool: ...

    async def release(self, run_key: str) -> None: ...


class ClaudeWorker:
    def __init__(
        self,
        runtime: BoundedClaudeRuntime,
        *,
        ledger: RunLedger,
        lease: ConcurrencyLease,
        max_transient_retries: int = MAX_TRANSIENT_RETRIES,
    ) -> None:
        if max_transient_retries < 0:
            raise ValueError("retry bound cannot be negative")
        self._runtime = runtime
        self._ledger = ledger
        self._lease = lease
        self._max_transient_retries = max_transient_retries

    async def handle(self, prepared: PreparedAgentRun) -> WorkerOutcome:
        if prepared.job_type not in CLAUDE_JOB_TYPES:
            return WorkerOutcome("needs_attention", "unknown_job_type")

        # Before the lease, so a duplicate delivery of finished work never waits on
        # whatever is running now.
        already = await self._ledger.published(prepared.run_key)
        if already is not None:
            return WorkerOutcome("replayed", "already_published", already)

        if not await self._lease.acquire(prepared.run_key):
            return WorkerOutcome("deferred", "lease_held")
        try:
            return await self._run(prepared)
        finally:
            await self._lease.release(prepared.run_key)

    async def _run(self, prepared: PreparedAgentRun) -> WorkerOutcome:
        for attempt in range(self._max_transient_retries + 1):
            try:
                result = await self._runtime.run(prepared)
            except AgentServiceUnavailable:
                if attempt == self._max_transient_retries:
                    return WorkerOutcome("needs_attention", "service_unavailable")
                continue
            except tuple(FAILURE_REASONS) as failure:
                # `.get` rather than `[]`: a future subclass would otherwise raise a
                # KeyError from inside the handler that exists to prevent exactly that.
                reason = FAILURE_REASONS.get(type(failure), "processing_failure")
                return WorkerOutcome("needs_attention", reason)
            await self._ledger.publish(result)
            return WorkerOutcome("published", "none", result)
        raise AssertionError("unreachable: the retry loop always returns")


async def gate_step(sessions: async_sessionmaker[AsyncSession]) -> str | None:
    """Beat with the state of the gate: attestation present, credential installed.

    There is no queue of Claude jobs yet, so the worker's only duty is to say,
    truthfully and every beat, whether Claude work could run on this host.
    """
    from ..agents.compatibility import AttestationRepository
    from ..agents.settings import (
        ClaudeSubscriptionSettings,
        ClaudeWorkerConfigurationError,
        PaidCredentialForbidden,
        SubscriptionCredentialMissing,
    )
    from ..auth.models import Owner

    async with sessions() as session:
        owner_id = await session.scalar(select(Owner.id).order_by(Owner.id).limit(1))
        await session.rollback()
    stored = None
    if owner_id is not None:
        # A fresh session: `AttestationRepository.current` opens its own transaction,
        # and a session that already autobegan one on the owner read would refuse it,
        # which reads back as an invalid attestation rather than the real state.
        async with sessions() as session:
            stored = await AttestationRepository(session).current(owner_id=owner_id)
    try:
        ClaudeSubscriptionSettings.for_worker(environ=os.environ, stored=stored)
    except PaidCredentialForbidden:
        return "permission_required"
    except SubscriptionCredentialMissing:
        return "auth"
    except ClaudeWorkerConfigurationError:
        return "permission_required"
    reason = await probe_step(sessions, owner_id=owner_id)
    if reason is not None:
        return reason
    await review_step(sessions)
    await debrief_step(sessions)
    await class_analysis_step(sessions)
    return None


REVIEW_JOBS_PER_STEP = 3


async def review_step(
    sessions: async_sessionmaker[AsyncSession],
    *,
    reviewer: ReviewerService | None = None,
    worker_id: str = "claude-reviewer",
) -> int:
    """Queue reviews for self-reviewed attempts, then score up to a few of them.

    Each job is one bounded reviewer turn. A refused credential or a spent quota parks
    the job with its closed category and the heartbeat says so on the next beat; a
    transport failure retries under the queue's policy; an attempt that cannot be
    reviewed parks as invalid input. The activity's processing status mirrors the job.
    """
    from ..agents.sdk_runtime import AgentSdkRuntime
    from ..evidence.repository import SqlAlchemyEvidenceRepository
    from ..evidence.service import EvidenceService
    from ..jobs.repository import SqlAlchemyJobRepository
    from ..jobs.schemas import ClaimJobCommand, CompleteJobCommand, JobFailure, RetryJobCommand
    from ..jobs.service import JobService
    from ..reviews.service import (
        REVIEW_JOB_KIND,
        ReviewInvalid,
        ReviewService,
        ReviewsUnavailable,
    )
    from .settings import WorkerSettings

    if reviewer is None:
        reviewer = ReviewerService(AgentSdkRuntime(), model=WorkerSettings().reviewer_model)
    async with sessions() as session:
        await ReviewService(session, reviewer=reviewer).enqueue_pending()
    processed = 0
    for _ in range(REVIEW_JOBS_PER_STEP):
        async with sessions() as session:
            jobs = JobService(SqlAlchemyJobRepository(session))
            job = await jobs.claim(
                ClaimJobCommand(worker_id=worker_id, kinds=(REVIEW_JOB_KIND,), lease_seconds=600)
            )
            if job is None:
                return processed
            service = ReviewService(
                session,
                reviewer=reviewer,
                evidence=EvidenceService(SqlAlchemyEvidenceRepository(session)),
            )
            category: str | None = None
            try:
                await service.process(owner_id=job.owner_id, activity_id=job.payload.subject_id)
            except ReviewInvalid:
                category = "invalid_input"
            except ReviewsUnavailable as exc:
                text = str(exc).lower()
                if "quota" in text:
                    category = "resource_exhausted"
                elif "credential" in text or "authentication" in text:
                    category = "permission_required"
                else:
                    category = "transient_dependency"
            except Exception:  # noqa: BLE001 - a job must always end in a closed state
                await session.rollback()
                category = "processing_failure"
            if category is None:
                await jobs.complete(job_id=job.id, command=CompleteJobCommand(worker_id=worker_id))
                processed += 1
                continue
            await session.rollback()
            outcome = await jobs.retry(
                job_id=job.id,
                command=RetryJobCommand(
                    worker_id=worker_id, failure=JobFailure(category=cast(Any, category))
                ),
            )
            if outcome.job.state == "failed":
                await service.mark_failed(
                    owner_id=job.owner_id, activity_id=job.payload.subject_id, category=category
                )
    return processed


DEBRIEF_JOBS_PER_STEP = 1


async def debrief_step(
    sessions: async_sessionmaker[AsyncSession],
    *,
    debriefer: DebriefService | None = None,
    worker_id: str = "claude-debrief",
) -> int:
    """Run one requested interview debrief; every failure ends in a closed job state."""
    from ..agents.sdk_runtime import AgentSdkRuntime
    from ..interviews.debriefs import DEBRIEF_JOB_KIND, InterviewDebriefService
    from ..interviews.service import InterviewInvalid, InterviewsUnavailable
    from ..jobs.repository import SqlAlchemyJobRepository
    from ..jobs.schemas import ClaimJobCommand, CompleteJobCommand, JobFailure, RetryJobCommand
    from ..jobs.service import JobService
    from .settings import WorkerSettings

    if debriefer is None:
        debriefer = DebriefService(AgentSdkRuntime(), model=WorkerSettings().debrief_model)
    processed = 0
    for _ in range(DEBRIEF_JOBS_PER_STEP):
        async with sessions() as session:
            jobs = JobService(SqlAlchemyJobRepository(session))
            job = await jobs.claim(
                ClaimJobCommand(worker_id=worker_id, kinds=(DEBRIEF_JOB_KIND,), lease_seconds=900)
            )
            if job is None:
                return processed
            service = InterviewDebriefService(session, debriefer=debriefer)
            category: str | None = None
            try:
                await service.process(owner_id=job.owner_id, interview_id=job.payload.subject_id)
            except InterviewInvalid:
                category = "invalid_input"
            except InterviewsUnavailable as exc:
                text = str(exc).lower()
                if "quota" in text:
                    category = "resource_exhausted"
                elif "credential" in text or "authentication" in text:
                    category = "permission_required"
                else:
                    category = "transient_dependency"
            except Exception:  # noqa: BLE001 - a job must always end in a closed state
                await session.rollback()
                category = "processing_failure"
            if category is None:
                await jobs.complete(job_id=job.id, command=CompleteJobCommand(worker_id=worker_id))
                processed += 1
                continue
            await session.rollback()
            await jobs.retry(
                job_id=job.id,
                command=RetryJobCommand(
                    worker_id=worker_id, failure=JobFailure(category=cast(Any, category))
                ),
            )
    return processed


CLASS_ANALYSIS_JOBS_PER_STEP = 1


async def class_analysis_step(
    sessions: async_sessionmaker[AsyncSession],
    *,
    analyst: ClassAnalysisService | None = None,
    worker_id: str = "claude-class-analysis",
) -> int:
    """Run one requested English class analysis; every failure ends in a closed state."""
    from ..agents.sdk_runtime import AgentSdkRuntime
    from ..classes.analysis import CLASS_ANALYSIS_JOB_KIND, EnglishClassAnalysisService
    from ..classes.service import ClassesUnavailable, ClassInvalid
    from ..jobs.repository import SqlAlchemyJobRepository
    from ..jobs.schemas import ClaimJobCommand, CompleteJobCommand, JobFailure, RetryJobCommand
    from ..jobs.service import JobService
    from .settings import WorkerSettings

    if analyst is None:
        analyst = ClassAnalysisService(AgentSdkRuntime(), model=WorkerSettings().reviewer_model)
    processed = 0
    for _ in range(CLASS_ANALYSIS_JOBS_PER_STEP):
        async with sessions() as session:
            jobs = JobService(SqlAlchemyJobRepository(session))
            job = await jobs.claim(
                ClaimJobCommand(
                    worker_id=worker_id, kinds=(CLASS_ANALYSIS_JOB_KIND,), lease_seconds=900
                )
            )
            if job is None:
                return processed
            service = EnglishClassAnalysisService(session, analyst=analyst)
            category: str | None = None
            try:
                await service.process(owner_id=job.owner_id, class_id=job.payload.subject_id)
            except ClassInvalid:
                category = "invalid_input"
            except ClassesUnavailable as exc:
                text = str(exc).lower()
                if "quota" in text:
                    category = "resource_exhausted"
                elif "credential" in text or "authentication" in text:
                    category = "permission_required"
                else:
                    category = "transient_dependency"
            except Exception:  # noqa: BLE001 - a job must always end in a closed state
                await session.rollback()
                category = "processing_failure"
            if category is None:
                await jobs.complete(job_id=job.id, command=CompleteJobCommand(worker_id=worker_id))
                processed += 1
                continue
            await session.rollback()
            await jobs.retry(
                job_id=job.id,
                command=RetryJobCommand(
                    worker_id=worker_id, failure=JobFailure(category=cast(Any, category))
                ),
            )
    return processed


async def probe_step(
    sessions: async_sessionmaker[AsyncSession], *, owner_id: int | None
) -> str | None:
    """Ask the installed runtime whether Claude work may run; report by closed reason."""
    from datetime import UTC, datetime

    from ..agents.compatibility import AttestationRepository, probe_claude_compatibility
    from ..agents.sdk_runtime import AgentSdkRuntime
    from .settings import WorkerSettings

    if owner_id is None:
        return "permission_required"
    settings = WorkerSettings()
    async with sessions() as session:
        result = await probe_claude_compatibility(
            runtime=AgentSdkRuntime(),
            repository=AttestationRepository(session),
            owner_id=owner_id,
            enabled=settings.claude_enabled,
            requested_model=settings.planner_model,
            now=datetime.now(UTC),
        )
        await session.rollback()
    if result.claude_may_run:
        return None
    return PROBE_HEARTBEAT_REASONS.get(result.reason, "service")


PROBE_HEARTBEAT_REASONS: Mapping[str, str] = {
    "not_enabled": "permission_required",
    "attestation_missing": "permission_required",
    "attestation_superseded": "permission_required",
    "authentication_missing": "auth",
    "authentication_not_subscription": "auth",
    "authentication_rejected": "auth",
    "quota_exhausted": "quota",
    "policy_rejected": "permission_required",
}


def main() -> int:
    from .runtime import run_main

    return run_main("claude", gate_step, interval_seconds=30.0)


if __name__ == "__main__":  # pragma: no cover - process entrypoint
    raise SystemExit(main())


__all__ = [
    "CLAUDE_JOB_TYPES",
    "FAILURE_REASONS",
    "MAX_TRANSIENT_RETRIES",
    "ClaudeWorker",
    "ConcurrencyLease",
    "Outcome",
    "RunLedger",
    "WorkerOutcome",
]

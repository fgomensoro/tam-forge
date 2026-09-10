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

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

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

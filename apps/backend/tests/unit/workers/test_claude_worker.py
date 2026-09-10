"""One lease, one published result, and nothing published when Claude fails."""

from __future__ import annotations

import asyncio

import pytest
from tamforge_backend.agents.runtime import (
    AgentAuthenticationFailed,
    AgentOutputInvalid,
    AgentQuotaExhausted,
    AgentServiceUnavailable,
    AgentTimeout,
    AgentTurnsExceeded,
    PreparedAgentRun,
    ValidatedAgentResult,
)
from tamforge_backend.workers.claude import (
    CLAUDE_JOB_TYPES,
    MAX_TRANSIENT_RETRIES,
    ClaudeWorker,
)

PAYLOAD = {"verdict": "clear"}


def prepared(**overrides):
    data = {
        "run_key": "run-1",
        "job_type": "claude.review",
        "model": "claude-sonnet-5-20260101",
        "schema_id": "urn:tamforge:schema:english-analysis-v1",
        "prompt_version": "v1",
        "max_turns": 4,
        "wall_time_seconds": 30,
    }
    data.update(overrides)
    return PreparedAgentRun(**data)


def result(run_key="run-1"):
    return ValidatedAgentResult(
        run_key=run_key,
        model="claude-sonnet-5-20260101",
        schema_id="urn:tamforge:schema:english-analysis-v1",
        payload=PAYLOAD,
        turns=2,
        repaired=False,
    )


class FakeRuntime:
    def __init__(self, outcomes=None):
        self.outcomes = list(outcomes or [result()])
        self.calls = 0

    async def run(self, prepared):
        self.calls += 1
        outcome = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeLedger:
    def __init__(self, stored=None):
        self.stored = dict(stored or {})

    async def published(self, run_key):
        return self.stored.get(run_key)

    async def publish(self, value):
        self.stored[value.run_key] = value


class FakeLease:
    def __init__(self, *, available=True):
        self.available = available
        self.held = None
        self.releases = 0

    async def acquire(self, run_key):
        if not self.available or self.held is not None:
            return False
        self.held = run_key
        return True

    async def release(self, run_key):
        self.held = None
        self.releases += 1


def handle(runtime=None, ledger=None, lease=None, **overrides):
    worker = ClaudeWorker(
        runtime or FakeRuntime(), ledger=ledger or FakeLedger(), lease=lease or FakeLease()
    )
    return asyncio.run(worker.handle(prepared(**overrides)))


def test_a_successful_run_publishes_once_and_releases_the_lease() -> None:
    ledger, lease = FakeLedger(), FakeLease()
    outcome = handle(ledger=ledger, lease=lease)

    assert (outcome.outcome, outcome.reason) == ("published", "none")
    assert ledger.stored["run-1"].payload == PAYLOAD
    assert lease.held is None and lease.releases == 1


def test_a_job_that_already_published_is_never_invoked_again() -> None:
    runtime, lease = FakeRuntime(), FakeLease()
    outcome = handle(runtime, FakeLedger({"run-1": result()}), lease)

    assert (outcome.outcome, outcome.reason) == ("replayed", "already_published")
    assert outcome.result is not None and outcome.result.payload == PAYLOAD
    assert runtime.calls == 0
    # The lease is never taken, so a duplicate delivery cannot block live work.
    assert lease.releases == 0


def test_a_held_lease_defers_rather_than_running_a_second_job() -> None:
    runtime = FakeRuntime()
    outcome = handle(runtime, lease=FakeLease(available=False))

    assert (outcome.outcome, outcome.reason) == ("deferred", "lease_held")
    assert runtime.calls == 0


@pytest.mark.parametrize(
    "failure,reason",
    [
        (AgentQuotaExhausted("q"), "quota_exhausted"),
        (AgentAuthenticationFailed("a"), "authentication_rejected"),
        (AgentOutputInvalid("o"), "output_invalid"),
        (AgentTimeout("t"), "timeout"),
        (AgentTurnsExceeded("n"), "turns_exceeded"),
    ],
)
def test_a_failure_needs_attention_and_publishes_nothing(failure, reason) -> None:
    ledger, lease, runtime = FakeLedger(), FakeLease(), FakeRuntime([failure])
    outcome = handle(runtime, ledger, lease)

    assert (outcome.outcome, outcome.reason) == ("needs_attention", reason)
    assert ledger.stored == {}
    assert lease.held is None and lease.releases == 1


def test_quota_and_authentication_are_not_retried() -> None:
    for failure in (AgentQuotaExhausted("q"), AgentAuthenticationFailed("a")):
        runtime = FakeRuntime([failure])
        handle(runtime)
        assert runtime.calls == 1


def test_a_transient_failure_is_retried_within_its_bound() -> None:
    runtime = FakeRuntime([AgentServiceUnavailable("t"), result()])
    outcome = handle(runtime)

    assert outcome.outcome == "published"
    assert runtime.calls == 2


def test_transient_retries_stop_at_the_bound() -> None:
    runtime = FakeRuntime([AgentServiceUnavailable("t")])
    outcome = handle(runtime)

    assert (outcome.outcome, outcome.reason) == ("needs_attention", "service_unavailable")
    assert runtime.calls == MAX_TRANSIENT_RETRIES + 1


def test_a_rerun_after_a_failure_starts_clean_and_then_publishes_once() -> None:
    ledger, lease = FakeLedger(), FakeLease()
    worker_runtime = FakeRuntime([AgentTimeout("t")])
    assert handle(worker_runtime, ledger, lease).outcome == "needs_attention"
    assert ledger.stored == {}

    assert handle(FakeRuntime(), ledger, lease).outcome == "published"
    # And a third delivery of the same run does not publish a second time.
    assert handle(FakeRuntime(), ledger, lease).outcome == "replayed"
    assert list(ledger.stored) == ["run-1"]


def test_only_the_four_registered_job_types_reach_claude() -> None:
    assert CLAUDE_JOB_TYPES == (
        "claude.review",
        "claude.analyze",
        "claude.plan",
        "claude.followup",
    )
    runtime = FakeRuntime()
    outcome = handle(runtime, job_type="speech.transcribe")

    assert (outcome.outcome, outcome.reason) == ("needs_attention", "unknown_job_type")
    assert runtime.calls == 0


def test_a_negative_retry_bound_is_refused() -> None:
    with pytest.raises(ValueError):
        ClaudeWorker(
            FakeRuntime(), ledger=FakeLedger(), lease=FakeLease(), max_transient_retries=-1
        )

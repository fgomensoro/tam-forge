"""The bounds, the validation, and the single repair, driven through a fake transport."""

from __future__ import annotations

import asyncio

import pytest
from tamforge_backend.agents.runtime import (
    MAX_REPAIR_ATTEMPTS,
    AgentOutputInvalid,
    AgentRuntimeError,
    AgentServiceUnavailable,
    AgentTimeout,
    AgentTurnsExceeded,
    BoundedClaudeRuntime,
    PreparedAgentRun,
    TransportResult,
)

GOOD = {"verdict": "clear", "schema_version": "english-analysis-v1"}


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


class FakeTransport:
    def __init__(self, results=None, error=None, delay=0.0):
        self.results = list(results or [TransportResult(GOOD, 2)])
        self.error = error
        self.delay = delay
        self.calls = []

    async def invoke(self, run, *, repair_errors=()):
        self.calls.append({"run_key": run.run_key, "repair_errors": repair_errors})
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return self.results.pop(0) if len(self.results) > 1 else self.results[0]


def valid(payload):
    return () if payload == GOOD else ("payload does not match the schema",)


def run(transport, *, validate=valid, **overrides):
    runtime = BoundedClaudeRuntime(transport, validate=validate)
    return asyncio.run(runtime.run(prepared(**overrides)))


def test_a_valid_payload_comes_back_with_its_pinned_identity() -> None:
    transport = FakeTransport()
    result = run(transport)

    assert result.payload == GOOD
    assert result.run_key == "run-1"
    assert result.schema_id == "urn:tamforge:schema:english-analysis-v1"
    assert result.model == "claude-sonnet-5-20260101"
    assert result.turns == 2
    assert result.repaired is False
    assert transport.calls == [{"run_key": "run-1", "repair_errors": ()}]


def test_invalid_output_buys_exactly_one_repair_carrying_the_errors() -> None:
    assert MAX_REPAIR_ATTEMPTS == 1
    transport = FakeTransport([TransportResult({"wrong": True}, 2), TransportResult(GOOD, 3)])
    result = run(transport)

    assert result.repaired is True
    assert len(transport.calls) == 2
    assert transport.calls[0]["repair_errors"] == ()
    assert transport.calls[1]["repair_errors"] == ("payload does not match the schema",)


def test_a_second_invalid_payload_is_not_repaired_again() -> None:
    transport = FakeTransport([TransportResult({"wrong": True}, 1)])

    with pytest.raises(AgentOutputInvalid):
        run(transport)
    assert len(transport.calls) == MAX_REPAIR_ATTEMPTS + 1


def test_a_run_that_overruns_its_wall_time_is_a_timeout() -> None:
    with pytest.raises(AgentTimeout):
        run(FakeTransport(delay=0.5), wall_time_seconds=0.05, validate=valid)


def test_more_turns_than_allowed_is_refused_before_the_payload_is_read() -> None:
    calls = []

    def never(payload):
        calls.append(payload)
        return ()

    with pytest.raises(AgentTurnsExceeded):
        run(FakeTransport([TransportResult(GOOD, 9)]), validate=never, max_turns=4)
    assert calls == []


def test_an_unknown_transport_failure_never_carries_its_message() -> None:
    secret = "prompt text and a token that must not travel"

    with pytest.raises(AgentServiceUnavailable) as raised:
        run(FakeTransport(error=RuntimeError(secret)))

    assert secret not in str(raised.value)
    assert raised.value.__cause__ is None


def test_a_runtime_error_from_the_transport_is_left_alone() -> None:
    from tamforge_backend.agents.runtime import AgentQuotaExhausted

    with pytest.raises(AgentQuotaExhausted):
        run(FakeTransport(error=AgentQuotaExhausted("quota")))


@pytest.mark.parametrize(
    "overrides", [{"run_key": "  "}, {"max_turns": 0}, {"wall_time_seconds": 0}]
)
def test_a_run_without_bounds_or_an_idempotency_key_is_refused(overrides) -> None:
    with pytest.raises(AgentRuntimeError):
        prepared(**overrides)

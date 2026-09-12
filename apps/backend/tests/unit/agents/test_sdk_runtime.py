from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date
from typing import Any

import pytest
from claude_agent_sdk import (
    CLINotFoundError,
    ProcessError,
    ResultMessage,
    SystemMessage,
)
from tamforge_backend.agents.compatibility import (
    EXPECTED_STRUCTURED_RESPONSE,
    ProbeAuthenticationFailed,
    ProbeError,
    ProbeQuotaExhausted,
)
from tamforge_backend.agents.runtime import AgentAuthenticationFailed, AgentServiceUnavailable
from tamforge_backend.agents.sdk_runtime import PROBE_PROMPT, AgentSdkRuntime
from tamforge_backend.roadmaps.planner import EvidenceLine, PlannerRequest

TOKEN_ENV = {"CLAUDE_CODE_OAUTH_TOKEN": "redacted-fixture-token"}


def _result(**overrides: Any) -> ResultMessage:
    data: dict[str, Any] = {
        "subtype": "success",
        "duration_ms": 10,
        "duration_api_ms": 8,
        "is_error": False,
        "num_turns": 1,
        "session_id": "s",
        "total_cost_usd": 0.0,
        "usage": {},
        "result": "",
        "structured_output": dict(EXPECTED_STRUCTURED_RESPONSE),
    }
    data.update(overrides)
    return ResultMessage(**data)


class FakeQuery:
    def __init__(self, messages: list[Any] | None = None, error: Exception | None = None) -> None:
        self.messages = messages or []
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def __call__(self, *, prompt: str, options: Any) -> AsyncIterator[Any]:
        self.calls.append({"prompt": prompt, "options": options})
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[Any]:
        if self.error is not None:
            raise self.error
        for message in self.messages:
            yield message


def _runtime(query: FakeQuery, environ: dict[str, str] | None = None) -> AgentSdkRuntime:
    return AgentSdkRuntime(
        environ=TOKEN_ENV if environ is None else environ,
        query=query,
        cli_version=lambda: "2.1.0",
        sdk_version=lambda: "0.2.152",
    )


@pytest.mark.anyio
async def test_probe_reads_the_resolved_model_and_the_structured_echo() -> None:
    query = FakeQuery(
        [SystemMessage(subtype="init", data={"model": "claude-fable-5-1"}), _result()]
    )
    observation = await _runtime(query).probe(requested_model="claude-fable-5-1")

    assert observation.authentication_method == "subscription"
    assert observation.resolved_model == "claude-fable-5-1"
    assert observation.supported_models == ("claude-fable-5-1",)
    assert observation.structured_response == EXPECTED_STRUCTURED_RESPONSE
    assert observation.sdk_version == "0.2.152" and observation.cli_version == "2.1.0"
    options = query.calls[0]["options"]
    assert query.calls[0]["prompt"] == PROBE_PROMPT
    assert options.model == "claude-fable-5-1" and options.max_turns == 1
    assert options.allowed_tools == [] and options.setting_sources == []
    assert options.output_format["type"] == "json_schema"
    assert options.env["CLAUDE_CODE_OAUTH_TOKEN"] == "redacted-fixture-token"
    assert options.env["DISABLE_TELEMETRY"] == "1"


@pytest.mark.anyio
async def test_probe_without_a_credential_never_calls_the_runtime() -> None:
    query = FakeQuery([_result()])
    observation = await _runtime(query, environ={}).probe(requested_model="m")
    assert observation.authentication_method == "none"
    assert observation.resolved_model is None
    assert query.calls == []

    paid = await _runtime(query, environ={"ANTHROPIC_API_KEY": "x"}).probe(requested_model="m")
    assert paid.authentication_method == "api_key"


@pytest.mark.anyio
async def test_probe_maps_runtime_failures_to_closed_probe_errors() -> None:
    with pytest.raises(ProbeAuthenticationFailed):
        await _runtime(FakeQuery([_result(api_error_status=401, is_error=True)])).probe(
            requested_model="m"
        )
    with pytest.raises(ProbeQuotaExhausted):
        await _runtime(FakeQuery([_result(api_error_status=429, is_error=True)])).probe(
            requested_model="m"
        )
    with pytest.raises(ProbeError):
        await _runtime(FakeQuery(error=CLINotFoundError())).probe(requested_model="m")
    with pytest.raises(ProbeAuthenticationFailed):
        await _runtime(
            FakeQuery(error=ProcessError("failed", exit_code=1, stderr="Not logged in"))
        ).probe(requested_model="m")
    with pytest.raises(ProbeError):
        await _runtime(FakeQuery([])).probe(requested_model="m")


@pytest.mark.anyio
async def test_propose_sends_the_package_and_repair_errors_and_returns_the_scheme() -> None:
    scheme = {"schema_version": 1, "program": {"key": "demo", "title": "Demo"}, "days": []}
    query = FakeQuery(
        [SystemMessage(subtype="init", data={"model": "m"}), _result(structured_output=scheme)]
    )
    request = PlannerRequest(
        mode="reforecast",
        files={"Week 1.md": "# Week 1\n\n## Day 1\n"},
        instruction="two hours a day",
        today=date(2026, 9, 12),
        current_scheme={"days": {}},
        evidence_summary=(EvidenceLine("d01", "done"),),
        repair_errors=("day 'd01' block minutes 10 do not equal budget 20",),
    )

    payload = await _runtime(
        query, environ={**TOKEN_ENV, "TAMFORGE_PLANNER_MODEL": "claude-opus-5"}
    ).propose(request)

    assert payload == scheme
    prompt = query.calls[0]["prompt"]
    assert "Mode: reforecast." in prompt and "Today: 2026-09-12." in prompt
    assert "two hours a day" in prompt and "### Week 1.md" in prompt
    assert "- d01: done" in prompt and "do not equal budget 20" in prompt
    assert query.calls[0]["options"].model == "claude-opus-5"


@pytest.mark.anyio
async def test_propose_translates_a_refused_run_into_agent_errors() -> None:
    with pytest.raises(AgentAuthenticationFailed):
        await _runtime(FakeQuery([_result(api_error_status=403, is_error=True)])).propose(
            PlannerRequest(mode="generate", files={}, instruction="", today=date(2026, 9, 12))
        )
    with pytest.raises(AgentServiceUnavailable):
        await _runtime(FakeQuery([_result(is_error=True, structured_output=None)])).propose(
            PlannerRequest(mode="generate", files={}, instruction="", today=date(2026, 9, 12))
        )

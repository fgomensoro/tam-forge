from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from pathlib import Path

import pytest
import yaml
from tamforge_backend.agents.runtime import AgentServiceUnavailable
from tamforge_backend.evidence.config_loader import load_config_bundle
from tamforge_backend.roadmaps.planner import (
    EvidenceLine,
    PlannerRequest,
    PlannerService,
    PlannerUnavailable,
)

from .test_scheme import FILES, SCHEME

ROOT = Path(__file__).parents[5]
CONFIG = load_config_bundle(ROOT / "config")
VALID: dict[str, object] = yaml.safe_load(SCHEME)


class FakeTransport:
    def __init__(self, payloads: list[Mapping[str, object]]) -> None:
        self.payloads = list(payloads)
        self.requests: list[PlannerRequest] = []

    async def propose(self, request: PlannerRequest) -> Mapping[str, object]:
        self.requests.append(request)
        return self.payloads.pop(0)


class BrokenTransport:
    async def propose(self, request: PlannerRequest) -> Mapping[str, object]:
        del request
        raise AgentServiceUnavailable("down")


@pytest.mark.anyio
async def test_generate_returns_a_validated_proposal() -> None:
    transport = FakeTransport([VALID])
    service = PlannerService(transport, config=CONFIG, model="claude-fable-5-1")

    proposal = await service.generate(files=FILES, instruction="two hours a day")

    assert proposal.accepted
    assert proposal.summary == {
        "program": "Demo",
        "study_days": 2,
        "budget_minutes": {"1": 120, "2": 60},
    }
    assert "budget_minutes: 120" in proposal.yaml_text
    request = transport.requests[0]
    assert request.mode == "generate"
    assert request.instruction == "two hours a day"
    assert set(request.files) == {"Week 1.md", "docs/Queue.md"}


@pytest.mark.anyio
async def test_one_repair_is_offered_then_the_proposal_is_refused_with_issues() -> None:
    broken = dict(VALID)
    broken["days"] = [dict(VALID["days"][0], budget_minutes=200)]  # type: ignore[index]
    transport = FakeTransport([broken, broken])
    service = PlannerService(transport, config=CONFIG, model="m")

    proposal = await service.generate(files=FILES, instruction="")

    assert not proposal.accepted
    assert any("do not equal budget 200" in issue for issue in proposal.issues)
    assert "budget_minutes: 200" in proposal.yaml_text
    assert len(transport.requests) == 2
    assert transport.requests[1].repair_errors
    assert transport.requests[0].repair_errors == ()


@pytest.mark.anyio
async def test_a_payload_that_is_not_a_scheme_is_refused_by_name() -> None:
    transport = FakeTransport([{"schema_version": 7}, {"schema_version": 7}])
    service = PlannerService(transport, config=CONFIG, model="m")

    proposal = await service.generate(files=FILES, instruction="")

    assert not proposal.accepted
    assert "schema_version" in proposal.issues[0]


@pytest.mark.anyio
async def test_planner_is_unavailable_without_claude_or_when_the_runtime_fails() -> None:
    disabled = PlannerService(None, config=CONFIG, model="m")
    with pytest.raises(PlannerUnavailable):
        await disabled.generate(files=FILES, instruction="")

    broken = PlannerService(BrokenTransport(), config=CONFIG, model="m")
    with pytest.raises(PlannerUnavailable):
        await broken.generate(files=FILES, instruction="")


@pytest.mark.anyio
async def test_reforecast_passes_the_current_scheme_evidence_and_today() -> None:
    transport = FakeTransport([VALID])
    service = PlannerService(transport, config=CONFIG, model="m")
    current = {"rest_weekdays": [6], "program": {"key": "demo", "title": "Demo"}, "days": {}}

    proposal = await service.reforecast(
        files=FILES,
        current_scheme=current,
        evidence=(EvidenceLine("d01-interview", "done"), EvidenceLine("d02-sql", "pending")),
        today=date(2026, 9, 12),
        instruction="from tomorrow two hours",
    )

    assert proposal.accepted
    request = transport.requests[0]
    assert request.mode == "reforecast"
    assert request.today == date(2026, 9, 12)
    assert request.current_scheme == current
    assert [line.status for line in request.evidence_summary] == ["done", "pending"]

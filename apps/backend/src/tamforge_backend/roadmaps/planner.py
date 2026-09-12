"""The planner role: propose a scheme, or reforecast one, and never apply it.

Everything the planner returns goes through `validate_scheme` before anyone sees
it. The transport is a seam: production fills it with the Claude Agent SDK bound
to the subscription (epic F2), tests fill it with a fake, and while Claude is
disabled the service refuses instead of pretending.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Literal, Protocol

import yaml

from ..agents.roles.contracts import (
    EVIDENCE_SUMMARY,
    ROADMAP_STATE,
    TASK_BRIEF,
    prepare_role_prompt,
)
from ..agents.runtime import (
    AgentOutputInvalid,
    AgentRuntimeError,
    BoundedClaudeRuntime,
    PreparedAgentRun,
    TransportResult,
)
from ..agents.tools.registry import AgentRole
from ..evidence.config_models import ConfigBundle
from .ports import RoadmapWorkflowError
from .scheme import (
    SchemeValidationError,
    scheme_from_payload,
    scheme_summary_from_payload,
    validate_scheme,
)

PLANNER_SCHEMA_ID = "urn:tamforge:schema:planner-v1"
PLANNER_MAX_TURNS = 8
PLANNER_WALL_TIME_SECONDS = 300.0
PlannerMode = Literal["generate", "reforecast"]


class PlannerUnavailable(RoadmapWorkflowError):
    """Claude is disabled or not wired, so no proposal can be made."""


@dataclass(frozen=True, slots=True)
class EvidenceLine:
    block_id: str
    status: Literal["done", "pending"]


@dataclass(frozen=True, slots=True)
class PlannerRequest:
    """What the planner reads. Markdown only; audio and evidence bodies never travel."""

    mode: PlannerMode
    files: Mapping[str, str]
    instruction: str
    today: date
    current_scheme: Mapping[str, object] | None = None
    evidence_summary: tuple[EvidenceLine, ...] = ()
    repair_errors: tuple[str, ...] = ()


class PlannerTransport(Protocol):
    async def propose(self, request: PlannerRequest) -> Mapping[str, object]: ...


@dataclass(frozen=True, slots=True)
class SchemeProposal:
    """A scheme the learner still has to approve. Non-empty issues mean refused."""

    yaml_text: str
    summary: dict[str, object]
    issues: tuple[str, ...]

    @property
    def accepted(self) -> bool:
        return not self.issues


@dataclass
class _RuntimeAdapter:
    """Bridges the bounded runtime's transport seam to the planner transport."""

    transport: PlannerTransport
    request: PlannerRequest
    last_payload: Mapping[str, object] | None = field(default=None)

    async def invoke(
        self, run: PreparedAgentRun, *, repair_errors: tuple[str, ...] = ()
    ) -> TransportResult:
        del run
        request = PlannerRequest(
            mode=self.request.mode,
            files=self.request.files,
            instruction=self.request.instruction,
            today=self.request.today,
            current_scheme=self.request.current_scheme,
            evidence_summary=self.request.evidence_summary,
            repair_errors=repair_errors,
        )
        payload = await self.transport.propose(request)
        self.last_payload = payload
        return TransportResult(payload=payload, turns=1)


def render_scheme_yaml(payload: Mapping[str, object]) -> str:
    return yaml.safe_dump(dict(payload), sort_keys=False, allow_unicode=True, width=120)


class PlannerService:
    def __init__(
        self,
        transport: PlannerTransport | None,
        *,
        config: ConfigBundle,
        model: str,
    ) -> None:
        self._transport = transport
        self._config = config
        self._model = model

    async def generate(self, *, files: Mapping[str, bytes], instruction: str) -> SchemeProposal:
        request = PlannerRequest(
            mode="generate",
            files=_markdown_text(files),
            instruction=instruction.strip(),
            today=date.today(),
        )
        return await self._propose(request, files)

    async def reforecast(
        self,
        *,
        files: Mapping[str, bytes],
        current_scheme: Mapping[str, object],
        evidence: Sequence[EvidenceLine],
        today: date,
        instruction: str,
    ) -> SchemeProposal:
        request = PlannerRequest(
            mode="reforecast",
            files=_markdown_text(files),
            instruction=instruction.strip(),
            today=today,
            current_scheme=current_scheme,
            evidence_summary=tuple(evidence),
        )
        return await self._propose(request, files)

    async def _propose(self, request: PlannerRequest, files: Mapping[str, bytes]) -> SchemeProposal:
        if self._transport is None:
            raise PlannerUnavailable("the planner needs Claude enabled on the server")
        prepare_role_prompt(
            AgentRole.PLANNER,
            committed=True,
            requested_context=(TASK_BRIEF, ROADMAP_STATE, EVIDENCE_SUMMARY),
        )
        adapter = _RuntimeAdapter(self._transport, request)
        runtime = BoundedClaudeRuntime(adapter, validate=self._issues_for(files))
        digest = hashlib.sha256(
            f"{request.mode}:{request.today.isoformat()}:{request.instruction}".encode()
        ).hexdigest()[:24]
        prepared = PreparedAgentRun(
            run_key=f"planner:{request.mode}:{digest}",
            job_type="planner",
            model=self._model,
            schema_id=PLANNER_SCHEMA_ID,
            prompt_version="v1",
            max_turns=PLANNER_MAX_TURNS,
            wall_time_seconds=PLANNER_WALL_TIME_SECONDS,
        )
        try:
            result = await runtime.run(prepared)
        except AgentOutputInvalid:
            payload = adapter.last_payload or {}
            issues = self._issues_for(files)(payload) or ("the planner did not return a scheme",)
            return SchemeProposal(
                yaml_text=render_scheme_yaml(payload) if payload else "",
                summary={},
                issues=issues,
            )
        except AgentRuntimeError as exc:
            raise PlannerUnavailable(str(exc)) from None
        scheme = scheme_from_payload(result.payload)
        payload_scheme = _scheme_payload(scheme)
        return SchemeProposal(
            yaml_text=render_scheme_yaml(result.payload),
            summary=scheme_summary_from_payload(payload_scheme),
            issues=(),
        )

    def _issues_for(self, files: Mapping[str, bytes]):  # type: ignore[no-untyped-def]
        def validate(payload: Mapping[str, object]) -> tuple[str, ...]:
            try:
                scheme = scheme_from_payload(payload)
            except SchemeValidationError as exc:
                return (str(exc),)
            return validate_scheme(scheme, files=files, config=self._config)

        return validate


def _markdown_text(files: Mapping[str, bytes]) -> dict[str, str]:
    return {
        path: data.decode("utf-8", errors="replace")
        for path, data in files.items()
        if path.lower().endswith(".md")
    }


def _scheme_payload(scheme) -> dict[str, object]:  # type: ignore[no-untyped-def]
    return {
        "rest_weekdays": [int(index) for index in sorted(scheme.rest_weekday_indexes)],
        "program": {"key": scheme.program.key, "title": scheme.program.title},
        "days": {
            str(number): {"id": day.id, "kind": day.kind, "budget_minutes": day.budget_minutes}
            for number, day in enumerate(scheme.days, start=1)
        },
    }


__all__ = [
    "PLANNER_MAX_TURNS",
    "PLANNER_SCHEMA_ID",
    "PLANNER_WALL_TIME_SECONDS",
    "EvidenceLine",
    "PlannerMode",
    "PlannerRequest",
    "PlannerService",
    "PlannerTransport",
    "PlannerUnavailable",
    "SchemeProposal",
    "render_scheme_yaml",
]

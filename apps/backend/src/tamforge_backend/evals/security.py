"""The security suite: every attack in the fixture must fail closed, and nothing may leak.

Four doors, each already built to refuse, exercised here as one scored set so a regression
in any of them is a number in a report rather than a surprise in production. Authorization:
a role calling a tool outside its allowlist never reaches the handler. Injection: text
shaped like an instruction, whether it arrives as a tool argument or as a memory claim
lifted from a transcript, is an invalid argument or a rejected proposal, never a command.
Secrets: a token, a cookie, a signed URL or a transcript phrase offered to the log line is
dropped by construction. Isolation: a context packet for one role never includes another
role's, another owner's, another company's, or a real interview's material.

Disclosure is measured, not assumed: every canary string planted in an attack is searched
for in everything the door produced (the exception message, the audit record, the log
line, the packet manifest). One hit is one disclosure, and the threshold is zero.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field
from tamforge_protocol.memory import MemoryLedger, Role, Sensitivity

from ..agents.tools import AgentRole, ToolContext, ToolError, ToolRegistry, ToolSpec
from ..memory.context import ContextRequest, ContextSource, build_context
from ..memory.policy import MemoryProposal, decide
from ..observability.logging import safe_event

SECURITY_EVALUATOR_VERSION: Final = "security-eval-v1"

Door = Literal["authorization", "injection", "secrets", "isolation"]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SecurityCase(_StrictModel):
    case_id: Annotated[str, Field(pattern=r"^[a-z0-9-]{1,64}$")]
    door: Door
    role: Role
    # The string that must never appear in anything the door produces.
    canary: Annotated[str, Field(min_length=8, max_length=512)]
    # authorization / injection: the tool and arguments to call.
    tool: str | None = None
    arguments: dict[str, object] = Field(default_factory=dict)
    # injection via memory: a claim lifted from a transcript.
    claim: str | None = None
    # secrets: the field the attacker controls in a log call.
    log_field: str | None = None
    # isolation: the source that must be excluded for this role.
    source_tier: str | None = None
    source_sensitivity: Sensitivity = "routine"
    source_owner_id: Annotated[int, Field(strict=True, gt=0)] = 1
    source_company_id: int | None = None


class SecurityCaseSet(_StrictModel):
    fixture_version: Literal["security-cases-v1"]
    cases: tuple[SecurityCase, ...]
    fixture_sha256: str = ""


def load_security_cases(path: Path) -> SecurityCaseSet:
    raw = path.read_bytes()
    body = json.loads(raw)
    body["fixture_sha256"] = sha256(raw).hexdigest()
    return SecurityCaseSet.model_validate(body)


@dataclass(frozen=True, slots=True)
class SecurityOutcome:
    case_id: str
    door: Door
    failed_closed: bool
    disclosures: int
    produced: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SecurityReport:
    evaluator_version: str
    fixture_sha256: str
    outcomes: tuple[SecurityOutcome, ...]

    @property
    def open_doors(self) -> tuple[str, ...]:
        return tuple(o.case_id for o in self.outcomes if not o.failed_closed)

    @property
    def disclosures(self) -> int:
        return sum(o.disclosures for o in self.outcomes)

    @property
    def passed(self) -> bool:
        return not self.open_doors and self.disclosures == 0

    def render(self) -> str:
        body = {
            "evaluator_version": self.evaluator_version,
            "fixture_sha256": self.fixture_sha256,
            "cases": len(self.outcomes),
            "open_doors": list(self.open_doors),
            "disclosures": self.disclosures,
            "passed": self.passed,
            "by_door": {
                door: sum(1 for o in self.outcomes if o.door == door and o.failed_closed)
                for door in ("authorization", "injection", "secrets", "isolation")
            },
        }
        return json.dumps(body, indent=2, sort_keys=True) + "\n"


class _Sink:
    def __init__(self) -> None:
        self.records: list[object] = []

    async def record(self, audit: object) -> None:
        self.records.append(audit)


class _Search(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    skill: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
    limit: Annotated[int, Field(strict=True, ge=1, le=500)] = 10
    context_ordinals: tuple[Annotated[int, Field(strict=True, ge=0, le=63)], ...] = ()


def _registry(sink: _Sink) -> ToolRegistry:
    async def search(payload: object, context: ToolContext) -> object:
        return {"rows": []}

    built = ToolRegistry(audit=sink)
    built.register(
        ToolSpec(
            name="search_evidence",
            version="v1",
            roles=frozenset({AgentRole.REVIEWER, AgentRole.ANALYST}),
            schema=_Search,
            handler=search,
        )
    )
    return built


async def _tool_door(case: SecurityCase) -> tuple[bool, tuple[str, ...]]:
    sink = _Sink()
    registry = _registry(sink)
    context = ToolContext(owner_id=1, activity_id=1, allowed_context_ordinals=frozenset({0, 1}))
    produced: list[str] = []
    try:
        result = await registry.call(
            AgentRole(case.role), case.tool or "", case.arguments, context=context
        )
    except ToolError as refusal:
        produced.append(str(refusal))
        produced.extend(repr(r) for r in sink.records)
        return True, tuple(produced)
    produced.append(repr(result))
    produced.extend(repr(r) for r in sink.records)
    return False, tuple(produced)


def _memory_door(case: SecurityCase) -> tuple[bool, tuple[str, ...]]:
    outcome = decide(
        MemoryProposal(
            kind="semantic",
            claim=case.claim or "",
            origin="agent_inference",
            author="tutor",
            model_run_id=1,
            evidence_kinds=("conversation",),
            event_count=5,
            sensitivity="routine",
        )
    )
    return outcome.decision == "REJECT", (repr(outcome),)


def _secrets_door(case: SecurityCase) -> tuple[bool, tuple[str, ...]]:
    fields: dict[str, object] = {case.log_field or "error_code": case.canary}
    line = safe_event("request_failed", **fields)
    return case.canary not in line, (line,)


def _isolation_door(case: SecurityCase, *, at: datetime) -> tuple[bool, tuple[str, ...]]:
    source = ContextSource(
        source_id="planted",
        tier=case.source_tier or "verified_role_memory",  # type: ignore[arg-type]
        owner_id=case.source_owner_id,
        text=case.canary,
        sensitivity=case.source_sensitivity,
        company_id=case.source_company_id,
        revision_id=None,
    )
    packet = build_context(
        (source,),
        ContextRequest(
            owner_id=1, role=case.role, ceiling="routine", at=at, token_budget=1_000, company_id=1
        ),
        ledger=MemoryLedger(),
    )
    excluded = not any(i.source_id == "planted" for i in packet.included)
    return excluded, (repr(packet.manifest),)


async def run_security_cases(cases: SecurityCaseSet, *, at: datetime) -> SecurityReport:
    outcomes: list[SecurityOutcome] = []
    for case in cases.cases:
        if case.door in ("authorization", "injection") and case.tool is not None:
            closed, produced = await _tool_door(case)
        elif case.door == "injection":
            closed, produced = _memory_door(case)
        elif case.door == "secrets":
            closed, produced = _secrets_door(case)
        else:
            closed, produced = _isolation_door(case, at=at)
        disclosures = sum(1 for text in produced if case.canary in text)
        outcomes.append(
            SecurityOutcome(
                case_id=case.case_id,
                door=case.door,
                failed_closed=closed,
                disclosures=disclosures,
                produced=produced,
            )
        )
    return SecurityReport(
        evaluator_version=SECURITY_EVALUATOR_VERSION,
        fixture_sha256=cases.fixture_sha256,
        outcomes=tuple(outcomes),
    )


__all__ = [
    "SECURITY_EVALUATOR_VERSION",
    "SecurityCase",
    "SecurityCaseSet",
    "SecurityOutcome",
    "SecurityReport",
    "load_security_cases",
    "run_security_cases",
]

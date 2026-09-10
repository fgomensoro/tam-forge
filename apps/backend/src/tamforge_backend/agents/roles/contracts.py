"""What each role is, what it may be shown, and when it may speak at all.

Five roles, five prompt contracts, and no sharing. A prompt key, a version and an output
schema belong to exactly one role, because two roles behind one prompt is one role with
two names, and the audit trail then cannot say which of them produced an answer.

Context is granted per role and checked against what a call asks for. A role sees the
kinds of context its contract lists and nothing else, whatever the caller passes.

The last rule is the one the workspace exists for. Only the Planner runs before the
learner has committed anything, because planning the day is not answering the question.
Every other role is refused until there is a committed attempt to work from: a tutor
that answers first has replaced the exercise, and a reviewer with nothing to review is
inventing one.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from ..tools.registry import AgentRole

# The kinds of context a prompt may be handed. Anything not named here has no way in.
ContextKind = str

TASK_BRIEF = "task_brief"
ROADMAP_STATE = "roadmap_state"
SOURCE_MATERIAL = "source_material"
COMMITTED_ATTEMPT = "committed_attempt"
SELF_REVIEW = "self_review"
RUBRIC = "rubric"
EVIDENCE_SUMMARY = "evidence_summary"
SPEECH_METRICS = "speech_metrics"

# Only the Planner works before anything is committed: planning a day is not answering
# a question. Every other role needs a committed attempt in front of it.
ROLES_BEFORE_COMMITMENT: frozenset[AgentRole] = frozenset({AgentRole.PLANNER})


class RoleContractError(ValueError):
    """A role was asked for something its contract does not allow."""


@dataclass(frozen=True, slots=True)
class RolePromptContract:
    role: AgentRole
    prompt_key: str
    prompt_version: str
    output_schema_id: str
    allowed_context: frozenset[ContextKind]

    @property
    def requires_commitment(self) -> bool:
        return self.role not in ROLES_BEFORE_COMMITMENT


def _contract(
    role: AgentRole, key: str, schema: str, context: Iterable[ContextKind]
) -> RolePromptContract:
    return RolePromptContract(
        role=role,
        prompt_key=key,
        prompt_version="v1",
        output_schema_id=schema,
        allowed_context=frozenset(context),
    )


ROLE_CONTRACTS: Mapping[AgentRole, RolePromptContract] = MappingProxyType(
    {
        AgentRole.PLANNER: _contract(
            AgentRole.PLANNER,
            "tamforge.planner",
            "urn:tamforge:schema:planner-v1",
            (TASK_BRIEF, ROADMAP_STATE, EVIDENCE_SUMMARY),
        ),
        AgentRole.TUTOR: _contract(
            AgentRole.TUTOR,
            "tamforge.tutor",
            "urn:tamforge:schema:tutor-v1",
            (TASK_BRIEF, SOURCE_MATERIAL, COMMITTED_ATTEMPT),
        ),
        AgentRole.COACH: _contract(
            AgentRole.COACH,
            "tamforge.coach",
            "urn:tamforge:schema:coach-v1",
            (TASK_BRIEF, COMMITTED_ATTEMPT, SELF_REVIEW),
        ),
        AgentRole.REVIEWER: _contract(
            AgentRole.REVIEWER,
            "tamforge.reviewer",
            "urn:tamforge:schema:reviewer-v1",
            (TASK_BRIEF, COMMITTED_ATTEMPT, SELF_REVIEW, RUBRIC, SPEECH_METRICS),
        ),
        AgentRole.ANALYST: _contract(
            AgentRole.ANALYST,
            "tamforge.analyst",
            "urn:tamforge:schema:analyst-v1",
            (EVIDENCE_SUMMARY, RUBRIC),
        ),
    }
)


def contract_for(role: AgentRole) -> RolePromptContract:
    contract = ROLE_CONTRACTS.get(role)
    if contract is None:
        raise RoleContractError("no prompt contract is defined for this role")
    return contract


def prepare_role_prompt(
    role: AgentRole, *, committed: bool, requested_context: Iterable[ContextKind]
) -> RolePromptContract:
    """Return the contract to run under, or refuse the run outright."""
    contract = contract_for(role)
    if contract.requires_commitment and not committed:
        raise RoleContractError("this role may not speak before the learner commits")
    requested = frozenset(requested_context)
    if not requested <= contract.allowed_context:
        raise RoleContractError("this role was offered context its contract does not allow")
    return contract


__all__ = [
    "COMMITTED_ATTEMPT",
    "EVIDENCE_SUMMARY",
    "ROLES_BEFORE_COMMITMENT",
    "ROLE_CONTRACTS",
    "ROADMAP_STATE",
    "RUBRIC",
    "SELF_REVIEW",
    "SOURCE_MATERIAL",
    "SPEECH_METRICS",
    "TASK_BRIEF",
    "ContextKind",
    "RoleContractError",
    "RolePromptContract",
    "contract_for",
    "prepare_role_prompt",
]

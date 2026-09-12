"""The Planner is the only role that speaks before anything is committed."""

from __future__ import annotations

import pytest
from tamforge_backend.agents.roles.contracts import (
    EVIDENCE_SUMMARY,
    ROADMAP_STATE,
    ROLE_CONTRACTS,
    SOURCE_MATERIAL,
    TASK_BRIEF,
    RoleContractError,
    contract_for,
    prepare_role_prompt,
)
from tamforge_backend.agents.tools.registry import AgentRole


def test_the_planner_runs_before_the_learner_has_committed_anything() -> None:
    contract = prepare_role_prompt(
        AgentRole.PLANNER, committed=False, requested_context=(TASK_BRIEF, ROADMAP_STATE)
    )

    assert contract.role is AgentRole.PLANNER
    assert contract.requires_commitment is False


def test_the_planner_never_sees_the_source_material() -> None:
    # Planning a day is not reading the reading. Handing it the source is how a plan
    # turns into a summary of what the learner was supposed to work through.
    assert SOURCE_MATERIAL not in contract_for(AgentRole.PLANNER).allowed_context

    with pytest.raises(RoleContractError, match="context"):
        prepare_role_prompt(AgentRole.PLANNER, committed=True, requested_context=(SOURCE_MATERIAL,))


def test_the_planner_reads_the_roadmap_and_the_evidence_summary() -> None:
    allowed = contract_for(AgentRole.PLANNER).allowed_context

    assert {TASK_BRIEF, ROADMAP_STATE, EVIDENCE_SUMMARY} == set(allowed)


def test_a_role_with_no_contract_cannot_be_prepared() -> None:
    with pytest.raises(RoleContractError, match="no prompt contract"):
        prepare_role_prompt(AgentRole.INTERVIEWER, committed=True, requested_context=())
    assert AgentRole.INTERVIEWER not in ROLE_CONTRACTS

"""The Coach, and the matrix all five roles have to satisfy together."""

from __future__ import annotations

import pytest
from tamforge_backend.agents.roles.contracts import (
    COMMITTED_ATTEMPT,
    ROLE_CONTRACTS,
    ROLES_BEFORE_COMMITMENT,
    SCREEN_CONTEXT,
    SELF_REVIEW,
    SOURCE_MATERIAL,
    TASK_BRIEF,
    WORKING_DRAFT,
    RoleContractError,
    contract_for,
    prepare_role_prompt,
)
from tamforge_backend.agents.tools.registry import AgentRole


def test_the_coach_may_prepare_before_the_attempt_but_sees_only_its_context() -> None:
    contract = prepare_role_prompt(
        AgentRole.COACH, committed=False, requested_context=(TASK_BRIEF, WORKING_DRAFT)
    )
    assert contract.role is AgentRole.COACH

    allowed = contract_for(AgentRole.COACH).allowed_context
    assert {TASK_BRIEF, COMMITTED_ATTEMPT, SELF_REVIEW, WORKING_DRAFT, SCREEN_CONTEXT} == set(
        allowed
    )
    assert SOURCE_MATERIAL not in allowed
    assert (WORKING_DRAFT, SCREEN_CONTEXT) == ("working_draft", "screen_context")


def test_the_five_roles_have_five_distinct_prompt_contracts() -> None:
    contracts = list(ROLE_CONTRACTS.values())

    assert {contract.role for contract in contracts} == {
        AgentRole.PLANNER,
        AgentRole.TUTOR,
        AgentRole.COACH,
        AgentRole.REVIEWER,
        AgentRole.ANALYST,
    }
    for field in ("prompt_key", "output_schema_id"):
        values = [getattr(contract, field) for contract in contracts]
        # Two roles behind one prompt is one role with two names, and the audit trail
        # then cannot say which of them produced an answer.
        assert len(set(values)) == len(values)


@pytest.mark.parametrize("role", [AgentRole.TUTOR, AgentRole.REVIEWER, AgentRole.ANALYST])
def test_only_the_planner_and_the_coach_speak_before_commitment(role: AgentRole) -> None:
    assert ROLES_BEFORE_COMMITMENT == frozenset({AgentRole.PLANNER, AgentRole.COACH})
    with pytest.raises(RoleContractError, match="commits"):
        prepare_role_prompt(role, committed=False, requested_context=())


def test_every_role_is_granted_only_what_its_own_contract_lists() -> None:
    every_kind = set().union(*(c.allowed_context for c in ROLE_CONTRACTS.values()))

    for role, contract in ROLE_CONTRACTS.items():
        outside = every_kind - contract.allowed_context
        assert (
            prepare_role_prompt(role, committed=True, requested_context=contract.allowed_context)
            is contract
        )
        for kind in outside:
            with pytest.raises(RoleContractError, match="context"):
                prepare_role_prompt(role, committed=True, requested_context=(kind,))

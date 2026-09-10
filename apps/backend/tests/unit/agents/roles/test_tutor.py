"""The Tutor teaches after the learner has written something, never before."""

from __future__ import annotations

import pytest
from tamforge_backend.agents.roles.contracts import (
    COMMITTED_ATTEMPT,
    RUBRIC,
    SOURCE_MATERIAL,
    TASK_BRIEF,
    RoleContractError,
    contract_for,
    prepare_role_prompt,
)
from tamforge_backend.agents.tools.registry import AgentRole


def test_the_tutor_is_refused_until_there_is_a_committed_attempt() -> None:
    with pytest.raises(RoleContractError, match="commits"):
        prepare_role_prompt(
            AgentRole.TUTOR, committed=False, requested_context=(SOURCE_MATERIAL,)
        )

    contract = prepare_role_prompt(
        AgentRole.TUTOR, committed=True, requested_context=(SOURCE_MATERIAL, COMMITTED_ATTEMPT)
    )
    assert contract.requires_commitment is True


def test_the_tutor_may_read_the_source_it_is_teaching_from() -> None:
    allowed = contract_for(AgentRole.TUTOR).allowed_context

    assert {TASK_BRIEF, SOURCE_MATERIAL, COMMITTED_ATTEMPT} == set(allowed)
    assert RUBRIC not in allowed


def test_context_outside_the_tutors_grant_is_refused_whatever_the_caller_passes() -> None:
    with pytest.raises(RoleContractError, match="context"):
        prepare_role_prompt(
            AgentRole.TUTOR, committed=True, requested_context=(COMMITTED_ATTEMPT, RUBRIC)
        )

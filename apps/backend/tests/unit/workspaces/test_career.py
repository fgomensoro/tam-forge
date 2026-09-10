"""A career block ends in something that was not there before, or it is not done."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from tamforge_backend.agents.model_runs import LEARNER_FIELDS
from tamforge_protocol.workspaces import (
    CAREER_PHASE_ORDER,
    CAREER_PHASE_SECONDS,
    CAREER_SESSION_SECONDS,
    CareerBlockCommitment,
    WorkspaceRuleError,
    career_phase_at,
)


def block(**overrides: object) -> CareerBlockCommitment:
    data: dict[str, object] = {
        "company": "Northwind",
        "role": "Technical Account Manager",
        "stage": "screen",
        "completed_action": "Sent the follow-up summary naming the integration risk.",
        "artifact_summary": "One-page summary of the failure and the two options.",
        "next_action": "Ask for the panel date if nothing arrives by Thursday.",
        "opportunity_id": 4,
        "related_interview_ids": (11,),
        "elapsed_seconds": 1_500,
    }
    data.update(overrides)
    return CareerBlockCommitment.model_validate(data)


def test_the_three_phases_fill_half_an_hour() -> None:
    assert CAREER_PHASE_ORDER == ("select", "produce", "record")
    assert [CAREER_PHASE_SECONDS[phase] for phase in CAREER_PHASE_ORDER] == [300, 1_200, 300]
    assert CAREER_SESSION_SECONDS == 1_800


@pytest.mark.parametrize(
    "elapsed,expected",
    [
        (0, "select"),
        (299, "select"),
        (300, "produce"),
        (1_499, "produce"),
        (1_500, "record"),
        (1_799, "record"),
        (1_800, None),
    ],
)
def test_career_phase_boundaries(elapsed: int, expected: str | None) -> None:
    assert career_phase_at(elapsed) == expected


def test_a_negative_clock_is_refused() -> None:
    with pytest.raises(WorkspaceRuleError):
        career_phase_at(-1)


def test_a_block_records_the_company_the_role_and_where_it_stands() -> None:
    recorded = block()

    assert (recorded.company, recorded.role, recorded.stage) == (
        "Northwind",
        "Technical Account Manager",
        "screen",
    )


def test_the_stage_vocabulary_is_the_opportunitys_own() -> None:
    # One vocabulary, so a block and the opportunity it belongs to cannot disagree
    # about what stage means.
    from typing import get_args

    from tamforge_protocol.opportunities import OpportunityStage

    assert get_args(CareerBlockCommitment.model_fields["stage"].annotation) == get_args(
        OpportunityStage
    )


@pytest.mark.parametrize(
    "field", ["completed_action", "artifact_summary", "next_action"]
)
def test_a_block_without_its_artifact_or_its_next_step_is_not_complete(field: str) -> None:
    # A block that produced nothing is a block that reviewed the list again.
    with pytest.raises(ValidationError):
        block(**{field: "   "})


def test_the_recorded_fields_are_the_ones_the_reviewer_reads() -> None:
    assert LEARNER_FIELDS["pipeline"] == {
        "completed_action",
        "artifact_summary",
        "next_action",
    }
    assert LEARNER_FIELDS["pipeline"] <= set(CareerBlockCommitment.model_fields)


def test_general_pipeline_work_needs_no_opportunity() -> None:
    general = block(opportunity_id=None, related_interview_ids=())

    assert general.opportunity_id is None
    assert general.completed_action


def test_a_related_interview_without_its_opportunity_points_at_nothing() -> None:
    with pytest.raises(ValidationError, match="opportunity they belong to"):
        block(opportunity_id=None)


def test_an_interview_is_linked_once() -> None:
    with pytest.raises(ValidationError, match="linked once"):
        block(related_interview_ids=(11, 11))


def test_a_block_cannot_outlast_its_half_hour() -> None:
    assert block(elapsed_seconds=CAREER_SESSION_SECONDS)
    with pytest.raises(ValidationError):
        block(elapsed_seconds=CAREER_SESSION_SECONDS + 1)

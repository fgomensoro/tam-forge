"""A schedule for one opportunity is never built from another one's interviews."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from tamforge_backend.opportunities.service import preparation_interviews
from tamforge_protocol.interviews import Interview
from tamforge_protocol.opportunities import Opportunity, OpportunityError

NOW = datetime(2026, 9, 15, 15, tzinfo=UTC)


def opportunity(**overrides: object) -> Opportunity:
    data: dict[str, object] = {
        "opportunity_id": 4,
        "owner_id": 1,
        "company": "Northwind",
        "role": "Technical Account Manager",
        "job_description": {
            "captured_at": NOW,
            "sha256": "a" * 64,
            "text": "Owns renewal health for named accounts.",
        },
        "stage_history": ({"stage": "screen", "occurred_at": NOW},),
        "interview_ids": (11,),
    }
    data.update(overrides)
    return Opportunity.model_validate(data)


def interview(**overrides: object) -> Interview:
    data: dict[str, object] = {
        "interview_id": 11,
        "owner_id": 1,
        "kind": "real",
        "scheduled_for": NOW,
        "opportunity_id": 4,
        "stage_label": "Screen",
    }
    data.update(overrides)
    return Interview.model_validate(data)


def test_preparation_reads_only_this_opportunitys_interviews() -> None:
    mine = interview()
    elsewhere = interview(interview_id=12, opportunity_id=9)

    assert preparation_interviews(opportunity(), [mine, elsewhere], owner_id=1) == (mine,)


def test_another_owners_interview_raises_rather_than_being_filtered_away() -> None:
    # Quietly dropping it would hide a schedule built from the wrong account.
    with pytest.raises(OpportunityError, match="another owner"):
        preparation_interviews(opportunity(), [interview(owner_id=2)], owner_id=1)


def test_another_owners_opportunity_answers_nothing() -> None:
    with pytest.raises(OpportunityError, match="another owner"):
        preparation_interviews(opportunity(owner_id=2), [interview(owner_id=2)], owner_id=1)


def test_an_interview_claiming_this_opportunity_without_being_linked_is_refused() -> None:
    # The claim is on the interview; the link is on the opportunity. Both have to agree
    # or a schedule can be built from an interview the opportunity never acknowledged.
    unlinked = interview(interview_id=13)

    with pytest.raises(OpportunityError, match="another opportunity"):
        preparation_interviews(opportunity(), [unlinked], owner_id=1)


def test_an_exercise_is_never_preparation_for_a_real_opportunity() -> None:
    practice = interview(interview_id=14, kind="practice", opportunity_id=None, stage_label=None)

    assert preparation_interviews(opportunity(), [practice], owner_id=1) == ()

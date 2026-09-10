"""What an opportunity keeps, and who is allowed to see it."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from tamforge_protocol.opportunities import (
    TERMINAL_STAGES,
    Opportunity,
    OpportunityError,
    owned_by,
    require_linked,
    visible_stage_history,
)

NOW = datetime(2026, 9, 10, 12, tzinfo=UTC)


def snapshot(**overrides: object) -> dict:
    data: dict[str, object] = {
        "captured_at": NOW - timedelta(days=14),
        "sha256": "a" * 64,
        "text": "Technical Account Manager, EMEA. Owns renewal health for named accounts.",
    }
    data.update(overrides)
    return data


def stage(name: str, days: int = 0, **overrides: object) -> dict:
    data: dict[str, object] = {"stage": name, "occurred_at": NOW + timedelta(days=days)}
    data.update(overrides)
    return data


def opportunity(**overrides: object) -> Opportunity:
    data: dict[str, object] = {
        "opportunity_id": 4,
        "owner_id": 1,
        "company": "Northwind",
        "role": "Technical Account Manager",
        "job_description": snapshot(),
        "stage_history": (stage("identified", -20), stage("applied", -14), stage("screen", -2)),
        "next_action": "Send the follow-up summary by Friday.",
        "interview_ids": (11,),
    }
    data.update(overrides)
    return Opportunity.model_validate(data)


def test_an_opportunity_keeps_the_posting_as_it_read_at_the_time() -> None:
    kept = opportunity().job_description

    assert kept.sha256 == "a" * 64
    assert kept.captured_at < NOW
    assert "Technical Account Manager" in kept.text


def test_the_stage_history_is_the_record_not_a_single_current_stage() -> None:
    tracked = opportunity()

    assert [event.stage for event in tracked.stage_history] == [
        "identified",
        "applied",
        "screen",
    ]
    assert tracked.current_stage == "screen"
    assert tracked.closed is False


def test_a_history_out_of_order_is_not_a_history() -> None:
    with pytest.raises(ValidationError, match="chronological"):
        opportunity(stage_history=(stage("applied", 0), stage("identified", -5)))


@pytest.mark.parametrize("closing", sorted(TERMINAL_STAGES))
def test_nothing_follows_a_close(closing: str) -> None:
    assert opportunity(stage_history=(stage("screen", -2), stage(closing, 0)), next_action=None)

    with pytest.raises(ValidationError, match="closed stage"):
        opportunity(
            stage_history=(stage(closing, -1), stage("offer", 0)),
            next_action=None,
        )


def test_a_closed_opportunity_has_nothing_left_to_do() -> None:
    with pytest.raises(ValidationError, match="no next action"):
        opportunity(stage_history=(stage("closed_lost", 0),))

    assert opportunity(stage_history=(stage("closed_lost", 0),), next_action=None).closed


def test_an_interview_is_linked_once() -> None:
    with pytest.raises(ValidationError, match="linked once"):
        opportunity(interview_ids=(11, 11))


def test_retrieval_returns_only_this_owners_opportunities() -> None:
    mine = opportunity()
    theirs = opportunity(opportunity_id=9, owner_id=2)

    assert owned_by([mine, theirs], owner_id=1) == (mine,)
    assert owned_by([mine, theirs], owner_id=2) == (theirs,)
    with pytest.raises(OpportunityError):
        owned_by([mine], owner_id=0)


def test_another_owners_opportunity_never_answers_a_read() -> None:
    theirs = opportunity(owner_id=2)

    with pytest.raises(OpportunityError, match="another owner"):
        visible_stage_history(theirs, owner_id=1)
    with pytest.raises(OpportunityError, match="another owner"):
        require_linked(theirs, interview_id=11, owner_id=1)


def test_an_interview_from_another_opportunity_is_refused() -> None:
    mine = opportunity()

    assert require_linked(mine, interview_id=11, owner_id=1) is None
    with pytest.raises(OpportunityError, match="another opportunity"):
        require_linked(mine, interview_id=12, owner_id=1)


def test_a_naive_timestamp_is_refused_everywhere() -> None:
    naive = datetime(2026, 9, 10, 12)

    with pytest.raises(ValidationError):
        opportunity(job_description=snapshot(captured_at=naive))
    with pytest.raises(ValidationError):
        opportunity(stage_history=({"stage": "applied", "occurred_at": naive},))

"""Which interviews may name an opportunity, and which must not."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from tamforge_protocol.interviews import OPPORTUNITY_LINKED_KINDS, Interview

NOW = datetime(2026, 9, 12, 15, tzinfo=UTC)


def interview(**overrides: object) -> Interview:
    data: dict[str, object] = {
        "interview_id": 11,
        "owner_id": 1,
        "kind": "real",
        "scheduled_for": NOW,
        "opportunity_id": 4,
        "stage_label": "Technical panel",
    }
    data.update(overrides)
    return Interview.model_validate(data)


def test_a_real_interview_names_the_opportunity_it_belongs_to() -> None:
    real = interview()

    assert real.is_real is True
    assert real.opportunity_id == 4
    assert OPPORTUNITY_LINKED_KINDS == frozenset({"real"})


def test_a_real_interview_without_an_opportunity_is_untraceable_and_refused() -> None:
    with pytest.raises(ValidationError, match="only a real interview"):
        interview(opportunity_id=None, stage_label=None)


@pytest.mark.parametrize("kind", ["practice", "mock"])
def test_an_exercise_never_names_a_live_opportunity(kind: str) -> None:
    # An exercise linked to a live opportunity is how practice material ends up read
    # as if it were the real conversation.
    assert interview(kind=kind, opportunity_id=None, stage_label=None).is_real is False

    with pytest.raises(ValidationError, match="only a real interview"):
        interview(kind=kind)


@pytest.mark.parametrize("kind", ["practice", "mock"])
def test_an_exercise_has_no_stage_in_anyones_pipeline(kind: str) -> None:
    with pytest.raises(ValidationError):
        interview(kind=kind, opportunity_id=None, stage_label="Technical panel")


def test_a_naive_schedule_is_refused() -> None:
    with pytest.raises(ValidationError):
        interview(scheduled_for=datetime(2026, 9, 12, 15))


def test_an_unknown_kind_is_refused() -> None:
    with pytest.raises(ValidationError):
        interview(kind="informal_chat")

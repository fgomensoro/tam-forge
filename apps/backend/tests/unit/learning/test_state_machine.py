from __future__ import annotations

from itertools import product

import pytest
from tamforge_backend.learning.enums import ActivityState
from tamforge_backend.learning.state_machine import (
    ActivityStateError,
    assert_attempt_number,
    assert_output_editable,
    transition,
)

ALLOWED = {
    (ActivityState.READY, ActivityState.ACTIVE),
    (ActivityState.ACTIVE, ActivityState.PAUSED),
    (ActivityState.ACTIVE, ActivityState.OUTPUT_COMMITTED),
    (ActivityState.ACTIVE, ActivityState.INCOMPLETE),
    (ActivityState.PAUSED, ActivityState.ACTIVE),
    (ActivityState.PAUSED, ActivityState.INCOMPLETE),
    (ActivityState.OUTPUT_COMMITTED, ActivityState.SELF_REVIEW_COMPLETE),
    (ActivityState.SELF_REVIEW_COMPLETE, ActivityState.AI_PROCESSING),
    (ActivityState.AI_PROCESSING, ActivityState.FEEDBACK_READY),
    (ActivityState.FEEDBACK_READY, ActivityState.CORRECTION_DUE),
    (ActivityState.CORRECTION_DUE, ActivityState.DEMONSTRATED),
    (ActivityState.CORRECTION_DUE, ActivityState.NEEDS_WORK),
}


@pytest.mark.parametrize(("current", "target"), product(ActivityState, repeat=2))
def test_only_the_explicit_activity_transition_table_is_allowed(
    current: ActivityState, target: ActivityState
) -> None:
    if (current, target) in ALLOWED:
        decision = transition(
            current=current,
            target=target,
            actual_version=3,
            expected_version=3,
            day_type="weekday",
            day_status="in_progress",
        )
        assert decision.state is target
        assert decision.next_version == 4
    else:
        with pytest.raises(ActivityStateError, match="transition"):
            transition(
                current=current,
                target=target,
                actual_version=3,
                expected_version=3,
                day_type="weekday",
                day_status="in_progress",
            )


def test_stale_optimistic_version_is_rejected() -> None:
    with pytest.raises(ActivityStateError, match="stale"):
        transition(
            current=ActivityState.READY,
            target=ActivityState.ACTIVE,
            actual_version=4,
            expected_version=3,
            day_type="weekday",
            day_status="planned",
        )


@pytest.mark.parametrize(
    ("day_type", "day_status"),
    [("sunday", "planned"), ("weekday", "closed"), ("weekday", "incomplete")],
)
def test_start_or_resume_is_rejected_on_sunday_or_after_day_close(
    day_type: str, day_status: str
) -> None:
    with pytest.raises(ActivityStateError, match="study day"):
        transition(
            current=ActivityState.READY,
            target=ActivityState.ACTIVE,
            actual_version=1,
            expected_version=1,
            day_type=day_type,
            day_status=day_status,
        )


@pytest.mark.parametrize(
    "state",
    [
        ActivityState.OUTPUT_COMMITTED,
        ActivityState.SELF_REVIEW_COMPLETE,
        ActivityState.AI_PROCESSING,
        ActivityState.FEEDBACK_READY,
        ActivityState.CORRECTION_DUE,
        ActivityState.DEMONSTRATED,
        ActivityState.NEEDS_WORK,
    ],
)
def test_output_edits_are_rejected_after_commit(state: ActivityState) -> None:
    with pytest.raises(ActivityStateError, match="committed"):
        assert_output_editable(state)


def test_attempt_c_is_never_allowed() -> None:
    assert_attempt_number(1)
    assert_attempt_number(2)
    with pytest.raises(ActivityStateError, match="Attempt C"):
        assert_attempt_number(3)

"""Pure, exhaustive activity transition rules with optimistic concurrency."""

from __future__ import annotations

from dataclasses import dataclass

from .enums import ActivityState


class ActivityStateError(ValueError):
    """An activity command violates its state or concurrency contract."""


_TRANSITIONS = frozenset(
    {
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
)


@dataclass(frozen=True, slots=True)
class TransitionDecision:
    state: ActivityState
    next_version: int


def transition(
    *,
    current: ActivityState,
    target: ActivityState,
    actual_version: int,
    expected_version: int,
    day_type: str,
    day_status: str,
) -> TransitionDecision:
    """Validate one transition without mutating state or trusting client clocks."""
    if actual_version <= 0 or expected_version != actual_version:
        raise ActivityStateError("stale activity version")
    if (current, target) not in _TRANSITIONS:
        raise ActivityStateError("invalid activity state transition")
    if target is ActivityState.ACTIVE:
        allowed_statuses = {"planned", "in_progress"}
        if (
            day_type == "sunday"
            or day_status not in allowed_statuses
            or (current is ActivityState.PAUSED and day_status != "in_progress")
        ):
            raise ActivityStateError("study day does not allow starting work")
    return TransitionDecision(state=target, next_version=actual_version + 1)


def assert_output_editable(state: ActivityState) -> None:
    """Output drafts stop being mutable at the commitment boundary."""
    if state not in {ActivityState.READY, ActivityState.ACTIVE, ActivityState.PAUSED}:
        raise ActivityStateError("committed output cannot be edited")


def assert_attempt_number(attempt_number: int) -> None:
    """The evidence contract has Attempt A and Attempt B, never Attempt C."""
    if attempt_number not in {1, 2}:
        raise ActivityStateError("Attempt C is not allowed")

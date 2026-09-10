"""Interview day fits inside the budget, and the last stretch stays protected."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from tamforge_backend.opportunities.service import (
    ALLOWED_IN_PROTECTED_WINDOW,
    MAX_PROTECTION_MINUTES,
    MIN_PROTECTION_MINUTES,
    BudgetExceeded,
    ProtectedWindowViolation,
    SchedulingError,
    admit_activity,
    plan_interview_day,
)

INTERVIEW_AT = datetime(2026, 9, 15, 15, tzinfo=UTC)


def plan(**overrides: object):
    data: dict[str, object] = {
        "budget_minutes": 180,
        "preparation_minutes": 45,
        "interview_minutes": 60,
        "interview_at": INTERVIEW_AT,
    }
    data.update(overrides)
    return plan_interview_day(**data)  # type: ignore[arg-type]


def test_interview_work_is_substituted_into_the_budget_not_added_to_it() -> None:
    day = plan()

    assert day.budget_minutes == 180
    assert day.remaining_practice_minutes == 75
    assert day.preparation_minutes + day.interview_minutes <= day.budget_minutes


def test_a_day_that_would_have_to_grow_is_refused() -> None:
    # A day that grows to fit an interview ends with the learner more tired going in.
    with pytest.raises(BudgetExceeded):
        plan(budget_minutes=90, preparation_minutes=45, interview_minutes=60)

    assert plan(budget_minutes=105, preparation_minutes=45).remaining_practice_minutes == 0


def test_the_protected_stretch_is_between_one_hour_and_ninety_minutes() -> None:
    assert (MIN_PROTECTION_MINUTES, MAX_PROTECTION_MINUTES) == (60, 90)
    assert plan().protection_minutes == MAX_PROTECTION_MINUTES
    assert plan(protection_minutes=60).protected_from == INTERVIEW_AT - timedelta(minutes=60)

    for minutes in (59, 91):
        with pytest.raises(SchedulingError, match="60 and 90"):
            plan(protection_minutes=minutes)


@pytest.mark.parametrize("load", ["new_practice", "exhausting_practice"])
def test_nothing_demanding_runs_in_the_protected_stretch(load: str) -> None:
    day = plan()

    with pytest.raises(ProtectedWindowViolation):
        admit_activity(day, starts_at=day.protected_from, load=load)
    with pytest.raises(ProtectedWindowViolation):
        admit_activity(day, starts_at=INTERVIEW_AT - timedelta(minutes=1), load=load)


def test_light_review_is_the_one_thing_allowed_close_in() -> None:
    day = plan()

    assert ALLOWED_IN_PROTECTED_WINDOW == frozenset({"light_review"})
    assert admit_activity(day, starts_at=day.protected_from, load="light_review") is None


def test_practice_earlier_in_the_day_is_untouched() -> None:
    day = plan()
    earlier = day.protected_from - timedelta(minutes=1)

    assert admit_activity(day, starts_at=earlier, load="new_practice") is None
    assert day.protects(earlier) is False


def test_the_window_ends_when_the_interview_starts() -> None:
    day = plan()

    assert day.protects(INTERVIEW_AT) is False
    assert admit_activity(day, starts_at=INTERVIEW_AT, load="new_practice") is None


def test_a_naive_timestamp_is_refused_on_both_sides() -> None:
    with pytest.raises(SchedulingError, match="timezone-aware"):
        plan(interview_at=datetime(2026, 9, 15, 15))
    with pytest.raises(SchedulingError, match="timezone-aware"):
        admit_activity(plan(), starts_at=datetime(2026, 9, 15, 14), load="light_review")


@pytest.mark.parametrize(
    "changes",
    [{"budget_minutes": 0}, {"interview_minutes": 0}, {"preparation_minutes": -1}],
)
def test_a_day_without_a_budget_or_an_interview_length_is_refused(changes) -> None:
    with pytest.raises(SchedulingError):
        plan(**changes)

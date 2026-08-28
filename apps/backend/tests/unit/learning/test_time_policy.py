from __future__ import annotations

from datetime import date, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st
from tamforge_backend.learning.time_policy import (
    CompletionGate,
    FocusEntry,
    TimePolicyError,
    budget_for,
    can_finish_early,
    counted_focused_minutes,
    hard_stop_recommended,
    validate_planned_minutes,
)


def test_weekday_budget_has_exact_target_range_and_hard_stop() -> None:
    budget = budget_for(date(2026, 8, 24))

    assert budget.day_type == "weekday"
    assert budget.target_minutes == 240
    assert budget.acceptable_minimum == 225
    assert budget.maximum_minutes == 255
    assert not hard_stop_recommended(budget, focused_minutes=254)
    assert hard_stop_recommended(budget, focused_minutes=255)


def test_saturday_has_a_strict_120_minute_maximum() -> None:
    budget = budget_for(date(2026, 8, 29))

    assert budget.day_type == "saturday"
    assert budget.target_minutes == 120
    assert budget.maximum_minutes == 120
    validate_planned_minutes(budget, 120)
    with pytest.raises(TimePolicyError, match="120"):
        validate_planned_minutes(budget, 121)


def test_async_processing_never_counts_as_focused_time() -> None:
    entries = (
        FocusEntry(kind="focused", minutes=45),
        FocusEntry(kind="async_processing", minutes=90),
        FocusEntry(kind="real_interview", minutes=60),
    )

    assert counted_focused_minutes(entries) == 105


@pytest.mark.parametrize(
    ("gates", "expected"),
    [
        ((CompletionGate(True, True), CompletionGate(True, True)), True),
        ((CompletionGate(False, True),), False),
        ((CompletionGate(True, False),), False),
        ((), False),
    ],
)
def test_finishing_early_requires_all_required_outputs_and_passes(
    gates: tuple[CompletionGate, ...], expected: bool
) -> None:
    assert can_finish_early(gates) is expected


SUNDAY_DATES = st.dates(
    min_value=date(2000, 1, 1), max_value=date(2099, 12, 24)
).map(lambda value: value + timedelta(days=(6 - value.weekday()) % 7))


@given(SUNDAY_DATES)
def test_sunday_budget_is_always_zero(local_date: date) -> None:
    budget = budget_for(local_date)

    assert budget.day_type == "sunday"
    assert budget.target_minutes == 0
    assert budget.maximum_minutes == 0
    validate_planned_minutes(budget, 0)
    with pytest.raises(TimePolicyError):
        validate_planned_minutes(budget, 1)

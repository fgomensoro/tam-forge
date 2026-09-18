"""SM-2 is pinned: the same grades always produce the same intervals."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from tamforge_backend.cards.scheduling import (
    SM2_VERSION,
    CardState,
    learner_local_date,
    new_card_state,
    schedule,
)

DAY = date(2026, 9, 16)


def _run(grades: list[int]) -> list[tuple[int, int, str]]:
    state = new_card_state(due_on=DAY)
    reviewed = DAY
    trace = []
    for grade in grades:
        outcome = schedule(state, grade=grade, reviewed_on=reviewed)
        state = outcome.after
        trace.append((state.repetitions, state.interval_days, str(state.easiness)))
        reviewed = state.due_on
    return trace


def test_successive_passes_follow_one_six_then_easiness_growth() -> None:
    assert _run([4, 4, 4, 4]) == [
        (1, 1, "2.50"),
        (2, 6, "2.50"),
        (3, 15, "2.50"),
        (4, 38, "2.50"),
    ]
    assert SM2_VERSION == "sm2-v1"


def test_a_failure_resets_repetitions_and_the_interval_but_keeps_lowering_easiness() -> None:
    assert _run([5, 5, 2]) == [(1, 1, "2.60"), (2, 6, "2.70"), (0, 1, "2.38")]


def test_easiness_never_drops_below_the_floor() -> None:
    trace = _run([0] * 8)
    assert trace[-1] == (0, 1, "1.30")


def test_due_date_is_the_review_date_plus_the_interval_not_the_old_due_date() -> None:
    state = CardState(
        easiness=Decimal("2.5"), interval_days=6, repetitions=2, due_on=date(2026, 9, 10)
    )
    outcome = schedule(state, grade=3, reviewed_on=date(2026, 9, 20))
    assert outcome.after.easiness == Decimal("2.36")
    assert outcome.after.interval_days == 14
    assert outcome.after.due_on == date(2026, 10, 4)
    assert outcome.before is state and outcome.successful


def test_grades_outside_zero_to_five_are_rejected() -> None:
    with pytest.raises(ValueError):
        schedule(new_card_state(due_on=DAY), grade=6, reviewed_on=DAY)


def test_a_new_card_is_due_on_the_learners_local_date_not_the_servers() -> None:
    # 03:00 UTC on the 18th is still the evening of the 17th in Los Angeles.
    now = datetime(2026, 9, 18, 3, 0, tzinfo=UTC)
    assert learner_local_date(now, "America/Los_Angeles") == date(2026, 9, 17)
    assert learner_local_date(now, "Asia/Tokyo") == date(2026, 9, 18)
    # No learner settings yet, or a zone the host does not know: the server's UTC date.
    assert learner_local_date(now, None) == date(2026, 9, 18)
    assert learner_local_date(now, "Not/AZone") == date(2026, 9, 18)

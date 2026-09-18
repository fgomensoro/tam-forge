"""SM-2, pinned: the scheduling algorithm every card review in TAM Forge follows.

`SM2_VERSION` names the exact rules below so a future change ships as a new version
rather than silently rescheduling every card.

Rules (SuperMemo 2, Wozniak 1990, with the usual floor on the easiness factor):

- A grade is an integer 0..5. 3 and above is a successful recall.
- Easiness starts at 2.5 and moves by `-0.8 + 0.28 * grade - 0.02 * grade * grade`,
  never below 1.3.
- On success the repetition count increments; the interval is 1 day for the first
  success, 6 days for the second, and `round(previous_interval * easiness)` after that.
- On failure the repetition count resets to 0 and the interval is 1 day; easiness is
  still updated, so a card that keeps failing gets harder to advance.
- The next due date is the review date plus the interval.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

SM2_VERSION: Final = "sm2-v1"
MINIMUM_EASINESS: Final = Decimal("1.30")
INITIAL_EASINESS: Final = Decimal("2.50")
PASSING_GRADE: Final = 3


@dataclass(frozen=True, slots=True)
class CardState:
    easiness: Decimal
    interval_days: int
    repetitions: int
    due_on: date


@dataclass(frozen=True, slots=True)
class ReviewOutcome:
    before: CardState
    after: CardState
    grade: int
    successful: bool


def learner_local_date(now: datetime, timezone: str | None) -> date:
    """The calendar date the learner is living in. The app asks for due cards by local date,
    so a card stamped with the server's UTC date can land on the learner's tomorrow."""
    if timezone:
        try:
            return now.astimezone(ZoneInfo(timezone)).date()
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return now.astimezone(UTC).date()


def new_card_state(*, due_on: date) -> CardState:
    return CardState(easiness=INITIAL_EASINESS, interval_days=0, repetitions=0, due_on=due_on)


def schedule(state: CardState, *, grade: int, reviewed_on: date) -> ReviewOutcome:
    """Apply one review to a card's state under SM-2."""
    if not 0 <= grade <= 5:
        raise ValueError("grade must be between 0 and 5")
    delta = Decimal("-0.8") + Decimal("0.28") * grade - Decimal("0.02") * grade * grade
    easiness = max(MINIMUM_EASINESS, (state.easiness + delta).quantize(Decimal("0.01")))
    successful = grade >= PASSING_GRADE
    if not successful:
        repetitions = 0
        interval = 1
    else:
        repetitions = state.repetitions + 1
        if repetitions == 1:
            interval = 1
        elif repetitions == 2:
            interval = 6
        else:
            interval = int(
                (Decimal(state.interval_days) * easiness).quantize(Decimal("1"), ROUND_HALF_UP)
            )
            interval = max(interval, state.interval_days + 1)
    after = CardState(
        easiness=easiness,
        interval_days=interval,
        repetitions=repetitions,
        due_on=reviewed_on + timedelta(days=interval),
    )
    return ReviewOutcome(before=state, after=after, grade=grade, successful=successful)


__all__ = [
    "INITIAL_EASINESS",
    "MINIMUM_EASINESS",
    "PASSING_GRADE",
    "SM2_VERSION",
    "CardState",
    "ReviewOutcome",
    "new_card_state",
    "schedule",
]

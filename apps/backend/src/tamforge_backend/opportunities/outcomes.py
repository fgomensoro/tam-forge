"""Conversion and timing from what happened, never from how the room felt.

An interview leaves two kinds of trace. There are the events: they scheduled a panel, they
made an offer, they stopped replying. And there is the impression: they seemed
unconvinced, the hiring manager was warm, it felt like it went badly.

Only the first kind moves anything here. Impressions are worth writing down and worth
reading, but a system that turns them into a pass-or-fail prediction is a system that
tells an anxious person their instinct was right, on no evidence, at the worst possible
time. There is no field for demeanour, no sentiment input, and no prediction output, and
tests assert each absence.

What it does compute is arithmetic over recorded events: how long each stage took, and how
many opportunities that reached a stage went on to the next one. Both are facts about
dates, and both are wrong only if the dates are.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import timedelta

from tamforge_protocol.opportunities import TERMINAL_STAGES, Opportunity, OpportunityStage

# Only these move conversion or timing. Anything else about an interview is context for
# a person to read, not an input to a number.
OUTCOME_EVENTS: frozenset[str] = frozenset(
    {"identified", "applied", "screen", "technical", "panel", "offer", "closed_won", "closed_lost"}
)


class OutcomeError(ValueError):
    """A conversion or timing question that cannot be answered from recorded events."""


@dataclass(frozen=True, slots=True)
class StageDuration:
    stage: OpportunityStage
    entered_at_index: int
    days: int


def stage_durations(opportunity: Opportunity) -> tuple[StageDuration, ...]:
    """How long each stage lasted, from the recorded history and nothing else.

    The last stage has no successor to end it, so it is not reported. An open-ended
    duration read as a number is how "we are still waiting" turns into "this took two
    days".
    """
    history = opportunity.stage_history
    durations = []
    for index, (earlier, later) in enumerate(zip(history, history[1:], strict=False)):
        span: timedelta = later.occurred_at - earlier.occurred_at
        durations.append(
            StageDuration(stage=earlier.stage, entered_at_index=index, days=span.days)
        )
    return tuple(durations)


def reached(opportunities: Iterable[Opportunity], *, stage: OpportunityStage) -> int:
    """How many of these opportunities ever recorded that stage."""
    if stage not in OUTCOME_EVENTS:
        raise OutcomeError("that is not a recorded outcome event")
    return sum(
        1
        for opportunity in opportunities
        if any(event.stage == stage for event in opportunity.stage_history)
    )


def conversion(
    opportunities: Sequence[Opportunity],
    *,
    from_stage: OpportunityStage,
    to_stage: OpportunityStage,
) -> tuple[int, int]:
    """Return (advanced, reached) rather than a ratio.

    A ratio over three opportunities is a number that looks like a rate, and a rate over
    three is noise wearing a percentage sign. The caller can divide when the denominator
    is worth dividing by.
    """
    denominator = reached(opportunities, stage=from_stage)
    numerator = reached(
        [
            opportunity
            for opportunity in opportunities
            if any(event.stage == from_stage for event in opportunity.stage_history)
        ],
        stage=to_stage,
    )
    return numerator, denominator


def still_open(opportunities: Iterable[Opportunity]) -> tuple[Opportunity, ...]:
    return tuple(
        opportunity
        for opportunity in opportunities
        if opportunity.current_stage not in TERMINAL_STAGES
    )


__all__ = [
    "OUTCOME_EVENTS",
    "OutcomeError",
    "StageDuration",
    "conversion",
    "reached",
    "stage_durations",
    "still_open",
]

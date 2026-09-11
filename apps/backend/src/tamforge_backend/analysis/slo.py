"""Whether feedback arrived in time, measured on the clock that can be defended.

Two budgets: fifteen minutes for routine practice, an hour for assessments and real
interviews. What makes them meaningful is what is excluded from them and what can never
satisfy them.

The clock starts at eligibility, not at upload. Practice and mock work becomes eligible
when the recording is sealed and the learner's self-review is in, whichever is later,
because feedback cannot honestly start before the learner has committed their own read.
A real interview is eligible at seal, since its debrief is a separate gate.

Two suspensions stop the clock and two do not. Waiting for a debrief or for a redaction
approval is waiting on a person, and holding the system to a deadline it cannot influence
teaches nobody anything, so that time is excluded. A Claude quota or service outage is
different: it stops the clock too, but a run that hit one can never be recorded as on
time however fast it finished afterwards. Otherwise a system that was unavailable for an
hour reports a perfect record.

Missing evidence is a miss, not an absence. A run with no feedback, or one whose speech
stage did not meet its own gate, fails rather than being left uncounted.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

RunKind = Literal["practice", "mock", "real"]

ROUTINE_SLO = timedelta(minutes=15)
ASSESSMENT_SLO = timedelta(minutes=60)

SuspensionReason = Literal[
    "awaiting_debrief",
    "awaiting_redaction",
    "claude_quota",
    "claude_service_unavailable",
]

# Waiting on a person. Excluded from the active clock.
WAITING_ON_A_PERSON: frozenset[str] = frozenset({"awaiting_debrief", "awaiting_redaction"})

# Waiting on Claude. Also excluded from the active clock, and also fatal to an on-time
# claim, because a system that was unavailable for an hour must not report a clean run.
WAITING_ON_CLAUDE: frozenset[str] = frozenset({"claude_quota", "claude_service_unavailable"})


class SloError(ValueError):
    """A processing run that cannot be accounted for as described."""


@dataclass(frozen=True, slots=True)
class Suspension:
    reason: SuspensionReason
    started_at: datetime
    ended_at: datetime | None = None

    def __post_init__(self) -> None:
        for moment in (self.started_at, self.ended_at):
            if moment is not None and (moment.tzinfo is None or moment.utcoffset() is None):
                raise SloError("suspension timestamps must be timezone-aware")
        if self.ended_at is not None and self.ended_at < self.started_at:
            raise SloError("a suspension cannot end before it starts")

    def elapsed(self, *, until: datetime) -> timedelta:
        return (self.ended_at or until) - self.started_at


@dataclass(frozen=True, slots=True)
class ProcessingRun:
    kind: RunKind
    ingest_sealed_at: datetime
    self_review_complete_at: datetime | None = None
    speech_stage_met: bool = True
    feedback_ready_at: datetime | None = None
    suspensions: tuple[Suspension, ...] = ()

    def __post_init__(self) -> None:
        if self.ingest_sealed_at.tzinfo is None or self.ingest_sealed_at.utcoffset() is None:
            raise SloError("run timestamps must be timezone-aware")
        if self.kind != "real" and self.self_review_complete_at is None:
            raise SloError("practice and mock work becomes eligible only after a self-review")

    @property
    def budget(self) -> timedelta:
        return ROUTINE_SLO if self.kind == "practice" else ASSESSMENT_SLO

    @property
    def eligible_at(self) -> datetime:
        if self.kind == "real" or self.self_review_complete_at is None:
            return self.ingest_sealed_at
        return max(self.ingest_sealed_at, self.self_review_complete_at)

    @property
    def suspended(self) -> timedelta:
        if self.feedback_ready_at is None:
            return timedelta()
        return sum(
            (item.elapsed(until=self.feedback_ready_at) for item in self.suspensions),
            timedelta(),
        )

    @property
    def active_elapsed(self) -> timedelta | None:
        """Wall time from eligibility to feedback, minus every suspension."""
        if self.feedback_ready_at is None:
            return None
        if self.feedback_ready_at < self.eligible_at:
            raise SloError("feedback cannot be ready before the run is eligible")
        return self.feedback_ready_at - self.eligible_at - self.suspended

    @property
    def blocked_by_claude(self) -> bool:
        return any(item.reason in WAITING_ON_CLAUDE for item in self.suspensions)

    @property
    def on_time(self) -> bool:
        active = self.active_elapsed
        if active is None or not self.speech_stage_met or self.blocked_by_claude:
            return False
        return active <= self.budget

    @property
    def miss_reason(self) -> str:
        if self.feedback_ready_at is None:
            return "no_feedback"
        if not self.speech_stage_met:
            return "speech_stage_missed"
        if self.blocked_by_claude:
            return "claude_unavailable"
        active = self.active_elapsed
        if active is not None and active > self.budget:
            return "over_budget"
        return "none"


def summarize(runs: Sequence[ProcessingRun]) -> dict[str, int]:
    """How many runs met their budget, and why the others did not."""
    counts: dict[str, int] = {"on_time": 0}
    for run in runs:
        if run.on_time:
            counts["on_time"] += 1
            continue
        counts[run.miss_reason] = counts.get(run.miss_reason, 0) + 1
    return counts


__all__ = [
    "ASSESSMENT_SLO",
    "ROUTINE_SLO",
    "WAITING_ON_A_PERSON",
    "WAITING_ON_CLAUDE",
    "ProcessingRun",
    "RunKind",
    "SloError",
    "Suspension",
    "SuspensionReason",
    "summarize",
]

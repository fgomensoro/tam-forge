"""The debrief the learner writes before anything else gets to speak.

Right after a real interview the learner knows things nobody else will ever recover:
which question landed badly, what they wished they had said, where they felt the room
turn. Five minutes later that is already fading, and once AI feedback has been read it is
gone for good, because from then on the memory is of the feedback.

So the debrief comes first and the release waits for it. It is capped at five minutes
because this is a memory dump, not an essay, and it has to be written soon after the
interview or it stops being a debrief and becomes recollection.

It is also permanently distinguishable from everything else in the record. Its attribution
is `user_stated` and cannot be anything else, so no later reader can mistake what the
learner remembers for what the transcript shows or for what a model concluded. Those three
are different kinds of claim and the difference does not survive being flattened.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

# A memory dump, not an essay.
DEBRIEF_MAX_MINUTES = 5

# After this the learner is recalling an interview rather than debriefing one. The
# window is generous on purpose: the point is to exclude next-day reconstruction, not to
# punish someone who needed a walk first.
DEBRIEF_WINDOW_MINUTES = 30

# The one attribution a debrief may carry. It matches the analysis contract's vocabulary
# so the two cannot drift, and it is single-valued so a debrief can never be filed as
# transcript evidence or as inference.
DebriefAttribution = Literal["user_stated"]


class DebriefError(ValueError):
    """Feedback asked to be released before the learner had their say."""


@dataclass(frozen=True, slots=True)
class Debrief:
    interview_id: int
    owner_id: int
    interview_ended_at: datetime
    committed_at: datetime
    minutes: int
    notes: str
    attribution: DebriefAttribution = "user_stated"

    def __post_init__(self) -> None:
        for moment in (self.interview_ended_at, self.committed_at):
            if moment.tzinfo is None or moment.utcoffset() is None:
                raise DebriefError("debrief timestamps must be timezone-aware")
        if self.interview_id <= 0 or self.owner_id <= 0:
            raise DebriefError("a debrief names its interview and its owner")
        if not 1 <= self.minutes <= DEBRIEF_MAX_MINUTES:
            raise DebriefError(f"a debrief runs from 1 to {DEBRIEF_MAX_MINUTES} minutes")
        if not self.notes.strip():
            raise DebriefError("an empty debrief is not a debrief")
        if self.committed_at < self.interview_ended_at:
            raise DebriefError("a debrief is written after the interview, not before")
        if self.committed_at - self.interview_ended_at > timedelta(
            minutes=DEBRIEF_WINDOW_MINUTES
        ):
            raise DebriefError("too late to be a debrief; this is recollection")

    @property
    def is_transcript_evidence(self) -> bool:
        """Never. Kept as a property so the answer is written down somewhere."""
        return False


def require_debrief_before_release(
    debrief: Debrief | None, *, interview_id: int, owner_id: int
) -> Debrief:
    """Return the debrief that unlocks feedback, or refuse to release anything."""
    if debrief is None:
        raise DebriefError("feedback is released after the debrief, not before")
    if debrief.interview_id != interview_id or debrief.owner_id != owner_id:
        raise DebriefError("that debrief belongs to another interview or owner")
    return debrief


__all__ = [
    "DEBRIEF_MAX_MINUTES",
    "DEBRIEF_WINDOW_MINUTES",
    "Debrief",
    "DebriefAttribution",
    "DebriefError",
    "require_debrief_before_release",
]

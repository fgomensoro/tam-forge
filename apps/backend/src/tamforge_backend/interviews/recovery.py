"""What happens after a real interview went badly, bounded so it stays useful.

Two corrections, one coached replay, one saved response. Every number here is a cap
rather than a target, because the failure mode after a bad interview is not doing too
little about it, it is doing all of it at once and learning none of it.

The replay is coached and the response is not. That order matters: talking through the
fix with help and then producing one unaided is the whole shape of the exercise, and a
second coached pass would replace the unaided one rather than prepare for it.

What the recovery does not resolve goes to retrieval in a different scenario later,
using the same transfer rule the correction contract already enforces. Repeating the
interview question measures recall of one answer, and after a real interview that is the
most tempting wrong thing to do.
"""

from __future__ import annotations

from dataclasses import dataclass

from tamforge_protocol.agents import (
    REQUIRED_CORRECTIONS,
    QueuedRetrieval,
    TransferAttempt,
    require_material_difference,
)

# One of each. A second coached pass would replace the unaided response rather than
# prepare for it.
MAX_COACHED_REPLAYS = 1
MAX_SAVED_RESPONSES = 1


class RecoveryError(ValueError):
    """A recovery plan that would do more than it can honestly measure."""


@dataclass(frozen=True, slots=True)
class RecoveryStep:
    target_skill: str
    instruction: str
    coached: bool

    def __post_init__(self) -> None:
        if not self.target_skill.strip() or not self.instruction.strip():
            raise RecoveryError("a step names its skill and what to do")


@dataclass(frozen=True, slots=True)
class RecoveryPlan:
    """The bounded thing a learner does after an interview that did not go well."""

    interview_id: int
    owner_id: int
    steps: tuple[RecoveryStep, ...]

    def __post_init__(self) -> None:
        if self.interview_id <= 0 or self.owner_id <= 0:
            raise RecoveryError("a recovery plan names its interview and its owner")
        if len(self.steps) != REQUIRED_CORRECTIONS:
            raise RecoveryError("recovery works on exactly two corrections")
        skills = [step.target_skill for step in self.steps]
        if len(set(skills)) != len(skills):
            raise RecoveryError("two steps on one skill is one step")
        coached = sum(1 for step in self.steps if step.coached)
        if coached != MAX_COACHED_REPLAYS:
            raise RecoveryError("recovery allows exactly one coached replay")
        if len(self.steps) - coached != MAX_SAVED_RESPONSES:
            raise RecoveryError("recovery allows exactly one saved response")

    @property
    def coached_replay(self) -> RecoveryStep:
        return next(step for step in self.steps if step.coached)

    @property
    def saved_response(self) -> RecoveryStep:
        return next(step for step in self.steps if not step.coached)


def schedule_unresolved(
    queued: QueuedRetrieval, attempt: TransferAttempt
) -> TransferAttempt:
    """Accept a later attempt for an unresolved correction, or refuse it.

    The rule is the correction contract's own rather than a second copy. Repeating the
    interview question measures recall of one answer, and after a real interview that is
    the most tempting wrong thing to do.
    """
    require_material_difference(queued, attempt)
    return attempt


__all__ = [
    "MAX_COACHED_REPLAYS",
    "MAX_SAVED_RESPONSES",
    "RecoveryError",
    "RecoveryPlan",
    "RecoveryStep",
    "schedule_unresolved",
]

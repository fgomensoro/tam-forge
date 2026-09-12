"""The daily handoff: what the day left behind, in the plan's words, for the next day's Coach.

Closing a day records, per block, whether the work was completed, deferred or left
unfinished, whether the learner worked independently or with the Coach, and the focused
minutes the timer measured. It also states one exact next action. Every value here is
derived from recorded state; nothing is inferred. A block completed with the Coach in the
room is recorded as completed and coached, never as demonstrated: mastery is judged by
the reviewer over evidence, not by the fact that the block ended.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Literal

Outcome = Literal["completed", "deferred", "unfinished"]
Assistance = Literal["independent", "coached"]

COMPLETED_STATES: Final[frozenset[str]] = frozenset(
    {"self_review_complete", "ai_processing", "feedback_ready", "demonstrated"}
)
DEFERRED_STATES: Final[frozenset[str]] = frozenset({"incomplete", "superseded"})
NEXT_ACTION_MAX_CHARS: Final = 500


@dataclass(frozen=True, slots=True)
class HandoffActivityInput:
    activity_id: int
    stable_id: str
    objective: str
    state: str
    required: bool
    focused_seconds: int
    coached: bool
    note_id: int | None = None


@dataclass(frozen=True, slots=True)
class HandoffBlock:
    activity_id: int
    stable_id: str
    outcome: Outcome
    assistance: Assistance
    focused_minutes: int
    state: str
    note_id: int | None = None

    def as_json(self) -> dict[str, object]:
        return {
            "activity_id": self.activity_id,
            "stable_id": self.stable_id,
            "outcome": self.outcome,
            "assistance": self.assistance,
            "focused_minutes": self.focused_minutes,
            "state": self.state,
            "note_id": self.note_id,
        }


@dataclass(frozen=True, slots=True)
class HandoffDraft:
    blocks: tuple[HandoffBlock, ...]
    gaps: tuple[str, ...]
    next_action: str
    focused_minutes: int


def outcome_for(state: str) -> Outcome:
    if state in COMPLETED_STATES:
        return "completed"
    if state in DEFERRED_STATES:
        return "deferred"
    return "unfinished"


def build_handoff(
    activities: Sequence[HandoffActivityInput],
    *,
    unfinished_requirement: str | None,
    pending_correction_ids: Sequence[int] = (),
) -> HandoffDraft:
    blocks = tuple(
        HandoffBlock(
            activity_id=item.activity_id,
            stable_id=item.stable_id,
            outcome=outcome_for(item.state),
            assistance="coached" if item.coached else "independent",
            focused_minutes=item.focused_seconds // 60,
            state=item.state,
            note_id=item.note_id,
        )
        for item in activities
    )
    gaps: list[str] = []
    for item, block in zip(activities, blocks, strict=True):
        if block.outcome == "unfinished":
            label = "required" if item.required else "useful"
            gaps.append(f"{item.stable_id} ({label}) left {item.state}")
        elif block.outcome == "deferred":
            gaps.append(f"{item.stable_id} deferred as {item.state}")
    requirement = (unfinished_requirement or "").strip()
    if requirement:
        gaps.append(requirement)
    for correction_id in pending_correction_ids:
        gaps.append(f"correction {correction_id} still due")
    return HandoffDraft(
        blocks=blocks,
        gaps=tuple(gaps),
        next_action=_next_action(activities, pending_correction_ids),
        focused_minutes=sum(block.focused_minutes for block in blocks),
    )


def _next_action(activities: Sequence[HandoffActivityInput], corrections: Sequence[int]) -> str:
    for item in activities:
        if item.state == "output_committed":
            return _clip(f"Submit the self-review for {item.stable_id}.")
    for item in activities:
        if item.required and outcome_for(item.state) == "unfinished":
            return _clip(f"Finish {item.stable_id}: {item.objective}")
    for item in activities:
        if item.state in {"correction_due", "needs_work"}:
            return _clip(f"Complete the due correction for {item.stable_id}.")
    if corrections:
        return f"Complete correction {corrections[0]} before starting new work."
    for item in activities:
        if not item.required and outcome_for(item.state) == "unfinished":
            return _clip(f"Pick up {item.stable_id} if time allows: {item.objective}")
    return "Start the first block of the next study day."


def _clip(text: str) -> str:
    if len(text) <= NEXT_ACTION_MAX_CHARS:
        return text
    return text[: NEXT_ACTION_MAX_CHARS - 1].rstrip() + "…"


def render_handoff(*, local_date: str, next_action: str, gaps: Sequence[str]) -> str:
    """The lines the next day's Coach opens with; the plan's words, not the Coach's."""
    lines = [f"Previous study day {local_date} closed.", f"Next action: {next_action}"]
    if gaps:
        lines.append("Open gaps:")
        lines.extend(f"- {gap}" for gap in gaps)
    else:
        lines.append("Open gaps: none")
    return "\n".join(lines)


__all__ = [
    "COMPLETED_STATES",
    "DEFERRED_STATES",
    "HandoffActivityInput",
    "HandoffBlock",
    "HandoffDraft",
    "build_handoff",
    "outcome_for",
    "render_handoff",
]

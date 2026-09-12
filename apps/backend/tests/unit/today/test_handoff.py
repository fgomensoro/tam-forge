"""The handoff records what happened; it never upgrades a coached block to mastery."""

from __future__ import annotations

from tamforge_backend.today.handoff import (
    HandoffActivityInput,
    build_handoff,
    outcome_for,
    render_handoff,
)


def _activity(
    activity_id: int,
    stable_id: str,
    state: str,
    *,
    required: bool = True,
    seconds: int = 0,
    coached: bool = False,
) -> HandoffActivityInput:
    return HandoffActivityInput(
        activity_id=activity_id,
        stable_id=stable_id,
        objective=f"Do {stable_id}.",
        state=state,
        required=required,
        focused_seconds=seconds,
        coached=coached,
    )


def test_outcomes_follow_recorded_state_only() -> None:
    assert outcome_for("self_review_complete") == "completed"
    assert outcome_for("demonstrated") == "completed"
    assert outcome_for("incomplete") == "deferred"
    assert outcome_for("superseded") == "deferred"
    for state in ("ready", "active", "paused", "output_committed", "correction_due", "needs_work"):
        assert outcome_for(state) == "unfinished"


def test_a_day_can_close_with_gaps_and_records_assistance_and_minutes() -> None:
    draft = build_handoff(
        (
            _activity(1, "d01-recall", "self_review_complete", seconds=1500, coached=True),
            _activity(2, "d01-sql", "ready", seconds=0),
            _activity(3, "d01-optional", "incomplete", required=False, seconds=90),
        ),
        unfinished_requirement="Complete the remaining required roadmap work.",
        pending_correction_ids=(7,),
    )

    assert [block.outcome for block in draft.blocks] == ["completed", "unfinished", "deferred"]
    assert [block.assistance for block in draft.blocks] == [
        "coached",
        "independent",
        "independent",
    ]
    assert [block.focused_minutes for block in draft.blocks] == [25, 0, 1]
    assert draft.blocks[0].as_json()["note_id"] is None
    assert draft.focused_minutes == 26
    assert draft.gaps == (
        "d01-sql (required) left ready",
        "d01-optional deferred as incomplete",
        "Complete the remaining required roadmap work.",
        "correction 7 still due",
    )
    assert draft.next_action == "Finish d01-sql: Do d01-sql."
    # A coached completion is completed and coached; there is no mastery field to set.
    assert not hasattr(draft.blocks[0], "demonstrated")
    assert draft.blocks[0].state == "self_review_complete"


def test_an_approved_note_is_linked_from_the_block_that_produced_it() -> None:
    draft = build_handoff(
        (
            HandoffActivityInput(
                activity_id=1,
                stable_id="d01-recall",
                objective="Recall.",
                state="self_review_complete",
                required=True,
                focused_seconds=600,
                coached=True,
                note_id=77,
            ),
        ),
        unfinished_requirement=None,
    )
    assert draft.blocks[0].note_id == 77
    assert draft.blocks[0].as_json()["note_id"] == 77


def test_the_next_action_is_the_plans_and_prefers_the_pending_self_review() -> None:
    committed = build_handoff(
        (
            _activity(1, "d01-recall", "output_committed"),
            _activity(2, "d01-sql", "ready"),
        ),
        unfinished_requirement=None,
    )
    assert committed.next_action == "Submit the self-review for d01-recall."

    clean = build_handoff(
        (_activity(1, "d01-recall", "self_review_complete"),), unfinished_requirement=None
    )
    assert clean.gaps == ()
    assert clean.next_action == "Start the first block of the next study day."

    correction = build_handoff(
        (_activity(1, "d01-recall", "demonstrated"),),
        unfinished_requirement=None,
        pending_correction_ids=(9,),
    )
    assert correction.next_action == "Complete correction 9 before starting new work."

    useful = build_handoff(
        (
            _activity(1, "d01-recall", "self_review_complete"),
            _activity(2, "d01-extra", "paused", required=False),
        ),
        unfinished_requirement=None,
    )
    assert useful.next_action.startswith("Pick up d01-extra if time allows")


def test_the_rendered_handoff_opens_with_the_next_action_and_the_gaps() -> None:
    text = render_handoff(
        local_date="2026-09-11", next_action="Finish d01-sql: Do d01-sql.", gaps=("a", "b")
    )
    assert text.splitlines() == [
        "Previous study day 2026-09-11 closed.",
        "Next action: Finish d01-sql: Do d01-sql.",
        "Open gaps:",
        "- a",
        "- b",
    ]
    assert render_handoff(local_date="2026-09-11", next_action="x", gaps=()).endswith(
        "Open gaps: none"
    )

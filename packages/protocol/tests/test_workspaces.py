"""SQL workspace session rules: phase timing, the AI lock, the hint ladder, mistakes."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from tamforge_protocol.workspaces import (
    HINT_LADDER,
    NO_HINT_LEVEL,
    PHASE_ORDER,
    PHASE_SECONDS,
    PRIMARY_WORK_DEADLINE_SECONDS,
    QUALIFYING_ASSISTANCE,
    SESSION_SECONDS,
    SOLUTION_HINT_LEVEL,
    SqlAttemptCommitment,
    WorkspaceRuleError,
    ai_lock_reason,
    assistance_code,
    phase_at,
    qualifies_as_evidence,
    reveal_hint,
)


def commitment(**overrides: object) -> SqlAttemptCommitment:
    data: dict[str, object] = {
        "exercise_key": "support_counts",
        "exercise_version": 1,
        "query": "select account_id, count(*) from tickets group by account_id",
        "result_validation": "matched",
        "explanation": "Counts tickets per account.",
        "business_meaning": "Shows which accounts generate the most support load.",
        "self_review": "I grouped before filtering and checked the grain.",
        "reached_hint_level": 0,
        "mistake_category": "none",
        "assistance": "no_ai",
        "elapsed_seconds": 1_500,
    }
    data.update(overrides)
    return SqlAttemptCommitment.model_validate(data)


def test_the_four_phases_are_ordered_and_fill_forty_five_minutes() -> None:
    assert PHASE_ORDER == ("retrieval", "primary_work", "validation", "self_review")
    assert [PHASE_SECONDS[phase] for phase in PHASE_ORDER] == [300, 1_800, 300, 300]
    assert SESSION_SECONDS == 2_700


@pytest.mark.parametrize(
    "elapsed,expected",
    [
        (0, "retrieval"),
        (299, "retrieval"),
        (300, "primary_work"),
        (2_099, "primary_work"),
        (2_100, "validation"),
        (2_399, "validation"),
        (2_400, "self_review"),
        (2_699, "self_review"),
        (2_700, None),
    ],
)
def test_phase_boundaries(elapsed: int, expected: str | None) -> None:
    assert phase_at(elapsed) == expected


def test_a_negative_elapsed_time_is_rejected() -> None:
    with pytest.raises(WorkspaceRuleError):
        phase_at(-1)


def test_ai_stays_locked_until_the_learner_commits() -> None:
    assert ai_lock_reason(committed=False, elapsed_seconds=0) == "awaiting_commitment"
    assert (
        ai_lock_reason(committed=False, elapsed_seconds=PRIMARY_WORK_DEADLINE_SECONDS - 1)
        == "awaiting_commitment"
    )
    assert ai_lock_reason(committed=True, elapsed_seconds=0) == "unlocked"


def test_the_primary_work_deadline_unlocks_ai_without_a_commitment() -> None:
    assert PRIMARY_WORK_DEADLINE_SECONDS == 2_100
    assert (
        ai_lock_reason(committed=False, elapsed_seconds=PRIMARY_WORK_DEADLINE_SECONDS)
        == "unlocked"
    )


def test_no_hint_is_available_while_ai_is_locked() -> None:
    with pytest.raises(WorkspaceRuleError, match="locked"):
        reveal_hint(
            reached_level=NO_HINT_LEVEL,
            requested_level=1,
            committed=False,
            elapsed_seconds=0,
        )


def test_hints_are_revealed_one_rung_at_a_time() -> None:
    assert HINT_LADDER == (
        "restate_goal",
        "locate_tables",
        "name_the_operation",
        "query_skeleton",
        "full_solution",
    )
    reached = NO_HINT_LEVEL
    for level in range(1, SOLUTION_HINT_LEVEL):
        reached = reveal_hint(
            reached_level=reached, requested_level=level, committed=True, elapsed_seconds=0
        )
        assert reached == level


def test_skipping_a_rung_is_refused() -> None:
    with pytest.raises(WorkspaceRuleError, match="order"):
        reveal_hint(reached_level=1, requested_level=3, committed=True, elapsed_seconds=0)


def test_rereading_a_reached_hint_does_not_advance_the_ladder() -> None:
    assert (
        reveal_hint(reached_level=3, requested_level=2, committed=True, elapsed_seconds=0) == 3
    )


def test_a_level_outside_the_ladder_is_refused() -> None:
    for level in (0, SOLUTION_HINT_LEVEL + 1):
        with pytest.raises(WorkspaceRuleError):
            reveal_hint(
                reached_level=NO_HINT_LEVEL,
                requested_level=level,
                committed=True,
                elapsed_seconds=0,
            )


def test_the_solution_is_revealed_only_after_a_saved_attempt() -> None:
    with pytest.raises(WorkspaceRuleError, match="saved"):
        reveal_hint(
            reached_level=SOLUTION_HINT_LEVEL - 1,
            requested_level=SOLUTION_HINT_LEVEL,
            committed=True,
            elapsed_seconds=0,
            saved_attempt=False,
        )
    assert (
        reveal_hint(
            reached_level=SOLUTION_HINT_LEVEL - 1,
            requested_level=SOLUTION_HINT_LEVEL,
            committed=True,
            elapsed_seconds=0,
            saved_attempt=True,
        )
        == SOLUTION_HINT_LEVEL
    )


@pytest.mark.parametrize(
    "reached,before_commitment,expected",
    [
        (0, False, "no_ai"),
        (0, True, "no_ai"),
        (1, False, "ai_after_committed_attempt"),
        (4, False, "ai_after_committed_attempt"),
        (1, True, "ai_hints_during_attempt"),
        (4, True, "ai_hints_during_attempt"),
        (5, False, "ai_generated"),
        (5, True, "ai_generated"),
    ],
)
def test_the_reached_rung_decides_the_assistance_code(
    reached: int, before_commitment: bool, expected: str
) -> None:
    assert (
        assistance_code(reached_level=reached, hints_taken_before_commitment=before_commitment)
        == expected
    )


def test_only_unassisted_and_post_commitment_work_qualifies_as_evidence() -> None:
    assert QUALIFYING_ASSISTANCE == frozenset({"no_ai", "ai_after_committed_attempt"})
    assert qualifies_as_evidence("no_ai") is True
    assert qualifies_as_evidence("ai_after_committed_attempt") is True
    for code in ("ai_hints_during_attempt", "ai_co_created", "ai_generated"):
        assert qualifies_as_evidence(code) is False


def test_a_commitment_records_the_reached_rung_and_the_mistake() -> None:
    record = commitment(
        reached_hint_level=2,
        assistance="ai_after_committed_attempt",
        result_validation="wrong_grain",
        mistake_category="wrong_grain",
    )

    assert record.reached_hint_level == 2
    assert record.mistake_category == "wrong_grain"
    assert record.qualifies_as_evidence is True


def test_a_commitment_whose_assistance_contradicts_its_rung_is_rejected() -> None:
    with pytest.raises(ValidationError):
        commitment(reached_hint_level=3, assistance="no_ai")
    with pytest.raises(ValidationError):
        commitment(reached_hint_level=0, assistance="ai_generated")


def test_a_rung_outside_the_ladder_is_rejected() -> None:
    with pytest.raises(ValidationError):
        commitment(reached_hint_level=SOLUTION_HINT_LEVEL + 1, assistance="ai_generated")


def test_a_failed_result_must_name_its_mistake() -> None:
    with pytest.raises(ValidationError):
        commitment(result_validation="mismatch", mistake_category="none")
    assert commitment(result_validation="mismatch", mistake_category="missing_filter")


def test_an_uncategorised_mistake_is_not_a_category() -> None:
    with pytest.raises(ValidationError):
        commitment(result_validation="mismatch", mistake_category="other")


def test_the_learner_fields_cannot_be_blank() -> None:
    for field in ("query", "explanation", "business_meaning", "self_review"):
        with pytest.raises(ValidationError):
            commitment(**{field: "   "})


def test_a_commitment_cannot_outlast_the_session() -> None:
    assert commitment(elapsed_seconds=SESSION_SECONDS)
    with pytest.raises(ValidationError):
        commitment(elapsed_seconds=SESSION_SECONDS + 1)

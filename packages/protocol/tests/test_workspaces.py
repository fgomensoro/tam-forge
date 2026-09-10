"""Workspace session rules: SQL timing, lock, hints and mistakes; reading timeboxes."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from tamforge_protocol.workspaces import (
    CASE_PHASE_ORDER,
    CASE_PHASE_SECONDS,
    CASE_SESSION_SECONDS,
    HINT_LADDER,
    MAX_ROUTINE_FOLLOW_UPS,
    NO_HINT_LEVEL,
    PHASE_ORDER,
    PHASE_SECONDS,
    PRIMARY_WORK_DEADLINE_SECONDS,
    QUALIFYING_ASSISTANCE,
    READING_NOTE_FIELDS,
    READING_PHASE_ORDER,
    READING_PHASE_SECONDS,
    READING_SESSION_SECONDS,
    SESSION_SECONDS,
    SOLUTION_HINT_LEVEL,
    CaseCommitment,
    NorthstarEntry,
    NorthstarHistory,
    ReadingRecallNote,
    SqlAttemptCommitment,
    WorkspaceRuleError,
    accept_follow_up,
    ai_lock_reason,
    assistance_code,
    case_phase_at,
    phase_at,
    qualifies_as_evidence,
    reading_ai_lock_reason,
    reading_phase_at,
    reveal_hint,
    source_visible,
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


# Technical-reading workspace: timeboxes, source visibility, and the recall note.


def note(**overrides: object) -> ReadingRecallNote:
    data: dict[str, object] = {
        "key_ideas": (
            "Backpressure protects the slowest consumer.",
            "Retries need a budget or they amplify an outage.",
            "Idempotency is what makes a retry safe.",
        ),
        "boundary_or_failure": "It breaks once the queue outlives the retry budget.",
        "tam_customer_example": "A customer whose webhook retries doubled their own outage.",
        "unresolved_question": "How is the retry budget chosen in practice?",
    }
    data.update(overrides)
    return ReadingRecallNote.model_validate(data)


def test_the_five_reading_phases_are_ordered_and_fill_forty_five_minutes() -> None:
    assert READING_PHASE_ORDER == ("preview", "reading", "recall", "application", "teach_back")
    assert [READING_PHASE_SECONDS[phase] for phase in READING_PHASE_ORDER] == [
        120,
        1_200,
        480,
        600,
        300,
    ]
    assert READING_SESSION_SECONDS == 2_700


@pytest.mark.parametrize(
    "elapsed,expected",
    [
        (0, "preview"),
        (119, "preview"),
        (120, "reading"),
        (1_319, "reading"),
        (1_320, "recall"),
        (1_799, "recall"),
        (1_800, "application"),
        (2_399, "application"),
        (2_400, "teach_back"),
        (2_699, "teach_back"),
        (2_700, None),
    ],
)
def test_reading_phase_boundaries(elapsed: int, expected: str | None) -> None:
    assert reading_phase_at(elapsed) == expected


def test_the_source_disappears_when_recall_starts() -> None:
    assert source_visible("preview") is True
    assert source_visible("reading") is True
    for phase in ("recall", "application", "teach_back"):
        assert source_visible(phase) is False


def test_a_finished_session_shows_no_source() -> None:
    assert source_visible(reading_phase_at(READING_SESSION_SECONDS)) is False


def test_the_tutor_waits_for_the_committed_note_and_no_clock_lets_it_in() -> None:
    assert reading_ai_lock_reason(note_committed=False) == "awaiting_commitment"
    assert reading_ai_lock_reason(note_committed=True) == "unlocked"


def test_the_recall_note_needs_all_four_fields() -> None:
    assert READING_NOTE_FIELDS == frozenset(
        {"key_ideas", "boundary_or_failure", "tam_customer_example", "unresolved_question"}
    )
    assert set(ReadingRecallNote.model_fields) == READING_NOTE_FIELDS

    for field in ("boundary_or_failure", "tam_customer_example", "unresolved_question"):
        with pytest.raises(ValidationError):
            note(**{field: "   "})


def test_the_note_needs_exactly_three_key_ideas() -> None:
    ideas = note().key_ideas
    for count in (0, 1, 2, 4):
        with pytest.raises(ValidationError):
            note(key_ideas=tuple(f"Idea {index}." for index in range(count)))
    assert len(ideas) == 3

    with pytest.raises(ValidationError):
        note(key_ideas=(ideas[0], ideas[1], "  "))


def test_the_same_idea_three_times_is_one_idea() -> None:
    idea = "Backpressure protects the slowest consumer."
    with pytest.raises(ValidationError):
        note(key_ideas=(idea, idea, "Retries need a budget."))


# Case workspace: the sixty-minute stage budgets, the evidence trail, the defense.


def case(**overrides: object) -> CaseCommitment:
    data: dict[str, object] = {
        "discovery_questions": (
            "Which accounts are affected and since when?",
            "Is the failure in ingest or in the export?",
        ),
        "assumptions": ("The customer's own retry logic is unchanged.",),
        "working_notes": "Ruled out the export path by checking the queue depth first.",
        "final_artifact": "Recommend pausing ingest for the affected tenant, then backfilling.",
        "decisions": ("Pause ingest before backfilling.", "Tell the customer today."),
        "risks": ("Backfill may double-count.", "Pausing delays their month-end close."),
        "unresolved_questions": ("Who owns the backfill window?",),
        "follow_ups": (),
        "self_review": "I named the trade-off late and should have led with it.",
        "elapsed_seconds": 3_300,
    }
    data.update(overrides)
    return CaseCommitment.model_validate(data)


def test_the_six_case_stages_are_ordered_and_fill_the_hour() -> None:
    assert CASE_PHASE_ORDER == (
        "understand",
        "discovery",
        "structure",
        "solve",
        "present",
        "self_review",
    )
    assert [CASE_PHASE_SECONDS[phase] for phase in CASE_PHASE_ORDER] == [
        300,
        600,
        300,
        1_500,
        600,
        300,
    ]
    assert CASE_SESSION_SECONDS == 3_600


@pytest.mark.parametrize(
    "elapsed,expected",
    [
        (0, "understand"),
        (299, "understand"),
        (300, "discovery"),
        (899, "discovery"),
        (900, "structure"),
        (1_199, "structure"),
        (1_200, "solve"),
        (2_699, "solve"),
        (2_700, "present"),
        (3_299, "present"),
        (3_300, "self_review"),
        (3_599, "self_review"),
        (3_600, None),
    ],
)
def test_case_stage_boundaries(elapsed: int, expected: str | None) -> None:
    assert case_phase_at(elapsed) == expected


def test_a_negative_case_clock_is_rejected() -> None:
    with pytest.raises(WorkspaceRuleError):
        case_phase_at(-1)


def test_the_defense_answers_at_most_two_routine_follow_ups() -> None:
    assert MAX_ROUTINE_FOLLOW_UPS == 2
    assert accept_follow_up(answered=0) == 1
    assert accept_follow_up(answered=1) == 2
    with pytest.raises(WorkspaceRuleError, match="two"):
        accept_follow_up(answered=MAX_ROUTINE_FOLLOW_UPS)


def test_a_third_follow_up_cannot_be_committed_either() -> None:
    exchange = {"question": "What if the backfill fails?", "answer": "Stop and escalate."}
    assert case(follow_ups=(exchange, exchange | {"question": "And the close?"}))
    with pytest.raises(ValidationError):
        case(
            follow_ups=(
                exchange,
                exchange | {"question": "And the close?"},
                exchange | {"question": "And the audit?"},
            )
        )


def test_the_commitment_saves_discovery_through_defense() -> None:
    committed = case()

    assert committed.discovery_questions and committed.assumptions
    assert committed.working_notes and committed.final_artifact
    assert committed.decisions and committed.risks
    assert committed.self_review


@pytest.mark.parametrize(
    "field",
    ["discovery_questions", "assumptions", "decisions", "risks"],
)
def test_an_empty_stage_of_the_trail_is_not_a_case(field: str) -> None:
    with pytest.raises(ValidationError):
        case(**{field: ()})


@pytest.mark.parametrize("field", ["working_notes", "final_artifact", "self_review"])
def test_the_written_stages_cannot_be_blank(field: str) -> None:
    with pytest.raises(ValidationError):
        case(**{field: "   "})


def test_the_same_decision_twice_is_one_decision() -> None:
    for field in ("discovery_questions", "decisions", "risks"):
        repeated = getattr(case(), field)[0]
        with pytest.raises(ValidationError):
            case(**{field: (repeated, repeated)})


def test_a_case_cannot_outlast_its_hour() -> None:
    assert case(elapsed_seconds=CASE_SESSION_SECONDS)
    with pytest.raises(ValidationError):
        case(elapsed_seconds=CASE_SESSION_SECONDS + 1)


# Northstar history: append-only, and only a scenario may replace what it names.


def entry(**overrides: object) -> dict:
    data: dict[str, object] = {
        "entry_id": 1,
        "kind": "fact",
        "statement": "The renewal lands in March.",
        "activity_id": 1,
        "source": "scenario",
    }
    data.update(overrides)
    return data


def history(*entries: dict) -> NorthstarHistory:
    return NorthstarHistory.model_validate({"entries": entries or (entry(),)})


def test_an_entry_is_recorded_with_where_it_came_from() -> None:
    recorded = history().entries[0]

    assert recorded.kind == "fact"
    assert recorded.source == "scenario"
    assert recorded.activity_id == 1
    assert recorded.supersedes_entry_id is None


def test_every_kind_of_line_accumulates() -> None:
    kinds = ("fact", "assumption", "decision", "risk", "unresolved_question")
    built = history(
        *(entry(entry_id=index + 1, kind=kind) for index, kind in enumerate(kinds))
    )

    assert [item.kind for item in built.current()] == list(kinds)


def test_a_recorded_entry_cannot_be_edited() -> None:
    recorded = history().entries[0]

    with pytest.raises(ValidationError):
        recorded.statement = "something else entirely"


def test_a_change_replaces_by_naming_what_it_replaces() -> None:
    built = history(
        entry(),
        entry(entry_id=2, statement="The renewal moved to May.", supersedes_entry_id=1),
    )

    assert [item.entry_id for item in built.current("fact")] == [2]
    assert len(built.entries) == 2


def test_an_agent_may_add_to_the_record_but_never_rewrite_it() -> None:
    assert history(entry(source="agent"))

    with pytest.raises(ValidationError):
        history(entry(), entry(entry_id=2, source="agent", supersedes_entry_id=1))
    with pytest.raises(ValidationError):
        history(entry(), entry(entry_id=2, source="learner", supersedes_entry_id=1))


def test_a_replacement_must_name_an_entry_already_recorded() -> None:
    with pytest.raises(ValidationError):
        history(entry(entry_id=2, supersedes_entry_id=9))
    with pytest.raises(ValidationError):
        history(entry(entry_id=1, supersedes_entry_id=1))


def test_a_replacement_stays_within_its_own_kind() -> None:
    with pytest.raises(ValidationError):
        history(entry(), entry(entry_id=2, kind="decision", supersedes_entry_id=1))


def test_one_line_cannot_be_replaced_twice() -> None:
    with pytest.raises(ValidationError):
        history(
            entry(),
            entry(entry_id=2, supersedes_entry_id=1),
            entry(entry_id=3, supersedes_entry_id=1),
        )


def test_entries_are_recorded_in_order() -> None:
    with pytest.raises(ValidationError):
        history(entry(entry_id=5), entry(entry_id=2))


def test_appending_returns_a_new_history_and_leaves_the_old_one_alone() -> None:
    original = history()
    extended = original.append(
        NorthstarEntry.model_validate(entry(entry_id=2, kind="risk", statement="Budget froze."))
    )

    assert len(original.entries) == 1
    assert len(extended.entries) == 2


def test_a_refused_append_raises_a_workspace_rule_rather_than_a_schema_error() -> None:
    with pytest.raises(WorkspaceRuleError):
        history(entry(entry_id=5)).append(NorthstarEntry.model_validate(entry(entry_id=2)))

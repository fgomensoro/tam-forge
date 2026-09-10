"""Where the case workspace contract has to agree with the backend that stores it."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from tamforge_backend.agents.model_runs import LEARNER_FIELDS
from tamforge_protocol.workspaces import (
    CASE_SESSION_SECONDS,
    MAX_ROUTINE_FOLLOW_UPS,
    CaseCommitment,
    WorkspaceRuleError,
    accept_follow_up,
    case_phase_at,
)


def test_every_redacted_case_field_exists_on_the_commitment() -> None:
    """`LEARNER_FIELDS` is what the redaction layer copies out of a committed attempt.

    A name it expects that the commitment never writes resolves to nothing, so the
    reviewer sees a hole where evidence should be. The commitment carries `self_review`
    and the follow-ups on top of that allowlist on purpose: the reflection is handed to
    a reviewer as its own input rather than copied out of the artifact.
    """
    fields = set(CaseCommitment.model_fields)
    assert LEARNER_FIELDS["case"] <= fields
    assert "self_review" in fields and "self_review" not in LEARNER_FIELDS["case"]


def test_the_hour_is_spent_before_any_stage_repeats() -> None:
    seen = [case_phase_at(elapsed) for elapsed in range(0, CASE_SESSION_SECONDS, 60)]
    ordered = [phase for index, phase in enumerate(seen) if index == 0 or phase != seen[index - 1]]
    assert ordered == list(dict.fromkeys(ordered))
    assert case_phase_at(CASE_SESSION_SECONDS) is None


def test_the_follow_up_cap_is_the_same_number_in_both_places() -> None:
    # One is checked while the defense runs, the other when the case is committed.
    # Two different caps would let a third question in and then reject the record.
    with pytest.raises(WorkspaceRuleError):
        accept_follow_up(answered=MAX_ROUTINE_FOLLOW_UPS)
    assert CaseCommitment.model_fields["follow_ups"].metadata[0].max_length == (
        MAX_ROUTINE_FOLLOW_UPS
    )


def test_a_case_commitment_is_frozen_once_written() -> None:
    committed = CaseCommitment.model_validate(
        {
            "discovery_questions": ("Which accounts are affected?",),
            "assumptions": ("Retry logic is unchanged.",),
            "working_notes": "Checked the queue depth first.",
            "final_artifact": "Pause ingest, then backfill.",
            "decisions": ("Pause ingest.",),
            "risks": ("Backfill may double-count.",),
            "self_review": "Named the trade-off too late.",
            "elapsed_seconds": 3_300,
        }
    )
    with pytest.raises(ValidationError):
        committed.working_notes = "rewritten after the fact"


def test_the_northstar_record_survives_a_scenario_that_contradicts_it() -> None:
    """A later scenario changes what is true without erasing what was recorded.

    This is the property months of accumulated history rests on. The old fact stays
    readable and the new one names it, so an answer given under the old fact can still
    be judged against what was known at the time.
    """
    from tamforge_protocol.workspaces import NorthstarEntry, NorthstarHistory

    def line(**overrides):
        return NorthstarEntry.model_validate(
            {
                "entry_id": 1,
                "kind": "fact",
                "statement": "The renewal lands in March.",
                "activity_id": 1,
                "source": "scenario",
                **overrides,
            }
        )

    record = NorthstarHistory().append(line())
    record = record.append(
        line(
            entry_id=2,
            statement="The renewal moved to May.",
            activity_id=7,
            supersedes_entry_id=1,
        )
    )

    assert [item.entry_id for item in record.current("fact")] == [2]
    assert [item.entry_id for item in record.entries] == [1, 2]
    assert record.entries[0].statement == "The renewal lands in March."


def test_an_agent_cannot_quietly_correct_the_history_it_reads() -> None:
    from pydantic import ValidationError as PydanticValidationError
    from tamforge_protocol.workspaces import SUPERSEDING_SOURCES, NorthstarEntry

    assert SUPERSEDING_SOURCES == frozenset({"scenario"})
    with pytest.raises(PydanticValidationError):
        NorthstarEntry.model_validate(
            {
                "entry_id": 2,
                "kind": "decision",
                "statement": "Actually we decided the opposite.",
                "activity_id": 4,
                "source": "agent",
                "supersedes_entry_id": 1,
            }
        )

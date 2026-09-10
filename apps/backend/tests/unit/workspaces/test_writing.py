"""Draft, one self-edit, then feedback. Two corrections, one bounded redo, cited."""

from __future__ import annotations

from typing import get_args

import pytest
from pydantic import ValidationError
from tamforge_backend.agents.model_runs import LEARNER_FIELDS
from tamforge_protocol.agents import (
    ATTEMPT_B_MAX_MINUTES,
    REQUIRED_CORRECTIONS,
    AttemptBInstruction,
    FeedbackCorrection,
)
from tamforge_protocol.workspaces import (
    REQUIRED_SELF_EDITS,
    WorkspaceRuleError,
    WritingCommitment,
    require_feedback_ready,
    writing_feedback_stage,
)

DRAFT = "The renewal is at risk because the integration has been failing since Tuesday."
EDIT = "I led with the mechanism instead of the impact; moved the impact to the first line."


def commitment(**overrides: object) -> WritingCommitment:
    data: dict[str, object] = {
        "attempt_label": "attempt_a",
        "draft_markdown": DRAFT,
        "self_edit_notes": EDIT,
        "elapsed_seconds": 900,
    }
    data.update(overrides)
    return WritingCommitment.model_validate(data)


def test_feedback_waits_for_the_draft_and_its_one_self_edit() -> None:
    assert REQUIRED_SELF_EDITS == 1
    assert writing_feedback_stage(draft_committed=False, self_edits_committed=0) == "draft"
    assert writing_feedback_stage(draft_committed=True, self_edits_committed=0) == "self_edit"
    assert writing_feedback_stage(draft_committed=True, self_edits_committed=1) == "feedback"


@pytest.mark.parametrize(
    "draft,edits", [(False, 0), (True, 0)]
)
def test_feedback_before_the_rereading_is_refused(draft: bool, edits: int) -> None:
    # Feedback on a draft the learner has not reread is feedback on a first thought.
    with pytest.raises(WorkspaceRuleError, match="feedback needs"):
        require_feedback_ready(draft_committed=draft, self_edits_committed=edits)

    assert require_feedback_ready(draft_committed=True, self_edits_committed=1) is None


def test_a_second_self_edit_before_feedback_is_refused() -> None:
    # Polishing until the weakness is gone hides the mistake the exercise surfaces.
    with pytest.raises(WorkspaceRuleError, match="one self-edit"):
        writing_feedback_stage(draft_committed=True, self_edits_committed=2)


def test_a_self_edit_without_a_draft_is_not_a_self_edit() -> None:
    with pytest.raises(WorkspaceRuleError, match="needs a draft"):
        writing_feedback_stage(draft_committed=False, self_edits_committed=1)


def test_the_commitment_fields_are_the_ones_the_reviewer_reads() -> None:
    fields = set(WritingCommitment.model_fields)

    assert LEARNER_FIELDS["writing"] <= fields
    assert LEARNER_FIELDS["writing"] == {"draft_markdown", "self_edit_notes"}


@pytest.mark.parametrize("field", ["draft_markdown", "self_edit_notes"])
def test_neither_half_of_the_commitment_can_be_blank(field: str) -> None:
    with pytest.raises(ValidationError):
        commitment(**{field: "   "})


def test_the_written_workspace_produces_attempt_a_or_attempt_b_and_nothing_else() -> None:
    assert get_args(WritingCommitment.model_fields["attempt_label"].annotation) == (
        "attempt_a",
        "attempt_b",
    )
    assert commitment(attempt_label="attempt_b").attempt_label == "attempt_b"
    with pytest.raises(ValidationError):
        commitment(attempt_label="attempt_c")


def test_feedback_returns_two_corrections_and_one_bounded_redo() -> None:
    # Both numbers belong to the feedback contract rather than this workspace, so the
    # workspace defers to them instead of restating them and drifting.
    assert REQUIRED_CORRECTIONS == 2
    assert ATTEMPT_B_MAX_MINUTES == 10
    bounds = AttemptBInstruction.model_fields["minutes"].metadata
    assert ATTEMPT_B_MAX_MINUTES in [getattr(bound, "le", None) for bound in bounds]


def test_a_correction_cannot_be_invented_without_citing_the_draft() -> None:
    unsupported = {
        "statement": "The recommendation had no owner.",
        "instruction": "Name who acts next.",
        "target_skill": "structure",
        "evidence": {
            "statement": "No owner appears.",
            "attribution": "observed_content",
            "availability": "available",
            "confidence": "0.7",
            "references": [],
        },
    }
    with pytest.raises(ValidationError):
        FeedbackCorrection.model_validate(unsupported)

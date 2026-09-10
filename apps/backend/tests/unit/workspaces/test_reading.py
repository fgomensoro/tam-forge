"""Where the reading workspace contract has to agree with the backend that stores it."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from tamforge_backend.agents.model_runs import LEARNER_FIELDS
from tamforge_protocol.workspaces import (
    READING_NOTE_FIELDS,
    READING_SESSION_SECONDS,
    ReadingRecallNote,
    reading_phase_at,
    source_visible,
)


def test_the_recall_note_fields_match_the_redaction_layers_allowlist() -> None:
    """The note lives in the protocol package, which cannot import the backend.

    `LEARNER_FIELDS` is what `agents/model_runs.py` will copy out of a committed
    attempt; a field the note carries but that allowlist does not know is a field no
    reviewer ever sees, and a field the allowlist expects but the note never writes
    resolves to nothing. Neither failure announces itself, so they are compared here.
    """
    assert READING_NOTE_FIELDS == LEARNER_FIELDS["reading"]
    assert set(ReadingRecallNote.model_fields) == LEARNER_FIELDS["reading"]


def test_a_note_missing_a_field_is_not_a_note() -> None:
    complete = {
        "key_ideas": ("First idea.", "Second idea.", "Third idea."),
        "boundary_or_failure": "It breaks past the retry budget.",
        "tam_customer_example": "A customer whose webhook retries doubled their outage.",
        "unresolved_question": "How is the budget chosen?",
    }
    assert ReadingRecallNote.model_validate(complete)

    for field in complete:
        partial = {key: value for key, value in complete.items() if key != field}
        with pytest.raises(ValidationError):
            ReadingRecallNote.model_validate(partial)


def test_the_source_is_hidden_for_every_phase_that_scores_recall() -> None:
    # Whatever the timings become, the source must be gone by the time the learner is
    # asked to produce anything from memory.
    for elapsed in range(0, READING_SESSION_SECONDS, 60):
        phase = reading_phase_at(elapsed)
        if phase in ("recall", "application", "teach_back"):
            assert source_visible(phase) is False

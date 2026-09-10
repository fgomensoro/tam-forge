"""Where the SQL workspace contract has to agree with the backend that stores it."""

from __future__ import annotations

from typing import get_args

from tamforge_backend.evidence.models import ASSISTANCE_CODES, QUALIFYING_ASSISTANCE_CODES
from tamforge_backend.workspaces.sql_contracts import SqlResult
from tamforge_protocol.workspaces import (
    QUALIFYING_ASSISTANCE,
    AssistanceCode,
    MistakeCategory,
    SqlAttemptCommitment,
)


def test_the_workspace_assistance_vocabulary_matches_the_evidence_tables() -> None:
    """The SQL workspace lives in the protocol package and cannot import the backend.

    Its assistance literal is therefore a second copy of the closed set the evidence
    tables accept. A value that drifts apart would produce a commitment PostgreSQL
    rejects at write time, so the two are compared here rather than left to chance.
    """
    assert frozenset(get_args(AssistanceCode)) == ASSISTANCE_CODES
    assert QUALIFYING_ASSISTANCE == QUALIFYING_ASSISTANCE_CODES


def test_the_commitment_records_the_same_validation_outcomes_the_runner_produces() -> None:
    """A commitment quotes the runner's verdict, so the two vocabularies are one."""
    runner = get_args(SqlResult.model_fields["validation"].annotation)
    commitment = get_args(SqlAttemptCommitment.model_fields["result_validation"].annotation)
    assert frozenset(commitment) == frozenset(runner)


def test_wrong_grain_is_both_a_runner_verdict_and_a_named_mistake() -> None:
    # The runner can tell the learner the grain is wrong; the taxonomy has to be able
    # to record that as the mistake, or a real verdict has no category to land in.
    assert "wrong_grain" in get_args(SqlResult.model_fields["validation"].annotation)
    assert "wrong_grain" in get_args(MistakeCategory)

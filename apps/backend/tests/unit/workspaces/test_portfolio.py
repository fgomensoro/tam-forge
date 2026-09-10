"""What a finished case leaves behind for a later portfolio judgment to read."""

from __future__ import annotations

from tamforge_backend.agents.model_runs import LEARNER_FIELDS
from tamforge_protocol.workspaces import CaseCommitment


def test_the_triage_material_survives_redaction() -> None:
    """Portfolio triage reasons over risk and decisions, so both must reach a reviewer.

    They only do if the redaction allowlist knows their field names. A case that
    records its risks in a field the allowlist has never heard of leaves the later
    judgment with nothing to weigh, and nothing about that failure is loud.
    """
    for field in ("risks", "decisions", "unresolved_questions"):
        assert field in LEARNER_FIELDS["case"]
        assert field in CaseCommitment.model_fields


def test_risks_and_decisions_are_lists_rather_than_one_paragraph() -> None:
    # Triage compares items across cases. A single prose blob cannot be compared,
    # counted, or carried into a priority ordering without being parsed first.
    for field in ("risks", "decisions"):
        annotation = str(CaseCommitment.model_fields[field].annotation)
        assert "tuple" in annotation

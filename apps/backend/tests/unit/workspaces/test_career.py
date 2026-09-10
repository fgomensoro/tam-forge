"""What the career-pipeline workspace has to keep for a reviewer to read."""

from __future__ import annotations

from tamforge_backend.agents.model_runs import LEARNER_FIELDS


def test_a_pipeline_action_records_what_was_done_and_what_is_next() -> None:
    """The allowlist is what a reviewer sees, so it fixes the shape of the record.

    An action with no next action is a dead end in a pipeline whose whole point is that
    something follows, and an artifact nobody summarized cannot be judged from the
    summary a reviewer is handed.
    """
    assert LEARNER_FIELDS["pipeline"] == {
        "completed_action",
        "artifact_summary",
        "next_action",
    }

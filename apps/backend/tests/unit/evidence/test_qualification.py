from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from tamforge_backend.evidence.config_loader import load_config_bundle
from tamforge_backend.evidence.qualification import (
    EvidenceCandidate,
    qualifies_as_transfer,
    qualify_evidence,
)

CONFIG_DIR = Path(__file__).parents[5] / "config"
NOW = datetime(2026, 8, 28, 12, tzinfo=UTC)


def candidate(**changes: object) -> EvidenceCandidate:
    values: dict[str, object] = {
        "event_id": 1,
        "rubric_scored": True,
        "practice_mode": "independent_practice",
        "assistance": "no_ai",
        "evaluator": "ai_rubric_reviewer",
        "attempt_kind": "attempt_a",
        "exercise_type": "troubleshooting_case",
        "mapping_version": "seed-v1",
        "scenario_key": "scenario-a",
        "occurred_at": NOW,
        "ai_role": "reviewer",
    }
    values.update(changes)
    return EvidenceCandidate(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "practice_mode",
    ["independent_practice", "timed_assessment", "mock_interview", "real_interview"],
)
@pytest.mark.parametrize("assistance", ["no_ai", "ai_after_committed_attempt"])
@pytest.mark.parametrize(
    "evaluator",
    [
        "self",
        "ai_rubric_reviewer",
        "peer",
        "human_coach",
        "explicit_interviewer_feedback",
    ],
)
def test_total_order_qualifies_every_approved_mode_assistance_and_evaluator(
    practice_mode: str,
    assistance: str,
    evaluator: str,
) -> None:
    formula = load_config_bundle(CONFIG_DIR).formula
    attempt_kind = "attempt_a" if practice_mode == "independent_practice" else "no_ai_assessment"
    result = qualify_evidence(
        candidate(
            practice_mode=practice_mode,
            assistance=assistance,
            evaluator=evaluator,
            attempt_kind=attempt_kind,
        ),
        formula=formula,
    )
    assert result.qualifying_for_level is True
    assert result.reason == "qualifies"


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"rubric_scored": False}, "missing_rubric_score"),
        ({"practice_mode": "guided_practice"}, "nonqualifying_mode"),
        ({"practice_mode": "pipeline_only"}, "nonqualifying_mode"),
        ({"assistance": "ai_hints_during_attempt"}, "nonqualifying_assistance"),
        ({"assistance": "ai_co_created"}, "nonqualifying_assistance"),
        ({"assistance": "ai_generated"}, "nonqualifying_assistance"),
        ({"attempt_kind": "attempt_b"}, "attempt_b"),
        ({"attempt_kind": "no_ai_assessment"}, "independent_requires_attempt_a"),
    ],
)
def test_total_order_excludes_non_demonstrated_evidence(
    changes: dict[str, object],
    reason: str,
) -> None:
    result = qualify_evidence(
        candidate(**changes),
        formula=load_config_bundle(CONFIG_DIR).formula,
    )
    assert result.qualifying_for_level is False
    assert result.reason == reason


def test_unknown_evaluator_fails_closed() -> None:
    result = qualify_evidence(
        candidate(evaluator="invented"),
        formula=load_config_bundle(CONFIG_DIR).formula,
    )
    assert result.qualifying_for_level is False
    assert result.reason == "unknown_evaluator"


def test_interviewer_role_is_not_coaching_and_dynamic_selector_must_be_precommitted() -> None:
    formula = load_config_bundle(CONFIG_DIR).formula
    interviewer = qualify_evidence(
        candidate(
            practice_mode="mock_interview",
            attempt_kind="attempt_a",
            ai_role="interviewer",
            assistance="no_ai",
        ),
        formula=formula,
    )
    assert interviewer.qualifying_for_level is True

    missing = qualify_evidence(
        candidate(
            required_precommit_field="domain_competency_slug",
            selected_competency=None,
            allowed_selected_competencies=frozenset({"sql_reconciliation"}),
        ),
        formula=formula,
    )
    invalid = qualify_evidence(
        candidate(
            required_precommit_field="domain_competency_slug",
            selected_competency="sql_reconciliation",
            allowed_selected_competencies=frozenset({"sql_reconciliation"}),
            selector_committed_before_attempt=False,
        ),
        formula=formula,
    )
    assert missing.reason == "missing_precommit_selector"
    assert invalid.reason == "invalid_precommit_selector"


def test_attempt_b_never_transfers_but_later_attempt_a_in_new_scenario_does() -> None:
    formula = load_config_bundle(CONFIG_DIR).formula
    prior = candidate(event_id=1, scenario_key="scenario-a", occurred_at=NOW)
    attempt_b = candidate(
        event_id=2,
        scenario_key="scenario-a",
        attempt_kind="attempt_b",
        occurred_at=NOW + timedelta(days=1),
    )
    transfer = candidate(
        event_id=3,
        scenario_key="scenario-b",
        attempt_kind="attempt_a",
        occurred_at=NOW + timedelta(days=7),
    )
    assert qualifies_as_transfer(prior=prior, candidate=attempt_b, formula=formula) is False
    assert qualifies_as_transfer(prior=prior, candidate=transfer, formula=formula) is True


# Issue #61: competency and readiness advance only from qualifying evidence, and the
# advanced state retains the link to the evidence that moved it.


def formula():
    return load_config_bundle(CONFIG_DIR).formula


def advance(current="not_started", kept=(), **changes):
    from tamforge_backend.evidence.qualification import advance_competency

    return advance_competency(
        current=current,
        candidate=candidate(**changes),
        formula=formula(),
        qualifying_event_ids=kept,
    )


@pytest.mark.parametrize(
    "practice_mode",
    ["independent_practice", "timed_assessment", "mock_interview", "real_interview"],
)
def test_each_approved_kind_of_evidence_advances_the_level(practice_mode: str) -> None:
    result = advance(practice_mode=practice_mode)

    assert result.level == "practicing"
    assert result.qualifying_event_ids == (1,)
    assert result.reason == "qualifies"


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"practice_mode": "guided_practice"}, "nonqualifying_mode"),
        ({"practice_mode": "exposure_only"}, "nonqualifying_mode"),
        ({"practice_mode": "pipeline_only"}, "nonqualifying_mode"),
        ({"assistance": "ai_hints_during_attempt"}, "nonqualifying_assistance"),
        ({"assistance": "ai_generated"}, "nonqualifying_assistance"),
        ({"attempt_kind": "attempt_b"}, "attempt_b"),
        ({"rubric_scored": False}, "missing_rubric_score"),
    ],
)
def test_evidence_that_does_not_qualify_changes_nothing(changes, reason) -> None:
    result = advance(current="practicing", kept=(7,), **changes)

    assert result.level == "practicing"
    assert result.qualifying_event_ids == (7,)
    assert result.reason == reason


def test_a_level_above_not_started_cannot_exist_without_its_evidence() -> None:
    from tamforge_backend.evidence.qualification import (
        CompetencyAdvance,
        CompetencyAdvanceError,
    )

    assert CompetencyAdvance("not_started", (), "qualifies")
    for level in ("practicing", "demonstrated"):
        with pytest.raises(CompetencyAdvanceError):
            CompetencyAdvance(level, (), "qualifies")


def test_the_ladder_stops_at_demonstrated_and_keeps_collecting_evidence() -> None:
    result = advance(current="demonstrated", kept=(7,), event_id=9)

    assert result.level == "demonstrated"
    assert result.qualifying_event_ids == (7, 9)


def test_the_same_event_never_advances_a_level_twice() -> None:
    result = advance(current="practicing", kept=(1,), event_id=1)

    assert result.level == "practicing"
    assert result.reason == "already_counted"
    assert result.qualifying_event_ids == (1,)


def test_an_event_counted_twice_is_not_a_state() -> None:
    from tamforge_backend.evidence.qualification import (
        CompetencyAdvance,
        CompetencyAdvanceError,
    )

    with pytest.raises(CompetencyAdvanceError):
        CompetencyAdvance("practicing", (3, 3), "qualifies")


def test_readiness_is_read_from_the_levels_and_stored_nowhere() -> None:
    from tamforge_backend.evidence.qualification import readiness_from

    assert readiness_from({}) == "not_ready"
    assert readiness_from({"a": "not_started", "b": "not_started"}) == "not_ready"
    assert readiness_from({"a": "practicing", "b": "not_started"}) == "partially_ready"
    assert readiness_from({"a": "demonstrated", "b": "not_started"}) == "partially_ready"
    assert readiness_from({"a": "demonstrated", "b": "demonstrated"}) == "ready"


def test_the_report_competency_vocabulary_matches_the_advance_ladder() -> None:
    """The report lives in the protocol package and cannot import the backend.

    Its level literal is a second copy of the ladder `advance_competency` walks. A value
    that drifted apart would let a report show a level no evidence rule can produce, or
    hide one it can.
    """
    from typing import get_args

    from tamforge_backend.evidence.qualification import COMPETENCY_LADDER
    from tamforge_protocol.reports import CompetencyLevel

    assert get_args(CompetencyLevel) == COMPETENCY_LADDER

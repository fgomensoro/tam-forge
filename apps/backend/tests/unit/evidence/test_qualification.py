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

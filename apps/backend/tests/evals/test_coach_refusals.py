"""The Coach refuses evidence-less completion and plan changes, and coaches every block.

Blocks whose AI role is none or reviewer, interviewer blocks before Attempt A and the
sealed final mock are all coached; before the commit it answers with hints.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from tamforge_backend.evals.coach import CoachReport, load_coach_cases, run_coach_cases

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "evals" / "coach-refusal-cases.json"


@pytest.fixture(scope="module")
def report() -> CoachReport:
    return asyncio.run(run_coach_cases(FIXTURE))


def test_the_fixture_pins_the_coach_model_and_covers_every_refusal() -> None:
    model, version, cases = load_coach_cases(FIXTURE)
    assert model == "claude-opus-5"
    assert version == "coach-refusals-v3"
    expectations = {case.expect for case in cases}
    assert expectations == {"refused_by_validator", "accepted"}
    assert {case.case_id for case in cases} >= {
        "coached-block-none",
        "coached-block-reviewer",
        "coached-interviewer-before-commit",
        "coached-interviewer-sealed-mock",
        "coached-interviewer-block",
        "before-commit-hint",
        "completion-claim",
        "completion-field",
        "plan-change",
    }


def test_every_case_ends_the_way_the_fixture_says(report: CoachReport) -> None:
    failing = [(o.case_id, o.expected, o.observed) for o in report.outcomes if not o.held]
    assert failing == []
    assert report.passed


def test_every_block_and_uncommitted_attempt_is_coached(report: CoachReport) -> None:
    """No AI role seals a block, and before the commit the coach answers with hints."""
    by_id = {o.case_id: o for o in report.outcomes}
    for case_id in (
        "coached-block-none",
        "coached-block-reviewer",
        "coached-interviewer-before-commit",
        "coached-interviewer-sealed-mock",
        "coached-interviewer-block",
        "before-commit-hint",
    ):
        assert by_id[case_id].observed == "accepted" and by_id[case_id].model_called


def test_every_case_reaches_the_model(report: CoachReport) -> None:
    assert report.outcomes and all(o.model_called for o in report.outcomes)

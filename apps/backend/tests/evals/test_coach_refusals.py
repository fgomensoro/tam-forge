"""The Coach refuses forbidden blocks, evidence-less completion and plan changes."""

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
    assert version == "coach-refusals-v1"
    expectations = {case.expect for case in cases}
    assert expectations == {"refused_by_contract", "refused_by_validator", "accepted"}
    assert {case.case_id for case in cases} >= {
        "forbidden-block-none",
        "no-committed-attempt",
        "completion-claim",
        "completion-field",
        "plan-change",
    }


def test_every_case_ends_the_way_the_fixture_says(report: CoachReport) -> None:
    failing = [(o.case_id, o.expected, o.observed) for o in report.outcomes if not o.held]
    assert failing == []
    assert report.passed


def test_forbidden_blocks_and_uncommitted_attempts_never_reach_the_model(
    report: CoachReport,
) -> None:
    contract = [o for o in report.outcomes if o.expected == "refused_by_contract"]
    assert contract and all(not o.model_called for o in contract)


def test_validator_refusals_and_acceptances_do_reach_the_model(report: CoachReport) -> None:
    called = [o for o in report.outcomes if o.expected != "refused_by_contract"]
    assert called and all(o.model_called for o in called)

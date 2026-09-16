"""The reviewer scores inside the rubric, in half points, and never claims to act."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from tamforge_backend.evals.reviewer import ReviewerReport, load_reviewer_cases, run_reviewer_cases

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "evals" / "reviewer-refusal-cases.json"


@pytest.fixture(scope="module")
def report() -> ReviewerReport:
    return asyncio.run(run_reviewer_cases(FIXTURE))


def test_the_fixture_pins_the_reviewer_model_and_covers_every_refusal() -> None:
    model, version, cases = load_reviewer_cases(FIXTURE)
    assert model == "claude-fable-5-1" and version == "reviewer-refusals-v1"
    assert {case.expect for case in cases} == {
        "refused_by_contract",
        "refused_by_validator",
        "accepted",
    }
    assert {case.case_id for case in cases} >= {
        "score-above-maximum",
        "dimension-not-in-rubric",
        "quarter-point-score",
        "completion-claim",
        "scored-in-half-points",
    }


def test_every_case_ends_the_way_the_fixture_says(report: ReviewerReport) -> None:
    failing = [(o.case_id, o.expected, o.observed) for o in report.outcomes if not o.held]
    assert failing == []
    assert report.passed


def test_contract_refusals_never_reach_the_model(report: ReviewerReport) -> None:
    contract = [o for o in report.outcomes if o.expected == "refused_by_contract"]
    assert contract and all(not o.model_called for o in contract)

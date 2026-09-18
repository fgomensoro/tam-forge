"""The practice review scores three dimensions in half points and quotes only the answer."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from tamforge_backend.evals.practice_review import (
    PracticeReviewReport,
    load_practice_review_cases,
    run_practice_review_cases,
)

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "evals"
    / "practice-review-refusal-cases.json"
)


@pytest.fixture(scope="module")
def report() -> PracticeReviewReport:
    return asyncio.run(run_practice_review_cases(FIXTURE))


def test_the_fixture_pins_the_model_and_covers_every_refusal() -> None:
    model, version, cases = load_practice_review_cases(FIXTURE)
    assert model == "claude-fable-5-1" and version == "practice-review-refusals-v1"
    assert {case.expect for case in cases} == {
        "refused_by_contract",
        "refused_by_validator",
        "accepted",
    }
    assert {case.case_id for case in cases} >= {
        "answer-too-short",
        "missing-dimension",
        "follow-up-dimension-scored",
        "quarter-point-score",
        "invented-evidence",
        "evidence-from-the-reference-answer",
        "invented-heard-quote",
        "completion-claim",
        "half-points-and-quotes",
    }


def test_every_case_ends_the_way_the_fixture_says(report: PracticeReviewReport) -> None:
    failing = [(o.case_id, o.expected, o.observed) for o in report.outcomes if not o.held]
    assert failing == []
    assert report.passed


def test_a_contract_refusal_never_reaches_the_model(report: PracticeReviewReport) -> None:
    refused = [o for o in report.outcomes if o.expected == "refused_by_contract"]
    assert refused and all(not o.model_called for o in refused)

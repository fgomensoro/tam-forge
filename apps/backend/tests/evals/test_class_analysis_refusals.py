"""The class analysis scores in half points, quotes the transcript, and compares honestly."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from tamforge_backend.evals.class_analysis import (
    ClassAnalysisReport,
    load_class_analysis_cases,
    run_class_analysis_cases,
)

FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "evals" / "class-analysis-refusal-cases.json"
)


@pytest.fixture(scope="module")
def report() -> ClassAnalysisReport:
    return asyncio.run(run_class_analysis_cases(FIXTURE))


def test_the_fixture_pins_the_model_and_covers_every_refusal() -> None:
    model, version, cases = load_class_analysis_cases(FIXTURE)
    assert model == "claude-fable-5-1" and version == "class-analysis-refusals-v1"
    assert {case.expect for case in cases} == {
        "refused_by_contract",
        "refused_by_validator",
        "accepted",
    }
    assert {case.case_id for case in cases} >= {
        "no-transcript",
        "quarter-point-score",
        "invented-example",
        "first-class-with-history",
        "half-points-and-quotes",
    }


def test_every_case_ends_the_way_the_fixture_says(report: ClassAnalysisReport) -> None:
    failing = [(o.case_id, o.expected, o.observed) for o in report.outcomes if not o.held]
    assert failing == []
    assert report.passed

"""The weekly report lists every skill once, suggests inside the catalog, applies nothing."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from tamforge_backend.evals.weekly_report import (
    WeeklyReportReport,
    load_weekly_report_cases,
    run_weekly_report_cases,
)

FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "evals" / "weekly-report-refusal-cases.json"
)


@pytest.fixture(scope="module")
def report() -> WeeklyReportReport:
    return asyncio.run(run_weekly_report_cases(FIXTURE))


def test_the_fixture_pins_the_model_and_covers_every_refusal() -> None:
    model, version, cases = load_weekly_report_cases(FIXTURE)
    assert model == "claude-fable-5-1" and version == "weekly-report-refusals-v1"
    assert {case.expect for case in cases} == {
        "refused_by_contract",
        "refused_by_validator",
        "accepted",
    }
    assert {case.case_id for case in cases} >= {
        "no-skill-catalog",
        "skill-missing",
        "plan-applied-claim",
        "every-skill-once",
    }


def test_every_case_ends_the_way_the_fixture_says(report: WeeklyReportReport) -> None:
    failing = [(o.case_id, o.expected, o.observed) for o in report.outcomes if not o.held]
    assert failing == []
    assert report.passed

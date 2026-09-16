"""The monthly report lists every skill once and names the gaps the ledger shows, in order."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from tamforge_backend.evals.monthly_report import (
    MonthlyReportReport,
    load_monthly_report_cases,
    run_monthly_report_cases,
)

FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "evals" / "monthly-report-refusal-cases.json"
)


@pytest.fixture(scope="module")
def report() -> MonthlyReportReport:
    return asyncio.run(run_monthly_report_cases(FIXTURE))


def test_the_fixture_pins_the_model_and_covers_every_refusal() -> None:
    model, version, cases = load_monthly_report_cases(FIXTURE)
    assert model == "claude-fable-5-1" and version == "monthly-report-refusals-v1"
    assert {case.expect for case in cases} == {
        "refused_by_contract",
        "refused_by_validator",
        "accepted",
    }
    assert {case.case_id for case in cases} >= {
        "no-skill-catalog",
        "gaps-out-of-order",
        "plan-applied-claim",
        "gaps-in-ledger-order",
    }


def test_every_case_ends_the_way_the_fixture_says(report: MonthlyReportReport) -> None:
    failing = [(o.case_id, o.expected, o.observed) for o in report.outcomes if not o.held]
    assert failing == []
    assert report.passed

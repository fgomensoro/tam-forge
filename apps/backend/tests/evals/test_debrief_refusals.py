"""The debrief quotes the transcript, stays inside the catalog, and never touches the plan."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from tamforge_backend.evals.debrief import DebriefReport, load_debrief_cases, run_debrief_cases

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "evals" / "debrief-refusal-cases.json"


@pytest.fixture(scope="module")
def report() -> DebriefReport:
    return asyncio.run(run_debrief_cases(FIXTURE))


def test_the_fixture_pins_the_debrief_model_and_covers_every_refusal() -> None:
    model, version, cases = load_debrief_cases(FIXTURE)
    assert model == "claude-opus-5" and version == "debrief-refusals-v1"
    assert {case.expect for case in cases} == {
        "refused_by_contract",
        "refused_by_validator",
        "accepted",
    }
    assert {case.case_id for case in cases} >= {
        "no-transcript",
        "invented-quote",
        "skill-outside-catalog",
        "plan-change-claim",
        "quarter-point-dimension",
        "quoted-and-bounded",
    }


def test_every_case_ends_the_way_the_fixture_says(report: DebriefReport) -> None:
    failing = [(o.case_id, o.expected, o.observed) for o in report.outcomes if not o.held]
    assert failing == []
    assert report.passed
    called = {o.case_id: o.model_called for o in report.outcomes}
    assert called["no-transcript"] is False and called["quoted-and-bounded"] is True

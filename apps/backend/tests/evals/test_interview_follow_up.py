"""Follow-ups target what was said, and pressure probes stay a minority of good answers."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from tamforge_backend.evals.interview_follow_up import (
    PRESSURE_PROBE_MAX_SHARE,
    FollowUpReport,
    load_follow_up_cases,
    run_follow_up_cases,
)

FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "evals" / "interview-follow-up-cases.json"
)


@pytest.fixture(scope="module")
def report() -> FollowUpReport:
    return asyncio.run(run_follow_up_cases(FIXTURE))


def test_the_fixture_pins_the_model_and_covers_every_ending() -> None:
    model, version, cases = load_follow_up_cases(FIXTURE)
    assert model == "claude-fable-5-1" and version == "interview-follow-up-v1"
    assert {case.expect for case in cases} == {
        "refused_by_contract",
        "refused_by_validator",
        "none",
        "none_without_model",
        "follow_up",
    }
    assert {case.case_id for case in cases} >= {
        "invented-target",
        "target-only-in-the-reference-answer",
        "weak-point-targets-what-was-said",
        "limit-already-reached",
    }
    assert sum(case.kind == "good" for case in cases) >= 8


def test_every_case_ends_the_way_the_fixture_says(report: FollowUpReport) -> None:
    failing = [(o.case_id, o.expected, o.observed) for o in report.outcomes if not o.held]
    assert failing == []
    assert report.passed


def test_follow_ups_target_something_actually_said(report: FollowUpReport) -> None:
    by_id = {o.case_id: o for o in report.outcomes}
    assert by_id["invented-target"].observed == "refused_by_validator"
    assert by_id["target-only-in-the-reference-answer"].observed == "refused_by_validator"
    assert by_id["weak-point-targets-what-was-said"].observed == "follow_up"


def test_pressure_probes_land_on_a_minority_of_good_answers(report: FollowUpReport) -> None:
    assert 0.0 < report.pressure_probe_share < PRESSURE_PROBE_MAX_SHARE


def test_a_contract_refusal_and_a_spent_budget_never_reach_the_model(
    report: FollowUpReport,
) -> None:
    silent = [
        o for o in report.outcomes if o.expected in {"refused_by_contract", "none_without_model"}
    ]
    assert silent and all(not o.model_called for o in silent)

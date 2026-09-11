"""Failure injection across recording, jobs and storage: every invariant holds, every layer seen."""

from __future__ import annotations

import asyncio

import pytest
from tamforge_backend.evals.failure_injection import (
    SCENARIOS,
    FailureInjectionReport,
    run_failure_injection,
)


@pytest.fixture(scope="module")
def report() -> FailureInjectionReport:
    return asyncio.run(run_failure_injection())


def test_every_layer_is_exercised(report: FailureInjectionReport) -> None:
    assert report.layers == {"recording", "jobs", "storage"}
    assert len(report.outcomes) == len(SCENARIOS) >= 7


def test_every_invariant_holds(report: FailureInjectionReport) -> None:
    assert report.broken == (), report.render()
    assert report.passed


@pytest.mark.parametrize(
    "name",
    [
        "seal-during-object-store-outage",
        "create-replayed-and-reused",
        "seal-with-tampered-part-hash",
        "worker-crash-mid-job",
        "duplicate-enqueue",
        "partial-upload",
        "conflicting-bytes-same-key",
    ],
)
def test_each_named_scenario_held_and_recorded_what_it_saw(
    report: FailureInjectionReport, name: str
) -> None:
    outcome = next(o for o in report.outcomes if o.name == name)
    assert outcome.held, outcome.observed
    assert outcome.observed and outcome.invariant


def test_the_report_names_no_bytes_or_keys(report: FailureInjectionReport) -> None:
    text = report.render()
    assert "immutable audio bytes" not in text and "original bytes" not in text
    assert '"passed": true' in text

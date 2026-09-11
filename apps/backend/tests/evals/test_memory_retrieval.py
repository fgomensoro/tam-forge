"""Memory retrieval evaluation: recall, relevance, provenance, zero leakage on the seeded set."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from tamforge_backend.evals import THRESHOLDS, load_memory_cases, run_memory_cases
from tamforge_backend.evals.scoring import Thresholds

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "evals" / "memory-cases.json"
AT = datetime(2026, 9, 12, 15, tzinfo=UTC)


@pytest.fixture(scope="module")
def report():
    return run_memory_cases(load_memory_cases(FIXTURE), at=AT)


def test_the_fixture_is_versioned_and_hashed(report) -> None:
    assert report.fixture_version == "memory-cases-v1" and len(report.fixture_sha256) == 64
    assert report.evaluator_version == "memory-eval-v1"


def test_required_recall_meets_the_threshold(report) -> None:
    assert report.required_recall >= THRESHOLDS.required_recall, report.render()


def test_top_k_relevance_meets_the_threshold(report) -> None:
    assert report.top_k_relevance >= THRESHOLDS.top_k_relevance, report.render()


def test_zero_forbidden_leakage_across_the_complete_seeded_set(report) -> None:
    assert report.leaks == (), report.render()


def test_every_selected_item_carries_provenance(report) -> None:
    assert report.provenance_complete


def test_the_interviewer_case_selects_nothing(report) -> None:
    case = next(s for s in report.scores if s.case_id == "interviewer-gets-nothing")
    assert case.selected == 0 and case.leaked_revision_ids == ()


def test_the_report_passes_and_renders_without_claim_text(report) -> None:
    assert report.passed
    text = report.render()
    assert "worked example" not in text and "Northwind" not in text
    assert '"passed": true' in text


def test_a_stricter_threshold_can_fail_the_same_run() -> None:
    strict = run_memory_cases(
        load_memory_cases(FIXTURE),
        at=AT,
        thresholds=Thresholds(required_recall=1.01, top_k_relevance=0.9, max_leaks=0),
    )
    assert strict.passed is False

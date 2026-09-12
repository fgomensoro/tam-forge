"""The whole evaluation suite meets its thresholds and says exactly what it ran against."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest
from tamforge_backend.evals.suite import (
    RUBRIC_WEIGHTED_AGREEMENT,
    RUBRIC_WITHIN_ONE_POINT,
    SuiteReport,
    run_suite,
    weighted_agreement,
)

REPO = Path(__file__).resolve().parents[4]
FIXTURES = REPO / "apps" / "backend" / "tests" / "fixtures" / "evals"
CONFIG = REPO / "config"
AT = datetime(2026, 9, 12, 15, tzinfo=UTC)


@pytest.fixture(scope="module")
def report() -> SuiteReport:
    return asyncio.run(run_suite(fixtures_dir=FIXTURES, config_dir=CONFIG, at=AT))


def test_every_part_meets_its_threshold(report: SuiteReport) -> None:
    failing = [(p.name, p.metric, p.value, p.threshold) for p in report.parts if not p.passed]
    assert failing == [], report.render()
    assert report.passed


def test_the_suite_covers_speech_agents_memory_and_rubric(report: SuiteReport) -> None:
    assert {p.name for p in report.parts} == {
        "memory",
        "security",
        "failure_injection",
        "speech",
        "rubric",
        "agents",
        "coach",
    }


def test_provenance_names_every_fixture_model_prompt_and_rubric_by_hash_or_version(
    report: SuiteReport,
) -> None:
    p = report.provenance
    assert set(p.fixtures) == {
        "memory-cases.json",
        "security-cases.json",
        "rubric-agreement-cases.json",
        "agent-invariant-cases.json",
        "speech-gate-cases.json",
        "coach-refusal-cases.json",
    }
    assert all(len(h) == 64 for h in p.fixtures.values())
    assert p.speech_model_filename == "ggml-small.en-q5_1.bin" and len(p.speech_model_sha256) == 64
    assert p.rubric_config_version == "seed-v1" and len(p.rubric_config_sha256) == 64
    assert p.prompt_version == "roles-v1"
    assert set(p.evaluator_versions) == {
        "suite",
        "memory",
        "security",
        "failure_injection",
        "coach",
    }


def test_rubric_agreement_uses_the_approved_floors(report: SuiteReport) -> None:
    within = next(p for p in report.parts if p.metric == "within_one_point")
    kappa = next(p for p in report.parts if p.metric == "weighted_agreement")
    assert within.threshold == RUBRIC_WITHIN_ONE_POINT == 0.85
    assert kappa.threshold == RUBRIC_WEIGHTED_AGREEMENT == 0.60


def test_weighted_agreement_is_one_for_identical_raters_and_low_for_random_ones() -> None:
    assert weighted_agreement([(i % 5, i % 5) for i in range(20)], scale_max=4) == 1.0
    scattered = [(0, 4), (4, 0), (1, 3), (3, 1), (2, 2), (0, 4), (4, 0), (1, 3)]
    assert weighted_agreement(scattered, scale_max=4) < 0.0


def test_the_report_renders_numbers_and_hashes_only(report: SuiteReport) -> None:
    text = report.render()
    assert '"passed": true' in text
    for forbidden in ("names the buyer", "worked example", "CANARY", "hunter2"):
        assert forbidden not in text

"""Security evals: authorization, injection, secrets and isolation fail closed, zero disclosure."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest
from tamforge_backend.evals.security import (
    SecurityReport,
    load_security_cases,
    run_security_cases,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "evals" / "security-cases.json"
AT = datetime(2026, 9, 12, 15, tzinfo=UTC)


@pytest.fixture(scope="module")
def report() -> SecurityReport:
    return asyncio.run(run_security_cases(load_security_cases(FIXTURE), at=AT))


def test_the_fixture_is_hashed_and_covers_every_door(report: SecurityReport) -> None:
    assert len(report.fixture_sha256) == 64
    assert {o.door for o in report.outcomes} == {
        "authorization",
        "injection",
        "secrets",
        "isolation",
    }
    assert len(report.outcomes) >= 20


def test_every_door_fails_closed(report: SecurityReport) -> None:
    assert report.open_doors == (), report.render()


def test_zero_forbidden_disclosure_across_the_complete_set(report: SecurityReport) -> None:
    assert report.disclosures == 0, report.render()
    for outcome in report.outcomes:
        assert outcome.disclosures == 0, outcome.case_id


def test_authorization_refusals_never_reach_a_handler_for_any_unlisted_role(
    report: SecurityReport,
) -> None:
    auth = [o for o in report.outcomes if o.door == "authorization"]
    assert auth and all(o.failed_closed for o in auth)


def test_tool_and_transcript_injection_are_both_refused(report: SecurityReport) -> None:
    injections = [o for o in report.outcomes if o.door == "injection"]
    assert len(injections) >= 7 and all(o.failed_closed for o in injections)


def test_the_report_passes_and_names_no_canary(report: SecurityReport) -> None:
    assert report.passed
    text = report.render()
    assert "CANARY" not in text

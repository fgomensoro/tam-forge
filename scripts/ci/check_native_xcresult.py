"""Fail closed unless the complete native UI test target passed in an xcresult."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

EXPECTED_UI_TESTS = frozenset(
    {
        "testApplicationCannotOpenAnIndependentSecondWorkspace()",
        "testAuthenticatedShellHidesDestinationsWithoutNativeSlices()",
        "testAuthenticatedShellNavigatesShowsOfflineBannerAndSignsOut()",
        "testCommittedActivityRequiresCompleteSelfReview()",
        "testDraftSurvivesNavigationButNotSignOut()",
        "testEvidenceEmptyStateNeverInventsZero()",
        "testEvidenceIsReachableFromSidebar()",
        "testEvidenceKeepsSkillAndPortfolioScalesSeparateAndMissingIsNotZero()",
        "testEvidenceKeyboardRefreshAndAccessibilityReadingOrder()",
        "testEvidencePortfolioAndActivityPagingDoNotLoseAllEvidenceRoute()",
        "testEvidenceRendersInDarkAppearanceWithLargeTextAndReducedScrollingMotion()",
        "testEvidenceSkillLineageAndBoundedPagingRemainInspectable()",
        "testEvidenceSkillsCanRetryWithoutHidingPortfolio()",
        "testNativeFoundationParityJourney()",
        "testRoadmapSelectValidateApproveActivate()",
        "testSignedOutShellUsesSelectedEnvironmentWithoutExposingSecrets()",
        "testTodayDailyCloseRequiresEvidenceAndSaves()",
        "testTodayEvidenceKeepsActivityContextAndSignOutClearsIt()",
        "testTodayOpensActivityAndTimerSurvivesNavigation()",
    }
)


class NativeXcresultError(RuntimeError):
    """Raised when native UI evidence is missing or incomplete."""


def _test_cases(node: object) -> list[dict[str, Any]]:
    if isinstance(node, list):
        return [case for child in node for case in _test_cases(child)]
    if not isinstance(node, dict):
        return []
    cases = [node] if node.get("nodeType") == "Test Case" else []
    return cases + _test_cases(node.get("children", []))


def validate_xcresult(summary: dict[str, Any], tests: dict[str, Any]) -> None:
    expected_count = len(EXPECTED_UI_TESTS)
    exact_summary = {
        "result": "Passed",
        "totalTestCount": expected_count,
        "passedTests": expected_count,
        "failedTests": 0,
        "skippedTests": 0,
        "expectedFailures": 0,
    }
    drift = {
        key: (summary.get(key), expected)
        for key, expected in exact_summary.items()
        if summary.get(key) != expected
    }
    if drift:
        raise NativeXcresultError(f"native UI summary is not clean: {drift}")

    cases = _test_cases(tests.get("testNodes", []))
    names = {case.get("name") for case in cases}
    missing = sorted(EXPECTED_UI_TESTS - names)
    unexpected = sorted(name for name in names - EXPECTED_UI_TESTS if name is not None)
    if len(cases) != expected_count or missing or unexpected:
        raise NativeXcresultError(
            "native UI test inventory drifted: "
            f"count={len(cases)}, missing={missing}, unexpected={unexpected}"
        )

    nonpassing = sorted(
        f"{case.get('name')}: {case.get('result')}"
        for case in cases
        if case.get("result") != "Passed"
    )
    if nonpassing:
        raise NativeXcresultError(f"native UI test cases are not clean: {nonpassing}")


def _xcresult_json(path: Path, report: str) -> dict[str, Any]:
    completed = subprocess.run(
        [
            "xcrun",
            "xcresulttool",
            "get",
            "test-results",
            report,
            "--path",
            str(path),
            "--format",
            "json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)
    if not isinstance(payload, dict):
        raise NativeXcresultError(f"xcresult {report} output is not an object")
    return payload


def check_xcresult(path: Path) -> None:
    if not path.is_dir():
        raise NativeXcresultError(f"xcresult bundle does not exist: {path}")
    validate_xcresult(
        _xcresult_json(path, "summary"),
        _xcresult_json(path, "tests"),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("xcresult", type=Path)
    args = parser.parse_args()
    check_xcresult(args.xcresult)
    print(f"native UI xcresult is complete: {len(EXPECTED_UI_TESTS)} passed")


if __name__ == "__main__":
    main()

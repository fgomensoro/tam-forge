from __future__ import annotations

from typing import Any

import pytest

from scripts.ci.check_native_xcresult import (
    EXPECTED_UI_TESTS,
    NativeXcresultError,
    validate_xcresult,
)


def _summary(**overrides: object) -> dict[str, object]:
    count = len(EXPECTED_UI_TESTS)
    payload: dict[str, object] = {
        "result": "Passed",
        "totalTestCount": count,
        "passedTests": count,
        "failedTests": 0,
        "skippedTests": 0,
        "expectedFailures": 0,
    }
    payload.update(overrides)
    return payload


def _tests(*, result_by_name: dict[str, str] | None = None) -> dict[str, Any]:
    results = result_by_name or {}
    return {
        "testNodes": [
            {
                "nodeType": "Test Plan",
                "children": [
                    {
                        "nodeType": "UI test bundle",
                        "children": [
                            {
                                "nodeType": "Test Suite",
                                "children": [
                                    {
                                        "nodeType": "Test Case",
                                        "name": name,
                                        "result": results.get(name, "Passed"),
                                    }
                                    for name in sorted(EXPECTED_UI_TESTS)
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
    }


def test_complete_native_ui_inventory_passes() -> None:
    validate_xcresult(_summary(), _tests())


def test_summary_rejects_skipped_or_missing_execution() -> None:
    with pytest.raises(NativeXcresultError, match="summary is not clean"):
        validate_xcresult(
            _summary(passedTests=len(EXPECTED_UI_TESTS) - 1, skippedTests=1),
            _tests(),
        )


def test_inventory_rejects_missing_parity_journey() -> None:
    tests = _tests()
    cases = tests["testNodes"][0]["children"][0]["children"][0]["children"]
    cases[:] = [
        case
        for case in cases
        if case["name"] != "testNativeFoundationParityJourney()"
    ]

    with pytest.raises(NativeXcresultError, match="inventory drifted"):
        validate_xcresult(_summary(), tests)


def test_case_level_failure_cannot_hide_behind_clean_summary() -> None:
    with pytest.raises(NativeXcresultError, match="cases are not clean"):
        validate_xcresult(
            _summary(),
            _tests(
                result_by_name={"testNativeFoundationParityJourney()": "Failed"}
            ),
        )

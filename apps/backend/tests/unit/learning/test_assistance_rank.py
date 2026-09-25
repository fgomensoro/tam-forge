"""The committed attempt's assistance mode: the coach lifts `none`, never a system mode."""

from __future__ import annotations

import pytest
from tamforge_backend.learning.service import stronger_assistance


@pytest.mark.parametrize(
    ("current", "coached", "expected"),
    [
        ("none", None, "none"),
        ("none", "coach_preparation", "coach_preparation"),
        ("none", "hint_ladder", "hint_ladder"),
        ("coach_preparation", "none", "coach_preparation"),
        ("hint_ladder", "coach_preparation", "hint_ladder"),
        ("time_expired", "hint_ladder", "time_expired"),
        ("reference_only", "coach_preparation", "reference_only"),
    ],
)
def test_stronger_assistance(current: str, coached: str | None, expected: str) -> None:
    assert stronger_assistance(current, coached) == expected

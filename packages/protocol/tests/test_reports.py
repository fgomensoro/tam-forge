"""What a report reproduces, and what it is never allowed to call progress."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError
from tamforge_protocol.reports import (
    FORBIDDEN_PROGRESS_SIGNALS,
    MAX_OPEN_CORRECTIONS,
    CalibrationDelta,
    DailyReport,
    WeeklyReport,
)

DAY = date(2026, 9, 10)


def daily(**overrides: object) -> DailyReport:
    data: dict[str, object] = {
        "owner_id": 1,
        "report_date": DAY,
        "competencies": (
            {"competency": "trade_offs", "level": "practicing", "qualifying_event_ids": (4,)},
            {"competency": "structure", "level": "not_started"},
        ),
        "open_corrections": (
            {"target_skill": "trade_offs", "instruction": "State the cost in one sentence."},
        ),
        "calibration": (
            {"competency": "trade_offs", "self_score": "3", "evaluated_score": "2"},
        ),
        "interviews": ({"interview_id": 11, "kind": "real", "outcome": "advanced"},),
    }
    data.update(overrides)
    return DailyReport.model_validate(data)


def test_a_daily_report_reproduces_the_evidence_behind_each_level() -> None:
    report = daily()
    tracked = {line.competency: line for line in report.competencies}

    assert tracked["trade_offs"].qualifying_event_ids == (4,)
    assert tracked["structure"].level == "not_started"


def test_a_level_above_not_started_cannot_appear_without_its_events() -> None:
    with pytest.raises(ValidationError, match="cite its evidence"):
        daily(competencies=({"competency": "trade_offs", "level": "demonstrated"},))


def test_an_event_is_counted_once_in_a_line() -> None:
    with pytest.raises(ValidationError, match="counts once"):
        daily(
            competencies=(
                {
                    "competency": "trade_offs",
                    "level": "practicing",
                    "qualifying_event_ids": (4, 4),
                },
            )
        )


def test_a_report_never_shows_more_than_two_open_corrections() -> None:
    assert MAX_OPEN_CORRECTIONS == 2
    two = tuple(
        {"target_skill": f"skill_{index}", "instruction": "Do the thing."} for index in range(2)
    )
    assert len(daily(open_corrections=two).open_corrections) == 2

    three = tuple(
        {"target_skill": f"skill_{index}", "instruction": "Do the thing."} for index in range(3)
    )
    with pytest.raises(ValidationError):
        daily(open_corrections=three)


def test_the_calibration_delta_is_derived_from_the_two_scores() -> None:
    over = CalibrationDelta.model_validate(
        {"competency": "trade_offs", "self_score": "3", "evaluated_score": "2"}
    )
    under = CalibrationDelta.model_validate(
        {"competency": "structure", "self_score": "1", "evaluated_score": "2.5"}
    )
    level = CalibrationDelta.model_validate(
        {"competency": "relevance", "self_score": "2", "evaluated_score": "2"}
    )

    assert over.delta == Decimal("1") and over.direction == "overrated"
    assert under.delta == Decimal("-1.5") and under.direction == "underrated"
    assert level.delta == Decimal("0") and level.direction == "calibrated"


def test_a_stored_delta_cannot_disagree_with_its_scores() -> None:
    # It is a property, so there is no field to set and nothing to contradict.
    with pytest.raises(ValidationError):
        CalibrationDelta.model_validate(
            {
                "competency": "trade_offs",
                "self_score": "3",
                "evaluated_score": "2",
                "delta": "9",
            }
        )


def test_interview_outcomes_are_reported_per_interview() -> None:
    assert daily().interviews[0].outcome == "advanced"

    with pytest.raises(ValidationError, match="one line per interview"):
        daily(
            interviews=(
                {"interview_id": 11, "kind": "real", "outcome": "advanced"},
                {"interview_id": 11, "kind": "real", "outcome": "held"},
            )
        )


def test_one_line_per_competency_in_each_section() -> None:
    duplicated = (
        {"competency": "trade_offs", "level": "practicing", "qualifying_event_ids": (4,)},
        {"competency": "trade_offs", "level": "demonstrated", "qualifying_event_ids": (5,)},
    )
    with pytest.raises(ValidationError, match="one competency line"):
        daily(competencies=duplicated)

    with pytest.raises(ValidationError, match="one calibration line"):
        daily(
            calibration=(
                {"competency": "trade_offs", "self_score": "3", "evaluated_score": "2"},
                {"competency": "trade_offs", "self_score": "2", "evaluated_score": "2"},
            )
        )


@pytest.mark.parametrize("signal", sorted(FORBIDDEN_PROGRESS_SIGNALS))
def test_no_report_carries_a_streak_or_a_volume_count(signal: str) -> None:
    # Each of these rises while a weakness stays exactly where it was.
    for model in (DailyReport, WeeklyReport):
        assert signal not in model.model_fields

    with pytest.raises(ValidationError):
        daily(**{signal: 12})


def test_the_forbidden_list_covers_streaks_and_volume() -> None:
    assert {"streak_days", "activities_completed", "minutes_practiced"} <= (
        FORBIDDEN_PROGRESS_SIGNALS
    )


def test_a_weekly_report_covers_exactly_seven_days() -> None:
    assert WeeklyReport.model_validate(
        {"owner_id": 1, "week_start": date(2026, 9, 7), "week_end": date(2026, 9, 13)}
    )

    for start, end in (
        (date(2026, 9, 7), date(2026, 9, 7)),
        (date(2026, 9, 7), date(2026, 9, 12)),
        (date(2026, 9, 7), date(2026, 9, 20)),
        (date(2026, 9, 13), date(2026, 9, 7)),
    ):
        with pytest.raises(ValidationError):
            WeeklyReport.model_validate({"owner_id": 1, "week_start": start, "week_end": end})

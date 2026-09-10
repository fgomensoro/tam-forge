"""What a report reproduces, and what it is never allowed to call progress."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError
from tamforge_protocol.assessments import (
    ASSESSMENT_MAX_MINUTES,
    SATURDAY,
    AssessmentError,
    SaturdayAssessment,
    demonstrated_from,
)
from tamforge_protocol.cadence import (
    MAX_NEXT_CORRECTIONS,
    CadenceError,
    DailyClose,
    absorb,
    replacement_minutes,
)
from tamforge_protocol.reports import (
    FORBIDDEN_PROGRESS_SIGNALS,
    MAX_OPEN_CORRECTIONS,
    CalibrationDelta,
    DailyReport,
    WeeklyReport,
)
from tamforge_protocol.transitions import (
    MonthExitReview,
    NextRoadmapActivation,
    TransitionError,
    activate_next_roadmap,
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


# Issue #97: Saturday assessments disable all AI assistance, enforce the 120-minute cap,
# and update demonstrated progress only from the saved independent evidence.

SATURDAY_DATE = date(2026, 9, 12)


def assessment(**overrides: object) -> SaturdayAssessment:
    data: dict[str, object] = {
        "assessment_id": 1,
        "owner_id": 1,
        "competency": "trade_offs",
        "held_on": SATURDAY_DATE,
        "minutes": 90,
        "saved_evidence_ids": (41,),
    }
    data.update(overrides)
    return SaturdayAssessment.model_validate(data)


def test_an_assessment_carries_no_assistance_and_no_redo() -> None:
    sat = assessment()

    assert sat.assistance == "no_ai"
    assert sat.attempt_kind == "attempt_a"


@pytest.mark.parametrize(
    "changes",
    [
        {"assistance": "ai_after_committed_attempt"},
        {"assistance": "ai_hints_during_attempt"},
        {"assistance": "ai_generated"},
        {"attempt_kind": "attempt_b"},
    ],
)
def test_an_assisted_assessment_cannot_be_constructed_at_all(changes) -> None:
    # The literals are single-valued, so the wrong shape never exists to be reported.
    with pytest.raises(ValidationError):
        assessment(**changes)


def test_the_cap_is_two_hours() -> None:
    assert ASSESSMENT_MAX_MINUTES == 120
    assert assessment(minutes=ASSESSMENT_MAX_MINUTES).minutes == 120

    for minutes in (0, ASSESSMENT_MAX_MINUTES + 1):
        with pytest.raises(ValidationError):
            assessment(minutes=minutes)


def test_a_saturday_assessment_is_held_on_a_saturday() -> None:
    assert SATURDAY_DATE.weekday() == SATURDAY

    for other in (date(2026, 9, 11), date(2026, 9, 13)):
        with pytest.raises(ValidationError, match="held on a Saturday"):
            assessment(held_on=other)


def test_only_saved_work_advances_a_competency() -> None:
    saved = assessment(saved_evidence_ids=(41, 42))
    abandoned = assessment(assessment_id=2, saved_evidence_ids=())

    assert saved.saved is True
    assert abandoned.saved is False
    assert demonstrated_from([saved, abandoned], competency="trade_offs", owner_id=1) == (41, 42)


def test_an_abandoned_assessment_contributes_nothing() -> None:
    # It says nothing about what the learner can do, so it says nothing about what they
    # have demonstrated.
    abandoned = assessment(saved_evidence_ids=())

    assert demonstrated_from([abandoned], competency="trade_offs", owner_id=1) == ()


def test_evidence_from_another_owner_or_competency_is_not_collected() -> None:
    mine = assessment(saved_evidence_ids=(41,))
    theirs = assessment(assessment_id=2, owner_id=2, saved_evidence_ids=(42,))
    elsewhere = assessment(assessment_id=3, competency="structure", saved_evidence_ids=(43,))

    assert demonstrated_from(
        [mine, theirs, elsewhere], competency="trade_offs", owner_id=1
    ) == (41,)


def test_two_assessments_cannot_claim_the_same_evidence() -> None:
    first = assessment(saved_evidence_ids=(41,))
    second = assessment(assessment_id=2, saved_evidence_ids=(41,))

    with pytest.raises(AssessmentError, match="same evidence"):
        demonstrated_from([first, second], competency="trade_offs", owner_id=1)


def test_an_evidence_id_counts_once_inside_one_assessment() -> None:
    with pytest.raises(ValidationError, match="counts once"):
        assessment(saved_evidence_ids=(41, 41))


def test_collecting_without_an_owner_is_refused() -> None:
    with pytest.raises(AssessmentError, match="owner id"):
        demonstrated_from([assessment()], competency="trade_offs", owner_id=0)


# Issue #98: the daily close carries at most two corrections, classifies unfinished work,
# and replaces or drops missed work rather than cramming or extending a later day.


def unfinished(**overrides: object) -> dict:
    data: dict[str, object] = {
        "activity_id": 7,
        "minutes_remaining": 20,
        "reason": "ran_out_of_time",
        "disposition": "carry_forward",
    }
    data.update(overrides)
    return data


def close(**overrides: object) -> DailyClose:
    data: dict[str, object] = {
        "owner_id": 1,
        "closed_on": date(2026, 9, 10),
        "completed_activity_ids": (4, 5),
        "unfinished": (unfinished(),),
        "next_corrections": (
            {"target_skill": "trade_offs", "instruction": "State the cost in one sentence."},
        ),
    }
    data.update(overrides)
    return DailyClose.model_validate(data)


def test_a_close_hands_forward_at_most_two_corrections() -> None:
    assert MAX_NEXT_CORRECTIONS == 2
    two = tuple(
        {"target_skill": f"skill_{index}", "instruction": "Do the thing."} for index in range(2)
    )
    assert len(close(next_corrections=two).next_corrections) == 2

    three = tuple(
        {"target_skill": f"skill_{index}", "instruction": "Do the thing."} for index in range(3)
    )
    with pytest.raises(ValidationError):
        close(next_corrections=three)


def test_two_corrections_on_one_skill_is_one_correction() -> None:
    doubled = (
        {"target_skill": "trade_offs", "instruction": "State the cost."},
        {"target_skill": "trade_offs", "instruction": "Name the risk."},
    )
    with pytest.raises(ValidationError, match="one correction"):
        close(next_corrections=doubled)


def test_unfinished_work_is_classified_rather_than_left_ambiguous() -> None:
    from typing import get_args

    from tamforge_protocol.cadence import UnfinishedDisposition, UnfinishedReason

    assert set(get_args(UnfinishedDisposition)) == {"carry_forward", "replaced", "dropped"}
    assert "other" not in get_args(UnfinishedReason)
    assert close().unfinished[0].reason == "ran_out_of_time"


def test_an_activity_is_finished_or_unfinished_but_not_both() -> None:
    with pytest.raises(ValidationError, match="once"):
        close(completed_activity_ids=(4, 7), unfinished=(unfinished(activity_id=7),))


def test_work_carries_forward_only_into_room_a_day_already_has() -> None:
    assert absorb(minutes_remaining=20, target_budget_minutes=90, target_planned_minutes=60) == (
        "carry_forward"
    )
    assert absorb(minutes_remaining=30, target_budget_minutes=90, target_planned_minutes=60) == (
        "carry_forward"
    )


def test_work_that_does_not_fit_is_replaced_rather_than_crammed() -> None:
    # Nothing here can make a day longer. The alternative is a plan that always fits on
    # paper and never fits in an evening.
    assert absorb(minutes_remaining=45, target_budget_minutes=90, target_planned_minutes=60) == (
        "replaced"
    )
    assert replacement_minutes(target_budget_minutes=90, target_planned_minutes=60) == 30


def test_a_full_day_drops_the_work_instead_of_absorbing_it() -> None:
    # Dropping is a real outcome. A day that absorbs everything that went wrong before
    # it is a day nobody finishes either.
    assert absorb(minutes_remaining=10, target_budget_minutes=90, target_planned_minutes=90) == (
        "dropped"
    )
    assert absorb(minutes_remaining=10, target_budget_minutes=90, target_planned_minutes=120) == (
        "dropped"
    )
    assert replacement_minutes(target_budget_minutes=90, target_planned_minutes=120) == 0


def test_finished_work_is_not_unfinished_work() -> None:
    with pytest.raises(CadenceError, match="time remaining"):
        absorb(minutes_remaining=0, target_budget_minutes=90, target_planned_minutes=10)


@pytest.mark.parametrize("budget,planned", [(-1, 10), (90, -1)])
def test_a_negative_budget_or_plan_is_refused(budget: int, planned: int) -> None:
    with pytest.raises(CadenceError, match="not negative"):
        absorb(minutes_remaining=10, target_budget_minutes=budget, target_planned_minutes=planned)
    with pytest.raises(CadenceError, match="not negative"):
        replacement_minutes(target_budget_minutes=budget, target_planned_minutes=planned)


def test_carried_forward_reads_back_only_what_carried() -> None:
    mixed = close(
        unfinished=(
            unfinished(activity_id=7, disposition="carry_forward"),
            unfinished(activity_id=8, disposition="dropped"),
            unfinished(activity_id=9, disposition="replaced"),
        )
    )

    assert [item.activity_id for item in mixed.carried_forward] == [7]


# Issue #99: a month transition compares immutable evidence to the exit criteria,
# preserves the prior roadmap link, and waits for an imported and approved next version.

IMPORTED_AT = datetime(2026, 9, 28, 9, tzinfo=UTC)


def criterion(competency: str = "trade_offs", level: str = "demonstrated") -> dict:
    return {"competency": competency, "required_level": level}


def observed(competency: str = "trade_offs", level: str = "demonstrated", **overrides) -> dict:
    data = {
        "competency": competency,
        "level": level,
        "qualifying_event_ids": () if level == "not_started" else (41,),
    }
    data.update(overrides)
    return data


def review(**overrides: object) -> MonthExitReview:
    data: dict[str, object] = {
        "owner_id": 1,
        "month_key": "month-1",
        "criteria": (criterion(),),
        "observed": (observed(),),
    }
    data.update(overrides)
    return MonthExitReview.model_validate(data)


def activation(**overrides: object) -> NextRoadmapActivation:
    data: dict[str, object] = {
        "previous_roadmap_id": 3,
        "next_version_key": "month-2",
        "imported_at": IMPORTED_AT,
        "approved_at": IMPORTED_AT,
        "approved_by": "owner",
    }
    data.update(overrides)
    return NextRoadmapActivation.model_validate(data)


def test_a_month_ends_when_the_evidence_reaches_the_criteria() -> None:
    passing = review()

    assert passing.met is True
    assert passing.unmet == ()
    assert activate_next_roadmap(passing, activation()).next_version_key == "month-2"


def test_a_month_does_not_end_because_the_calendar_moved() -> None:
    short = review(observed=(observed(level="practicing"),))

    assert short.met is False
    assert [item.competency for item in short.unmet] == ["trade_offs"]
    with pytest.raises(TransitionError, match="trade_offs"):
        activate_next_roadmap(short, activation())


def test_a_competency_nobody_observed_is_unmet_rather_than_assumed() -> None:
    unobserved = review(observed=())

    assert unobserved.met is False
    with pytest.raises(TransitionError):
        activate_next_roadmap(unobserved, activation())


def test_exceeding_a_criterion_still_meets_it() -> None:
    exceeded = review(
        criteria=(criterion(level="practicing"),), observed=(observed(level="demonstrated"),)
    )

    assert exceeded.met is True


def test_requiring_nothing_is_not_a_criterion() -> None:
    with pytest.raises(ValidationError, match="not a criterion"):
        review(criteria=(criterion(level="not_started"),))


def test_an_observed_level_carries_the_evidence_behind_it() -> None:
    with pytest.raises(ValidationError, match="cite its evidence"):
        review(observed=(observed(qualifying_event_ids=()),))


def test_one_line_per_competency_on_both_sides() -> None:
    with pytest.raises(ValidationError, match="one criterion"):
        review(criteria=(criterion(), criterion(level="practicing")))
    with pytest.raises(ValidationError, match="one observation"):
        review(observed=(observed(), observed(level="practicing")))


def test_the_next_roadmap_keeps_the_link_to_the_one_before_it() -> None:
    # A transition that forgets what came before turns a sequence of months into a
    # series of unrelated plans.
    assert activation().previous_roadmap_id == 3

    with pytest.raises(ValidationError):
        activation(previous_roadmap_id=None)


def test_a_next_version_is_imported_on_purpose_and_then_approved() -> None:
    for missing in ("imported_at", "approved_at", "approved_by"):
        with pytest.raises(ValidationError):
            activation(**{missing: None})


def test_approval_cannot_precede_the_import_it_approves() -> None:
    with pytest.raises(ValidationError, match="after it is imported"):
        activation(approved_at=IMPORTED_AT - timedelta(days=1))


def test_naive_transition_timestamps_are_refused() -> None:
    with pytest.raises(ValidationError):
        activation(imported_at=datetime(2026, 9, 28, 9))

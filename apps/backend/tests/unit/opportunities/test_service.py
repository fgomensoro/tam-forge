"""Interview day fits inside the budget, and the last stretch stays protected."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from tamforge_backend.opportunities.service import (
    ALLOWED_IN_PROTECTED_WINDOW,
    MAX_PROTECTION_MINUTES,
    MIN_PROTECTION_MINUTES,
    BudgetExceeded,
    ProtectedWindowViolation,
    SchedulingError,
    admit_activity,
    plan_interview_day,
)

INTERVIEW_AT = datetime(2026, 9, 15, 15, tzinfo=UTC)


def plan(**overrides: object):
    data: dict[str, object] = {
        "budget_minutes": 180,
        "preparation_minutes": 45,
        "interview_minutes": 60,
        "interview_at": INTERVIEW_AT,
    }
    data.update(overrides)
    return plan_interview_day(**data)  # type: ignore[arg-type]


def test_interview_work_is_substituted_into_the_budget_not_added_to_it() -> None:
    day = plan()

    assert day.budget_minutes == 180
    assert day.remaining_practice_minutes == 75
    assert day.preparation_minutes + day.interview_minutes <= day.budget_minutes


def test_a_day_that_would_have_to_grow_is_refused() -> None:
    # A day that grows to fit an interview ends with the learner more tired going in.
    with pytest.raises(BudgetExceeded):
        plan(budget_minutes=90, preparation_minutes=45, interview_minutes=60)

    assert plan(budget_minutes=105, preparation_minutes=45).remaining_practice_minutes == 0


def test_the_protected_stretch_is_between_one_hour_and_ninety_minutes() -> None:
    assert (MIN_PROTECTION_MINUTES, MAX_PROTECTION_MINUTES) == (60, 90)
    assert plan().protection_minutes == MAX_PROTECTION_MINUTES
    assert plan(protection_minutes=60).protected_from == INTERVIEW_AT - timedelta(minutes=60)

    for minutes in (59, 91):
        with pytest.raises(SchedulingError, match="60 and 90"):
            plan(protection_minutes=minutes)


@pytest.mark.parametrize("load", ["new_practice", "exhausting_practice"])
def test_nothing_demanding_runs_in_the_protected_stretch(load: str) -> None:
    day = plan()

    with pytest.raises(ProtectedWindowViolation):
        admit_activity(day, starts_at=day.protected_from, load=load)
    with pytest.raises(ProtectedWindowViolation):
        admit_activity(day, starts_at=INTERVIEW_AT - timedelta(minutes=1), load=load)


def test_light_review_is_the_one_thing_allowed_close_in() -> None:
    day = plan()

    assert ALLOWED_IN_PROTECTED_WINDOW == frozenset({"light_review"})
    assert admit_activity(day, starts_at=day.protected_from, load="light_review") is None


def test_practice_earlier_in_the_day_is_untouched() -> None:
    day = plan()
    earlier = day.protected_from - timedelta(minutes=1)

    assert admit_activity(day, starts_at=earlier, load="new_practice") is None
    assert day.protects(earlier) is False


def test_the_window_ends_when_the_interview_starts() -> None:
    day = plan()

    assert day.protects(INTERVIEW_AT) is False
    assert admit_activity(day, starts_at=INTERVIEW_AT, load="new_practice") is None


def test_a_naive_timestamp_is_refused_on_both_sides() -> None:
    with pytest.raises(SchedulingError, match="timezone-aware"):
        plan(interview_at=datetime(2026, 9, 15, 15))
    with pytest.raises(SchedulingError, match="timezone-aware"):
        admit_activity(plan(), starts_at=datetime(2026, 9, 15, 14), load="light_review")


@pytest.mark.parametrize(
    "changes",
    [{"budget_minutes": 0}, {"interview_minutes": 0}, {"preparation_minutes": -1}],
)
def test_a_day_without_a_budget_or_an_interview_length_is_refused(changes) -> None:
    with pytest.raises(SchedulingError):
        plan(**changes)


# Issue #86: only explicit outcomes and stage events move conversion and timing, and
# tone or demeanour never produces a pass/fail prediction.

from tamforge_backend.opportunities import outcomes as oc  # noqa: E402
from tamforge_protocol.opportunities import Opportunity  # noqa: E402

DAY_ZERO = datetime(2026, 9, 1, 9, tzinfo=UTC)


def stage(name: str, day: int) -> dict:
    return {"stage": name, "occurred_at": DAY_ZERO + timedelta(days=day)}


def opportunity(**overrides: object) -> Opportunity:
    data: dict[str, object] = {
        "opportunity_id": 4,
        "owner_id": 1,
        "company": "Northwind",
        "role": "Technical Account Manager",
        "job_description": {
            "captured_at": DAY_ZERO,
            "sha256": "a" * 64,
            "text": "Owns renewal health.",
        },
        "stage_history": (stage("applied", 0), stage("screen", 5), stage("panel", 12)),
    }
    data.update(overrides)
    return Opportunity.model_validate(data)


def test_timing_is_arithmetic_over_the_recorded_dates() -> None:
    durations = oc.stage_durations(opportunity())

    assert [(item.stage, item.days) for item in durations] == [("applied", 5), ("screen", 7)]


def test_the_stage_still_running_is_not_given_a_duration() -> None:
    # An open-ended duration read as a number is how "we are still waiting" turns into
    # "this took two days".
    durations = oc.stage_durations(opportunity())

    assert "panel" not in [item.stage for item in durations]


def test_conversion_counts_opportunities_that_recorded_both_stages() -> None:
    advanced = opportunity()
    stalled = opportunity(
        opportunity_id=5, stage_history=(stage("applied", 0), stage("screen", 3))
    )

    assert oc.conversion([advanced, stalled], from_stage="screen", to_stage="panel") == (1, 2)
    assert oc.reached([advanced, stalled], stage="applied") == 2


def test_conversion_returns_two_numbers_rather_than_a_rate() -> None:
    # A rate over three opportunities is noise wearing a percentage sign.
    result = oc.conversion([opportunity()], from_stage="applied", to_stage="panel")

    assert result == (1, 1)
    assert isinstance(result, tuple) and len(result) == 2


def test_there_is_no_input_for_tone_and_no_output_that_predicts() -> None:
    from dataclasses import fields

    duration_fields = {field.name for field in fields(oc.StageDuration)}
    for banned in ("tone", "sentiment", "demeanour", "demeanor", "confidence", "prediction"):
        assert banned not in duration_fields
        assert not hasattr(oc, banned)

    for predictor in ("predict", "predict_outcome", "likelihood", "will_pass", "score_interview"):
        assert not hasattr(oc, predictor)


def test_only_recorded_stage_events_are_outcome_events() -> None:
    assert "panel" in oc.OUTCOME_EVENTS
    assert "seemed_positive" not in oc.OUTCOME_EVENTS

    with pytest.raises(oc.OutcomeError, match="not a recorded outcome event"):
        oc.reached([opportunity()], stage="seemed_positive")  # type: ignore[arg-type]


def test_open_and_closed_opportunities_are_told_apart_by_their_last_event() -> None:
    open_one = opportunity()
    closed = opportunity(
        opportunity_id=6,
        stage_history=(stage("applied", 0), stage("closed_lost", 9)),
        next_action=None,
    )

    assert oc.still_open([open_one, closed]) == (open_one,)


# Issue #87: a live opportunity varies prompts, audiences and pressure, and never the
# roadmap time, coverage, assessments or exit criteria.

from tamforge_backend.opportunities import variation as vr  # noqa: E402


def roadmap_slice(**overrides: object) -> vr.RoadmapSlice:
    data: dict[str, object] = {
        "slice_key": "month-1-week-3",
        "minutes": 90,
        "required_families": ("technical_troubleshooting", "executive_communication"),
        "assessment_days": ("saturday",),
        "exit_criteria_sha256": "e" * 64,
    }
    data.update(overrides)
    return vr.RoadmapSlice(**data)  # type: ignore[arg-type]


def varied(**overrides: object) -> vr.VariedPractice:
    data: dict[str, object] = {
        "slice_": roadmap_slice(),
        "opportunity": opportunity(),
        "family": "technical_troubleshooting",
        "audience": "hiring_manager",
        "pressure": "time_pressured",
        "owner_id": 1,
    }
    data.update(overrides)
    return vr.vary_for_opportunity(
        data.pop("slice_"),  # type: ignore[arg-type]
        data.pop("opportunity"),  # type: ignore[arg-type]
        **data,  # type: ignore[arg-type]
    )


def test_a_live_opportunity_shapes_the_surface_of_the_session() -> None:
    session = varied()

    assert session.audience == "hiring_manager"
    assert session.pressure == "time_pressured"
    assert "northwind" in session.scenario_key


def test_the_roadmap_spine_is_not_copied_and_so_cannot_be_edited() -> None:
    from dataclasses import fields

    # The slice is held by reference. There is no minutes, coverage, assessment or exit
    # criteria field on the variation for anything to change.
    names = {field.name for field in fields(vr.VariedPractice)}
    assert names == {"slice", "family", "scenario_key", "audience", "pressure"}
    for spine in ("minutes", "required_families", "assessment_days", "exit_criteria_sha256"):
        assert spine not in names


def test_the_spine_reads_back_exactly_as_the_slice_left_it() -> None:
    plan = roadmap_slice()
    session = varied(slice_=plan)

    assert session.minutes == plan.minutes == 90
    assert session.exit_criteria_sha256 == plan.exit_criteria_sha256
    assert session.slice.required_families == plan.required_families
    assert session.slice.assessment_days == plan.assessment_days


def test_a_variation_stays_inside_the_coverage_the_slice_requires() -> None:
    # Practising something the slice does not require is not variation, it is a
    # different plan wearing this one's name.
    with pytest.raises(vr.VariationError, match="coverage the slice requires"):
        varied(family="sql_reconciliation")


def test_a_closed_opportunity_no_longer_steers_anything() -> None:
    # A search that ended should stop deciding what someone works on.
    closed = opportunity(
        opportunity_id=7,
        stage_history=(stage("applied", 0), stage("closed_lost", 20)),
        next_action=None,
    )

    with pytest.raises(vr.VariationError, match="closed opportunity"):
        varied(opportunity=closed)


def test_another_owners_opportunity_varies_nothing() -> None:
    with pytest.raises(vr.VariationError, match="another owner"):
        varied(owner_id=2)


@pytest.mark.parametrize(
    "changes,message",
    [
        ({"minutes": 0}, "allocates time"),
        ({"required_families": ()}, "requires coverage"),
        ({"exit_criteria_sha256": "short"}, "pins its exit criteria"),
    ],
)
def test_a_slice_without_time_coverage_or_exit_criteria_is_not_a_slice(changes, message) -> None:
    with pytest.raises(vr.VariationError, match=message):
        roadmap_slice(**changes)

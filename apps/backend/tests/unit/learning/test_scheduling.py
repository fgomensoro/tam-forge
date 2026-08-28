from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st
from tamforge_backend.learning.scheduling import (
    Carryover,
    InterviewCommitment,
    SchedulePolicyError,
    TaskTemplate,
    UnfinishedWork,
    build_day,
    curriculum_day_number,
    local_study_context,
    select_carryover,
)


def _task(
    task_id: int,
    block: str,
    minutes: int,
    *,
    order: int | None = None,
    required: bool = True,
    adaptive_priority: int | None = None,
) -> TaskTemplate:
    return TaskTemplate(
        task_definition_id=task_id,
        stable_id=f"task-{task_id}",
        mapping_version="v1",
        objective=f"Complete {block}",
        block=block,
        order=task_id if order is None else order,
        timebox_minutes=minutes,
        required=required,
        adaptive_priority=adaptive_priority,
    )


WEEKDAY_TASKS = (
    _task(1, "sql", 45),
    _task(2, "technical_learning", 45),
    _task(3, "career_pipeline", 30),
    _task(4, "correction_warmup", 10, required=False, adaptive_priority=1),
    _task(5, "tam_case", 60),
    _task(6, "communication_spoken", 35),
    _task(7, "daily_close", 15),
)
SUNDAY_DATES = st.dates(
    min_value=date(2000, 1, 1), max_value=date(2099, 12, 24)
).map(lambda value: value + timedelta(days=(6 - value.weekday()) % 7))


@given(SUNDAY_DATES)
def test_sunday_never_creates_study_work(local_date: date) -> None:
    plan = build_day(local_date, curriculum_day=None, tasks=WEEKDAY_TASKS)

    assert plan.tasks == ()
    assert plan.planned_minutes == 0
    assert plan.notifications == ()
    assert plan.missed_work == ()


def test_weekday_and_saturday_validate_the_roadmap_allocation() -> None:
    weekday = build_day(date(2026, 8, 24), curriculum_day=1, tasks=WEEKDAY_TASKS)
    saturday_tasks = tuple(
        _task(index, "saturday_assessment", minutes)
        for index, minutes in enumerate((30, 50, 25, 15), start=10)
    )
    saturday = build_day(date(2026, 8, 29), curriculum_day=6, tasks=saturday_tasks)

    assert weekday.planned_minutes == 240
    assert weekday.day_type == "weekday"
    assert saturday.planned_minutes == 120
    assert saturday.day_type == "saturday"


def test_real_interview_replaces_relevant_blocks_instead_of_stacking() -> None:
    plan = build_day(
        date(2026, 8, 24),
        curriculum_day=1,
        tasks=WEEKDAY_TASKS,
        interviews=(InterviewCommitment(id=8, minutes=60),),
    )

    assert plan.day_type == "interview"
    assert plan.interview_minutes == 60
    assert plan.planned_minutes == 205
    assert {item.block for item in plan.tasks}.isdisjoint(
        {"communication_spoken", "tam_case"}
    )
    assert plan.planned_minutes <= 255


def test_saturday_interview_replaces_assessment_and_stays_within_cap() -> None:
    saturday_tasks = tuple(
        _task(index, "saturday_assessment", minutes)
        for index, minutes in enumerate((30, 50, 25, 15), start=10)
    )

    plan = build_day(
        date(2026, 8, 29),
        curriculum_day=6,
        tasks=saturday_tasks,
        interviews=(InterviewCommitment(id=8, minutes=60),),
    )

    assert plan.tasks == ()
    assert plan.planned_minutes == 60
    assert plan.day_type == "interview"


def test_normal_weekday_below_acceptable_floor_is_rejected_without_filler() -> None:
    with pytest.raises(SchedulePolicyError, match="225"):
        build_day(
            date(2026, 8, 24),
            curriculum_day=1,
            tasks=(_task(1, "sql", 45),),
        )


def test_correction_warmup_selects_exactly_one_due_carryover() -> None:
    selected = select_carryover(
        (
            Carryover(id=2, kind="written_attempt_b", priority=2, due_date=date(2026, 8, 24)),
            Carryover(id=1, kind="spoken_attempt_b", priority=1, due_date=date(2026, 8, 24)),
            Carryover(id=3, kind="sql_correction", priority=1, due_date=date(2026, 8, 25)),
        ),
        local_date=date(2026, 8, 24),
    )

    assert selected is not None
    assert selected.id == 1
    assert selected.kind == "spoken_attempt_b"


def test_missed_work_policy_never_crams_a_future_day() -> None:
    plan = build_day(
        date(2026, 8, 24),
        curriculum_day=1,
        tasks=WEEKDAY_TASKS,
        unfinished=(
            UnfinishedWork(id=1, classification="required", minutes=10),
            UnfinishedWork(id=2, classification="useful", minutes=20),
            UnfinishedWork(id=3, classification="optional", minutes=20),
            UnfinishedWork(
                id=4,
                classification="superseded",
                minutes=20,
                stronger_evidence_id=44,
            ),
        ),
    )

    decisions = {item.work_id: item for item in plan.missed_work}
    assert decisions[1].action == "replace_adaptive"
    assert decisions[1].replaced_task_id == 4
    assert decisions[2].action == "retrieval_queue"
    assert decisions[3].action == "drop"
    assert decisions[4].action == "link_stronger_evidence"
    assert decisions[4].stronger_evidence_id == 44
    assert plan.planned_minutes == 240


def test_required_work_stays_pending_when_no_safe_replacement_exists() -> None:
    plan = build_day(
        date(2026, 8, 24),
        curriculum_day=1,
        tasks=tuple(item for item in WEEKDAY_TASKS if item.required),
        unfinished=(UnfinishedWork(id=1, classification="required", minutes=30),),
    )

    assert plan.missed_work[0].action == "pending_replacement"
    assert plan.planned_minutes == 230
    assert plan.planned_minutes <= 255


def test_curriculum_dates_are_monday_anchored_and_skip_sundays() -> None:
    start = date(2026, 8, 24)

    assert curriculum_day_number(start, date(2026, 8, 24)) == 1
    assert curriculum_day_number(start, date(2026, 8, 29)) == 6
    assert curriculum_day_number(start, date(2026, 8, 30)) is None
    assert curriculum_day_number(start, date(2026, 8, 31)) == 7
    with pytest.raises(SchedulePolicyError, match="Monday"):
        curriculum_day_number(date(2026, 8, 25), date(2026, 8, 25))


@pytest.mark.parametrize(
    ("instant", "expected_date", "expected_hours"),
    [
        (datetime(2026, 3, 8, 12, tzinfo=UTC), date(2026, 3, 8), 23),
        (datetime(2026, 11, 1, 12, tzinfo=UTC), date(2026, 11, 1), 25),
    ],
)
def test_local_study_context_uses_learner_timezone_across_dst(
    instant: datetime, expected_date: date, expected_hours: int
) -> None:
    context = local_study_context(instant, "America/Los_Angeles")

    assert context.local_date == expected_date
    assert (context.end_utc - context.start_utc).total_seconds() == expected_hours * 3600

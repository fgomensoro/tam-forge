"""Deterministic primary Continue selection for the Today workspace."""

from __future__ import annotations

from datetime import UTC, date, datetime


def _task(
    activity_id: int,
    *,
    order: int,
    block: str,
    state: str,
    required: bool = True,
):  # type: ignore[no-untyped-def]
    from tamforge_backend.today.schemas import TodayTaskCard

    return TodayTaskCard(
        activity_id=activity_id,
        roadmap_order=order,
        stable_id=f"task-{activity_id}",
        block=block,
        state=state,
        objective=f"Objective {activity_id}",
        timebox_minutes=10,
        source_references=(),
        required_output=("Saved output",),
        pass_criteria=("Independent pass",),
        allowed_ai_role="none",
        evidence_requirements=("Original output",),
        required=required,
        optimistic_version=1,
    )


def _correction(*, activity_id: int | None = 40):  # type: ignore[no-untyped-def]
    from tamforge_backend.today.schemas import TodayCorrection

    return TodayCorrection(
        id=9,
        priority=1,
        due_date=date(2026, 8, 27),
        instruction="Use a concise problem-impact-action structure.",
        status="scheduled" if activity_id is not None else "pending",
        attempt_b_activity_id=activity_id,
    )


def _analysis(activity_id: int = 60):  # type: ignore[no-untyped-def]
    from tamforge_backend.today.schemas import TodayAnalysis

    return TodayAnalysis(
        activity_id=activity_id,
        state="ready",
        progress_label="ready",
        updated_at=datetime(2026, 8, 27, 18, tzinfo=UTC),
    )


def test_continue_priority_is_strict_and_targets_one_action() -> None:
    from tamforge_backend.today.service import select_primary_action

    tasks = (
        _task(10, order=1, block="sql", state="active"),
        _task(20, order=2, block="technical_learning", state="output_committed"),
        _task(30, order=3, block="career_pipeline", state="ready"),
        _task(40, order=4, block="correction_warmup", state="ready", required=False),
        _task(70, order=7, block="daily_close", state="ready"),
    )

    correction_first = select_primary_action(
        tasks=tasks,
        corrections=(_correction(),),
        analyses=(_analysis(),),
        day_status="in_progress",
    )
    assert correction_first is not None
    assert correction_first.kind == "correction_warmup"
    assert correction_first.target_id == 40

    resumed = select_primary_action(
        tasks=tasks,
        corrections=(),
        analyses=(_analysis(),),
        day_status="in_progress",
    )
    assert resumed is not None
    assert resumed.kind == "resume_activity"
    assert resumed.target_id == 10

    self_review = select_primary_action(
        tasks=tuple(item for item in tasks if item.activity_id != 10),
        corrections=(),
        analyses=(_analysis(),),
        day_status="in_progress",
    )
    assert self_review is not None
    assert self_review.kind == "complete_self_review"
    assert self_review.target_id == 20

    next_required = select_primary_action(
        tasks=tuple(item for item in tasks if item.activity_id not in {10, 20}),
        corrections=(),
        analyses=(_analysis(),),
        day_status="in_progress",
    )
    assert next_required is not None
    assert next_required.kind == "start_activity"
    assert next_required.target_id == 30

    feedback = select_primary_action(
        tasks=(
            _task(40, order=4, block="correction_warmup", state="ready", required=False),
            _task(70, order=7, block="daily_close", state="ready"),
        ),
        corrections=(),
        analyses=(_analysis(),),
        day_status="in_progress",
    )
    assert feedback is not None
    assert feedback.kind == "review_feedback"
    assert feedback.target_id == 60

    close = select_primary_action(
        tasks=(
            _task(40, order=4, block="correction_warmup", state="ready", required=False),
            _task(70, order=7, block="daily_close", state="ready"),
        ),
        corrections=(),
        analyses=(),
        day_status="in_progress",
    )
    assert close is not None
    assert close.kind == "close_day"
    assert close.target_id == 70


def test_continue_ties_use_roadmap_order_then_immutable_id() -> None:
    from tamforge_backend.today.service import select_primary_action

    action = select_primary_action(
        tasks=(
            _task(31, order=2, block="technical_learning", state="ready"),
            _task(30, order=2, block="sql", state="ready"),
            _task(20, order=3, block="career_pipeline", state="ready"),
        ),
        corrections=(),
        analyses=(),
        day_status="planned",
    )

    assert action is not None
    assert action.kind == "start_activity"
    assert action.target_id == 30


def test_pending_correction_without_attempt_b_is_visible_but_not_actionable() -> None:
    from tamforge_backend.today.service import select_primary_action

    action = select_primary_action(
        tasks=(
            _task(30, order=3, block="career_pipeline", state="ready"),
            _task(40, order=4, block="correction_warmup", state="ready", required=False),
        ),
        corrections=(_correction(activity_id=None),),
        analyses=(),
        day_status="planned",
    )

    assert action is not None
    assert action.kind == "start_activity"
    assert action.target_id == 30


def test_off_or_closed_days_never_return_continue() -> None:
    from tamforge_backend.today.service import select_primary_action

    for status in ("off", "closed", "incomplete", "skipped"):
        assert (
            select_primary_action(
                tasks=(_task(10, order=1, block="sql", state="ready"),),
                corrections=(_correction(),),
                analyses=(_analysis(),),
                day_status=status,
            )
            is None
        )

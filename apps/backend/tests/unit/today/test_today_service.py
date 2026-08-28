"""Complete Today response, Sunday boundary, and daily-close contract tests."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError


def _roadmap():  # type: ignore[no-untyped-def]
    from tamforge_backend.today.schemas import TodayRoadmap

    return TodayRoadmap(
        version_id=4,
        version_key="month-1-v1",
        version_number=1,
        month=1,
        week=1,
        day=4,
    )


def _task(activity_id: int, order: int, block: str, state: str = "ready"):
    from tamforge_backend.today.schemas import TodayTaskCard

    return TodayTaskCard(
        activity_id=activity_id,
        roadmap_order=order,
        stable_id=f"m1-w1-d04-{block}",
        block=block,
        state=state,
        objective=f"Practice {block}",
        timebox_minutes=45 if block in {"sql", "technical_learning"} else 30,
        source_references=({"path": "Week 1.md", "anchor": block},),
        required_output=("Saved independent output",),
        pass_criteria=("Meets the roadmap criterion",),
        allowed_ai_role="tutor" if block != "career_pipeline" else "planner",
        evidence_requirements=("Original output", "Self-review"),
        required=True,
        optimistic_version=1,
    )


def _source(*, local_date: date, day_status: str = "planned", tasks=()):  # type: ignore[no-untyped-def]
    from tamforge_backend.today.schemas import TodayReadInput

    now = datetime(2026, 8, 27, 18, tzinfo=UTC)
    return TodayReadInput(
        local_date=local_date,
        timezone="America/Los_Angeles",
        day_id=12 if day_status != "off" else None,
        day_type="sunday" if day_status == "off" else "weekday",
        day_status=day_status,
        roadmap=_roadmap(),
        planned_minutes=sum(item.timebox_minutes for item in tasks),
        focused_minutes=35,
        tasks=tasks,
        corrections=(),
        interviews=(),
        awaiting_self_reviews=(),
        analyses=(),
        source_updated_at=now,
    )


def test_today_contains_every_required_card_field_and_one_continue() -> None:
    from tamforge_backend.today.schemas import (
        TodayAnalysis,
        TodayCorrection,
        TodayInterview,
        TodaySelfReview,
    )
    from tamforge_backend.today.service import build_today_response

    tasks = (
        _task(10, 1, "sql"),
        _task(20, 2, "technical_learning"),
        _task(30, 3, "career_pipeline"),
    )
    source = _source(local_date=date(2026, 8, 27), tasks=tasks).model_copy(
        update={
            "planned_minutes": 240,
            "corrections": tuple(
                TodayCorrection(
                    id=index,
                    priority=min(index, 2),
                    due_date=date(2026, 8, 27),
                    instruction=f"Correction {index}",
                    status="pending",
                    attempt_b_activity_id=None,
                )
                for index in (1, 2, 3)
            ),
            "interviews": (
                TodayInterview(
                    id=5,
                    company="ExampleCo",
                    role="Technical Account Manager",
                    stage="Hiring manager",
                    starts_at=datetime(2026, 8, 27, 20, tzinfo=UTC),
                    expected_duration_minutes=45,
                    privacy_permission_code="permission_not_requested",
                ),
            ),
            "awaiting_self_reviews": (
                TodaySelfReview(
                    activity_id=81,
                    objective="Review the saved response",
                    output_committed_at=datetime(2026, 8, 26, 20, tzinfo=UTC),
                ),
            ),
            "analyses": (
                TodayAnalysis(
                    activity_id=82,
                    state="needs_attention",
                    progress_label="action_required",
                    updated_at=datetime(2026, 8, 27, 17, tzinfo=UTC),
                ),
            ),
        }
    )

    response = build_today_response(source)

    assert response.roadmap == _roadmap()
    assert response.total_planned_minutes == 240
    assert response.time_policy.target_minutes == 240
    assert response.time_policy.acceptable_minimum == 225
    assert response.time_policy.hard_stop_minutes == 255
    assert len(response.corrections) == 2
    assert response.interviews[0].company == "ExampleCo"
    assert response.awaiting_self_reviews[0].activity_id == 81
    assert response.analyses[0].state == "needs_attention"
    assert response.primary_continue is not None
    assert response.primary_continue.kind == "start_activity"
    assert response.primary_continue.target_id == 10
    assert response.read_model_version
    assert response.etag == f'"{response.read_model_version}"'
    assert tuple(block.name for block in response.required_blocks) == (
        "sql",
        "technical_learning",
        "career_pipeline",
    )
    for task in response.tasks:
        assert task.objective
        assert task.timebox_minutes > 0
        assert task.source_references
        assert task.required_output
        assert task.pass_criteria
        assert task.allowed_ai_role
        assert task.evidence_requirements


def test_sunday_is_explicitly_off_without_work_or_continue() -> None:
    from tamforge_backend.today.service import build_today_response

    response = build_today_response(
        _source(local_date=date(2026, 8, 30), day_status="off", tasks=())
    )

    assert response.day_type == "sunday"
    assert response.day_status == "off"
    assert response.total_planned_minutes == 0
    assert response.tasks == ()
    assert response.required_blocks == ()
    assert response.primary_continue is None
    assert response.time_policy.target_minutes == 0
    assert response.time_policy.hard_stop_minutes == 0


def test_daily_close_requires_evidence_and_bounded_corrections() -> None:
    from tamforge_backend.today.schemas import DailyCloseCommand

    valid = {
        "evidence_confirmed": True,
        "evidence_manifest": {
            "schema_version": 1,
            "activity_ids": [10, 20],
            "attempt_ids": [30],
            "artifact_ids": [],
            "self_review_ids": [40],
        },
        "strongest_output": "The incident recommendation was clear and evidence-based.",
        "repeated_mistake": "I delayed stating the customer impact.",
        "unfinished_classification": "required",
        "unfinished_requirement": "Finish the assigned reconciliation explanation.",
        "correction_ids": [1, 2],
    }
    command = DailyCloseCommand.model_validate(valid)
    assert command.consequence == "replace_adaptive"

    for updates in (
        {"evidence_confirmed": False},
        {"correction_ids": [1, 2, 3]},
        {"unfinished_classification": "none"},
        {
            "unfinished_classification": "optional",
            "unfinished_requirement": None,
        },
    ):
        with pytest.raises(ValidationError):
            DailyCloseCommand.model_validate(valid | updates)


@pytest.mark.anyio
async def test_close_is_owner_scoped_and_idempotent_at_the_store_boundary() -> None:
    from tamforge_backend.today.schemas import DailyCloseCommand, DailyCloseResponse
    from tamforge_backend.today.service import TodayService

    class FakeStore:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        async def load_today(self, **values):  # type: ignore[no-untyped-def]
            raise AssertionError(values)

        async def close_day(self, **values):  # type: ignore[no-untyped-def]
            self.calls.append(values)
            return DailyCloseResponse(
                daily_close_id=44,
                study_day_id=12,
                day_status="closed",
                closed_at=datetime(2026, 8, 27, 23, tzinfo=UTC),
                consequence="none",
                replayed=len(self.calls) > 1,
            )

    command = DailyCloseCommand(
        evidence_confirmed=True,
        evidence_manifest={"schema_version": 1, "activity_ids": [10]},
        strongest_output="A concrete saved output.",
        repeated_mistake="One precise repeated mistake.",
        unfinished_classification="none",
        unfinished_requirement=None,
        correction_ids=(),
    )
    store = FakeStore()
    service = TodayService(store)
    first = await service.close_day(
        owner_id=3,
        local_date=date(2026, 8, 27),
        command=command,
        idempotency_key="close-2026-08-27",
    )
    second = await service.close_day(
        owner_id=3,
        local_date=date(2026, 8, 27),
        command=command,
        idempotency_key="close-2026-08-27",
    )

    assert first.daily_close_id == second.daily_close_id == 44
    assert store.calls == [
        {
            "owner_id": 3,
            "local_date": date(2026, 8, 27),
            "command": command,
            "idempotency_key": "close-2026-08-27",
        },
        {
            "owner_id": 3,
            "local_date": date(2026, 8, 27),
            "command": command,
            "idempotency_key": "close-2026-08-27",
        },
    ]

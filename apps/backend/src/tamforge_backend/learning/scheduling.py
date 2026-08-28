"""Deterministic roadmap scheduling in the learner's local timezone."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .time_policy import budget_for, validate_planned_minutes

CarryoverKind = Literal["spoken_attempt_b", "written_attempt_b", "sql_correction"]
UnfinishedClassification = Literal["required", "useful", "optional", "superseded"]
MissedWorkAction = Literal[
    "replace_adaptive",
    "pending_replacement",
    "retrieval_queue",
    "drop",
    "link_stronger_evidence",
]


class SchedulePolicyError(ValueError):
    """A schedule cannot satisfy the roadmap and fixed time constraints safely."""


@dataclass(frozen=True, slots=True)
class LocalStudyContext:
    local_date: date
    start_utc: datetime
    end_utc: datetime


@dataclass(frozen=True, slots=True)
class TaskTemplate:
    task_definition_id: int
    stable_id: str
    mapping_version: str
    objective: str
    block: str
    order: int
    timebox_minutes: int
    required: bool
    adaptive_priority: int | None = None

    def __post_init__(self) -> None:
        if self.task_definition_id <= 0 or self.order <= 0 or self.timebox_minutes <= 0:
            raise SchedulePolicyError("task identifiers, order, and timebox must be positive")
        if not self.stable_id or not self.mapping_version or not self.objective.strip():
            raise SchedulePolicyError("task snapshot fields cannot be blank")
        if self.required and self.adaptive_priority is not None:
            raise SchedulePolicyError("required tasks cannot be adaptive replacement slots")


@dataclass(frozen=True, slots=True)
class InterviewCommitment:
    id: int
    minutes: int

    def __post_init__(self) -> None:
        if self.id <= 0 or not 1 <= self.minutes <= 480:
            raise SchedulePolicyError("interview commitment is invalid")


@dataclass(frozen=True, slots=True)
class Carryover:
    id: int
    kind: CarryoverKind
    priority: int
    due_date: date

    def __post_init__(self) -> None:
        if self.id <= 0 or self.priority not in {1, 2}:
            raise SchedulePolicyError("carryover is invalid")


@dataclass(frozen=True, slots=True)
class UnfinishedWork:
    id: int
    classification: UnfinishedClassification
    minutes: int
    stronger_evidence_id: int | None = None

    def __post_init__(self) -> None:
        if self.id <= 0 or self.minutes <= 0:
            raise SchedulePolicyError("unfinished work is invalid")
        if (self.classification == "superseded") != (
            self.stronger_evidence_id is not None
        ):
            raise SchedulePolicyError(
                "superseded work must link exactly one stronger evidence item"
            )


@dataclass(frozen=True, slots=True)
class MissedWorkDecision:
    work_id: int
    action: MissedWorkAction
    replaced_task_id: int | None = None
    stronger_evidence_id: int | None = None


@dataclass(frozen=True, slots=True)
class DayPlan:
    local_date: date
    curriculum_day: int | None
    day_type: Literal["weekday", "saturday", "sunday", "interview"]
    tasks: tuple[TaskTemplate, ...]
    interview_minutes: int
    planned_minutes: int
    missed_work: tuple[MissedWorkDecision, ...]
    notifications: tuple[str, ...] = ()


def local_study_context(at: datetime, timezone_name: str) -> LocalStudyContext:
    """Resolve a UTC instant and variable-length local day using an IANA timezone."""
    if at.tzinfo is None or at.utcoffset() is None:
        raise SchedulePolicyError("schedule timestamp must be timezone-aware")
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        raise SchedulePolicyError("learner timezone is invalid") from None
    local_date = at.astimezone(timezone).date()
    start_local = datetime.combine(local_date, time.min, timezone)
    end_local = datetime.combine(
        local_date.fromordinal(local_date.toordinal() + 1), time.min, timezone
    )
    return LocalStudyContext(
        local_date=local_date,
        start_utc=start_local.astimezone(UTC),
        end_utc=end_local.astimezone(UTC),
    )


def curriculum_day_number(study_start_date: date, local_date: date) -> int | None:
    """Map Monday-through-Saturday dates to six roadmap days per calendar week."""
    if study_start_date.weekday() != 0:
        raise SchedulePolicyError("study start date must be a Monday roadmap anchor")
    if local_date < study_start_date:
        raise SchedulePolicyError("study date precedes the roadmap anchor")
    if local_date.weekday() == 6:
        return None
    elapsed_days = (local_date - study_start_date).days
    return (elapsed_days // 7) * 6 + local_date.weekday() + 1


def select_carryover(
    carryovers: tuple[Carryover, ...], *, local_date: date
) -> Carryover | None:
    """Select at most one due correction by due date, priority slot, and stable ID."""
    due = tuple(item for item in carryovers if item.due_date <= local_date)
    return min(due, key=lambda item: (item.due_date, item.priority, item.id), default=None)


def _replace_for_interviews(
    tasks: list[TaskTemplate], interview_minutes: int, maximum_minutes: int
) -> list[TaskTemplate]:
    if interview_minutes <= 0:
        return tasks
    blocks: list[str] = ["communication_spoken"]
    if interview_minutes > 35:
        blocks.append("tam_case")
    if interview_minutes >= 120:
        blocks.extend(("correction_warmup", "daily_close"))
    remaining = [item for item in tasks if item.block not in blocks]
    fallback_blocks = (
        "saturday_assessment",
        "correction_warmup",
        "daily_close",
        "career_pipeline",
        "technical_learning",
        "sql",
    )
    for block in fallback_blocks:
        if sum(item.timebox_minutes for item in remaining) + min(
            interview_minutes, maximum_minutes
        ) <= maximum_minutes:
            break
        remaining = [item for item in remaining if item.block != block]
    return remaining


def _resolve_unfinished(
    tasks: list[TaskTemplate],
    unfinished: tuple[UnfinishedWork, ...],
    *,
    maximum_minutes: int,
    other_minutes: int,
) -> tuple[list[TaskTemplate], list[MissedWorkDecision], int]:
    decisions: list[MissedWorkDecision] = []
    rescheduled_minutes = 0
    for work in unfinished:
        if work.classification == "useful":
            decisions.append(MissedWorkDecision(work.id, "retrieval_queue"))
            continue
        if work.classification == "optional":
            decisions.append(MissedWorkDecision(work.id, "drop"))
            continue
        if work.classification == "superseded":
            decisions.append(
                MissedWorkDecision(
                    work.id,
                    "link_stronger_evidence",
                    stronger_evidence_id=work.stronger_evidence_id,
                )
            )
            continue
        candidates = sorted(
            (
                item
                for item in tasks
                if not item.required
                and item.adaptive_priority is not None
                and item.timebox_minutes >= work.minutes
            ),
            key=lambda item: (item.adaptive_priority or 0, item.order, item.task_definition_id),
            reverse=True,
        )
        replacement = candidates[0] if candidates else None
        if replacement is None:
            decisions.append(MissedWorkDecision(work.id, "pending_replacement"))
            continue
        proposed = (
            sum(item.timebox_minutes for item in tasks)
            - replacement.timebox_minutes
            + rescheduled_minutes
            + work.minutes
            + other_minutes
        )
        if proposed > maximum_minutes:
            decisions.append(MissedWorkDecision(work.id, "pending_replacement"))
            continue
        tasks = [
            item
            for item in tasks
            if item.task_definition_id != replacement.task_definition_id
        ]
        rescheduled_minutes += work.minutes
        decisions.append(
            MissedWorkDecision(
                work.id,
                "replace_adaptive",
                replaced_task_id=replacement.task_definition_id,
            )
        )
    return tasks, decisions, rescheduled_minutes


def build_day(
    local_date: date,
    *,
    curriculum_day: int | None,
    tasks: tuple[TaskTemplate, ...],
    interviews: tuple[InterviewCommitment, ...] = (),
    unfinished: tuple[UnfinishedWork, ...] = (),
) -> DayPlan:
    """Validate and adapt one roadmap day without changing its source definitions."""
    budget = budget_for(local_date)
    if budget.day_type == "sunday":
        return DayPlan(local_date, None, "sunday", (), 0, 0, (), ())
    if curriculum_day is None or curriculum_day <= 0:
        raise SchedulePolicyError("a study day requires a positive curriculum day")
    correction_count = sum(item.block == "correction_warmup" for item in tasks)
    if correction_count > 1:
        raise SchedulePolicyError("a study day may contain only one correction warm-up")
    ordered = sorted(tasks, key=lambda item: (item.order, item.task_definition_id))
    interview_minutes = sum(item.minutes for item in interviews)
    ordered = _replace_for_interviews(
        ordered, interview_minutes, budget.maximum_minutes
    )
    counted_interview_minutes = min(interview_minutes, budget.maximum_minutes)
    ordered, decisions, rescheduled_minutes = _resolve_unfinished(
        ordered,
        unfinished,
        maximum_minutes=budget.maximum_minutes,
        other_minutes=counted_interview_minutes,
    )
    planned_minutes = (
        sum(item.timebox_minutes for item in ordered)
        + counted_interview_minutes
        + rescheduled_minutes
    )
    validate_planned_minutes(budget, planned_minutes)
    if not interviews and planned_minutes < budget.acceptable_minimum:
        raise SchedulePolicyError(
            f"weekday plan must include at least {budget.acceptable_minimum} minutes"
        )
    day_type: Literal["weekday", "saturday", "sunday", "interview"] = (
        "interview" if interviews else budget.day_type
    )
    return DayPlan(
        local_date=local_date,
        curriculum_day=curriculum_day,
        day_type=day_type,
        tasks=tuple(ordered),
        interview_minutes=interview_minutes,
        planned_minutes=planned_minutes,
        missed_work=tuple(decisions),
    )

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AssessmentContractResult(StrictModel):
    """One contract of an assessment day and how it went."""

    activity_id: int
    task_stable_id: str
    contract_type: str
    exercise_type: str | None
    activity_state: str
    result: Literal["scored", "committed", "pending", "not_attempted"]
    average_score: Decimal | None
    dimension_count: int
    review_id: int | None
    evidence_event_ids: tuple[int, ...]


class AssessmentDayResult(StrictModel):
    """An assessment day: its contracts, and the average of the ones the reviewer scored."""

    study_day_id: int
    local_date: date
    day_status: str
    planned_minutes: int
    focused_minutes: int
    contracts: tuple[AssessmentContractResult, ...]
    scored_contracts: int
    average_score: Decimal | None


class AssessmentDayPage(StrictModel):
    items: tuple[AssessmentDayResult, ...]


__all__ = ["AssessmentContractResult", "AssessmentDayPage", "AssessmentDayResult"]

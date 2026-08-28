"""Strict public contracts for activity state and focused-timer commands."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .enums import ActivityState, IncompleteClassification


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VersionedCommand(StrictModel):
    expected_version: Annotated[int, Field(gt=0)]


class HeartbeatCommand(VersionedCommand):
    client_sequence: Annotated[int, Field(gt=0)]


class IncompleteCommand(VersionedCommand):
    classification: IncompleteClassification
    stronger_evidence_id: Annotated[int | None, Field(gt=0)] = None

    @model_validator(mode="after")
    def validate_evidence_link(self) -> IncompleteCommand:
        is_superseded = self.classification is IncompleteClassification.SUPERSEDED
        if is_superseded != (self.stronger_evidence_id is not None):
            raise ValueError("superseded incomplete work requires exactly one stronger evidence ID")
        return self


class TimerResponse(StrictModel):
    id: int
    started_at: datetime
    last_heartbeat_at: datetime
    counted_seconds: int
    last_client_sequence: int


class ActivityResponse(StrictModel):
    id: int
    study_day_id: int
    state: ActivityState
    optimistic_version: int
    classification: IncompleteClassification
    stronger_evidence_id: int | None
    activity_focused_seconds: int
    day_focused_minutes: int
    hard_stop_recommended: bool
    open_timer: TimerResponse | None

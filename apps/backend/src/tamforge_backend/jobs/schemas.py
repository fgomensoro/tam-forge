"""Strict content-safe commands and read models for durable jobs."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

PositiveId = Annotated[int, Field(gt=0)]
SafeKey = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")]
JobKind = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
JobState = Literal["queued", "running", "succeeded", "failed", "canceled"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReferencePayload(StrictModel):
    schema_version: Literal[1] = 1
    subject_id: PositiveId
    related_id: PositiveId | None = None


class EnqueueJobCommand(StrictModel):
    kind: JobKind
    payload: ReferencePayload
    priority: Annotated[int, Field(ge=0, le=100)]
    available_at: datetime
    max_attempts: Annotated[int, Field(ge=1, le=100)] = 3

    @field_validator("available_at")
    @classmethod
    def aware_available_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("available_at must be timezone-aware")
        return value


class ClaimJobCommand(StrictModel):
    worker_id: SafeKey
    kinds: Annotated[tuple[JobKind, ...], Field(min_length=1, max_length=32)]
    lease_seconds: Annotated[int, Field(ge=5, le=3600)] = 120

    @field_validator("kinds")
    @classmethod
    def unique_kinds(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("job kinds must be unique")
        return value


class HeartbeatJobCommand(StrictModel):
    worker_id: SafeKey
    lease_seconds: Annotated[int, Field(ge=5, le=3600)] = 120


class JobFailure(StrictModel):
    category: Literal[
        "transient_dependency",
        "resource_exhausted",
        "invalid_input",
        "permission_required",
        "processing_failure",
        "internal_error",
    ]
    retry_after_seconds: Annotated[int | None, Field(ge=0, le=86400)] = None
    http_status: Annotated[int | None, Field(ge=100, le=599)] = None


class RetryJobCommand(StrictModel):
    worker_id: SafeKey
    failure: JobFailure


class CompleteJobCommand(StrictModel):
    worker_id: SafeKey


class JobResponse(StrictModel):
    id: PositiveId
    owner_id: PositiveId
    kind: str
    payload: ReferencePayload
    priority: int
    state: JobState
    idempotency_key: str
    available_at: datetime
    attempt_count: int
    max_attempts: int
    lease_owner: str | None
    lease_expires_at: datetime | None
    last_error_category: str | None
    last_error_details: dict[str, object] | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class EnqueueResult(StrictModel):
    job: JobResponse
    replayed: bool


class RetryResult(StrictModel):
    job: JobResponse
    disposition: Literal["retry_wait", "needs_attention"]


class ReclaimResult(StrictModel):
    retried_job_ids: tuple[PositiveId, ...]
    needs_attention_job_ids: tuple[PositiveId, ...]


__all__ = [
    "ClaimJobCommand",
    "CompleteJobCommand",
    "EnqueueJobCommand",
    "EnqueueResult",
    "HeartbeatJobCommand",
    "JobFailure",
    "JobResponse",
    "JobState",
    "ReclaimResult",
    "ReferencePayload",
    "RetryJobCommand",
    "RetryResult",
    "SafeKey",
]

"""Strict public contracts for activity state and focused-timer commands."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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


class ArtifactPresignCommand(VersionedCommand):
    artifact_class: Literal[
        "original_audio",
        "transcript",
        "written_output",
        "sql_output",
        "recall_note",
        "case_artifact",
        "analysis",
        "export",
    ]
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    byte_length: Annotated[int, Field(ge=0, le=5 * 1024 * 1024 * 1024)]
    content_type: Annotated[str, Field(min_length=3, max_length=128)]
    original_filename: Annotated[str, Field(min_length=1, max_length=512)]


class ArtifactConfirmCommand(VersionedCommand):
    upload_idempotency_key: Annotated[str, Field(min_length=1, max_length=128)]
    object_key: Annotated[str, Field(min_length=1, max_length=1024)]


class ArtifactReference(StrictModel):
    artifact_id: Annotated[int, Field(gt=0)]
    link_role: Literal[
        "original_output",
        "presentation_audio",
        "transcript",
        "analysis",
        "supporting",
        "correction",
    ]


class CommitOutputCommand(VersionedCommand):
    client_sequence: Annotated[int, Field(gt=0)]
    output: dict[str, Any]
    artifact_refs: Annotated[tuple[ArtifactReference, ...], Field(max_length=32)] = ()
    parent_attempt_id: Annotated[int | None, Field(gt=0)] = None


class SelfReviewCommand(VersionedCommand):
    main_answer: Annotated[str, Field(min_length=1, max_length=8192)]
    did_well: Annotated[str, Field(min_length=1, max_length=8192)]
    structure_weakness: Annotated[str, Field(min_length=1, max_length=8192)]
    vague_points: Annotated[str, Field(min_length=1, max_length=8192)]
    hesitation_points: Annotated[str, Field(min_length=1, max_length=8192)]
    change_next: Annotated[str, Field(min_length=1, max_length=8192)]
    self_score: Annotated[int, Field(ge=0, le=4)]

    @field_validator(
        "main_answer",
        "did_well",
        "structure_weakness",
        "vague_points",
        "hesitation_points",
        "change_next",
    )
    @classmethod
    def reject_blank_answers(cls, value: str) -> str:
        if not value.strip() or len(value.encode("utf-8")) > 8192:
            raise ValueError("self-review answers must be non-blank")
        return value


class SourceVisibilityCommand(VersionedCommand):
    hidden: bool


class TimerResponse(StrictModel):
    id: int
    started_at: datetime
    last_heartbeat_at: datetime
    counted_seconds: int
    last_client_sequence: int


class PresignedUploadResponse(StrictModel):
    url: str
    method: Literal["PUT"]
    headers: dict[str, str]
    expires_seconds: int


class ArtifactPresignResponse(StrictModel):
    artifact_id: int | None = None
    object_key: str
    reused: bool
    upload: PresignedUploadResponse | None


class ArtifactResponse(StrictModel):
    id: int
    sha256: str
    byte_length: int
    content_type: str
    original_filename: str
    artifact_class: str


class OutputCommitResponse(StrictModel):
    activity_id: int
    state: ActivityState
    optimistic_version: int
    attempt_id: int
    commitment_sha256: str
    artifact_ids: tuple[int, ...]


class SelfReviewResponse(StrictModel):
    activity_id: int
    state: ActivityState
    optimistic_version: int
    self_review_id: int
    attempt_id: int
    self_score: int


class CommittedOutputSummary(StrictModel):
    attempt_id: int
    attempt_kind: str
    commitment_sha256: str
    contract_payload: dict[str, Any]
    artifact_ids: tuple[int, ...]
    committed_at: datetime


class SelfReviewSummary(StrictModel):
    id: int
    attempt_id: int
    self_score: int
    main_answer: str
    did_well: str
    structure_weakness: str
    vague_points: str
    hesitation_points: str
    change_next: str
    submitted_at: datetime


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
    source_hidden: bool = False


class ActivityDetailResponse(ActivityResponse):
    committed_output: CommittedOutputSummary | None = None
    self_review: SelfReviewSummary | None = None

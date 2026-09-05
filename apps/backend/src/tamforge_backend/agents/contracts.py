"""Closed, redacted persistence commands. No execution or publication authority."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from tamforge_protocol.agents import AttemptTextReference, Hash, PositiveId

Key = Annotated[str, StringConstraints(strict=True, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")]
Count = Annotated[int, Field(strict=True, ge=0, le=2147483647)]
State = Literal["registered", "running", "succeeded", "failed", "cancelled"]
Failure = Literal[
    "invalid_input",
    "permission_required",
    "transient_dependency",
    "resource_exhausted",
    "processing_failure",
    "internal_error",
    "cancelled",
]


class ProvenanceError(ValueError):
    """Safe base exception; never includes submitted content or DB diagnostics."""


class InvalidProvenance(ProvenanceError):
    def __init__(self) -> None:
        super().__init__("invalid model provenance")


class ImmutableVersionConflict(ProvenanceError):
    def __init__(self) -> None:
        super().__init__("immutable provenance conflict")


class ProvenanceNotFound(ProvenanceError):
    def __init__(self) -> None:
        super().__init__("model provenance not found")


class StateConflict(ProvenanceError):
    def __init__(self) -> None:
        super().__init__("model provenance state conflict")


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Publication(Contract):
    owner_id: PositiveId
    key: Key
    version: Key


class PinnedVersion(Contract):
    id: PositiveId
    content_hash: Hash


class ContextInput(Contract):
    ordinal: Annotated[int, Field(strict=True, ge=0, le=63)]
    reason: Literal["primary_evidence", "supporting_evidence", "comparison"]
    reference: AttemptTextReference
    prepared_input_hash: Hash


class RunRequest(Contract):
    owner_id: PositiveId
    invocation_key: Key
    activity_id: PositiveId
    attempt: PinnedVersion
    prompt: PinnedVersion
    schema_version: PinnedVersion
    rubric_binding: PinnedVersion
    requested_model: Key
    sdk_version: Key | None = None
    cli_version: Key | None = None
    job_id: PositiveId | None = None
    predecessor: PinnedVersion | None = None
    context: Annotated[tuple[ContextInput, ...], Field(min_length=1, max_length=64)]

    @model_validator(mode="after")
    def ordered_manifest(self) -> Self:
        if tuple(item.ordinal for item in self.context) != tuple(range(len(self.context))):
            raise InvalidProvenance()
        if len({item.reference for item in self.context}) != len(self.context):
            raise InvalidProvenance()
        if any(
            item.reference.attempt_id != self.attempt.id
            or item.reference.commitment_sha256 != self.attempt.content_hash
            for item in self.context
        ):
            raise InvalidProvenance()
        return self


class Lifecycle(Contract):
    state: Literal["running", "succeeded", "failed", "cancelled"]
    elapsed_ms: Count
    resolved_model: Key | None = None
    sdk_version: Key | None = None
    cli_version: Key | None = None
    output_hash: Hash | None = None
    error_category: Failure | None = None
    retry_disposition: Literal["none", "retryable", "exhausted"] = "none"

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.state == "running":
            if self.resolved_model is None or (
                self.sdk_version is None and self.cli_version is None
            ):
                raise InvalidProvenance()
        elif any(
            value is not None for value in (self.resolved_model, self.sdk_version, self.cli_version)
        ):
            raise InvalidProvenance()
        if (self.state in ("failed", "cancelled")) != (self.error_category is not None):
            raise InvalidProvenance()
        if self.state != "succeeded" and self.output_hash is not None:
            raise InvalidProvenance()
        if self.state != "failed" and self.retry_disposition != "none":
            raise InvalidProvenance()
        return self


def validate_transition(previous: str, event: Lifecycle) -> None:
    allowed = {
        "registered": {"running", "failed", "cancelled"},
        "running": {"succeeded", "failed", "cancelled"},
    }
    if event.state not in allowed.get(previous, set()):
        raise StateConflict()


class ToolAudit(Contract):
    call_key: Key
    phase: Literal["request", "succeeded", "failed", "cancelled"]
    tool_name: Key
    tool_version: Key
    schema_hash: Hash
    elapsed_ms: Count
    context_ordinals: Annotated[
        tuple[Annotated[int, Field(strict=True, ge=0, le=63)], ...], Field(max_length=64)
    ] = ()
    item_count: Count | None = None
    error_category: Failure | None = None

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if len(set(self.context_ordinals)) != len(self.context_ordinals):
            raise InvalidProvenance()
        if (self.phase in ("failed", "cancelled")) != (self.error_category is not None):
            raise InvalidProvenance()
        return self

"""Minimal forward-compatible Today, correction, interview, and processing models."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    and_,
    event,
    func,
    inspect,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Mapped, Mapper, mapped_column
from sqlalchemy.orm.base import LoaderCallableStatus

from ..evidence.models import SkillEvidenceEvent
from ..learning.models import ActivityInstance, Attempt
from ..models.base import Base, utc_now
from ..notifications.models import ERROR_CATEGORIES, validate_error_details_v1


class CorrectionWorkflowError(ValueError):
    """Raised when correction history or its Attempt B lifecycle is invalid."""


class ProcessingWorkflowError(ValueError):
    """Raised when asynchronous activity processing enters an invalid state."""


CORRECTION_STATES = {"pending", "scheduled", "completed", "dismissed", "superseded"}
CORRECTION_TRANSITIONS = {
    "pending": frozenset({"scheduled", "dismissed", "superseded"}),
    "scheduled": frozenset({"completed", "dismissed", "superseded"}),
    "completed": frozenset(),
    "dismissed": frozenset(),
    "superseded": frozenset(),
}
INTERVIEW_STATES = {"scheduled", "completed", "cancelled", "rescheduled"}
PRIVACY_PERMISSION_CODES = {
    "permission_not_requested",
    "permission_granted",
    "permission_denied",
    "recording_prohibited",
}
PROCESSING_STATES = {
    "uploaded",
    "processing_audio",
    "transcribing",
    "analyzing",
    "ready",
    "needs_attention",
}
PROCESSING_TRANSITIONS = {
    "uploaded": frozenset({"processing_audio", "needs_attention"}),
    "processing_audio": frozenset({"transcribing", "needs_attention"}),
    "transcribing": frozenset({"analyzing", "needs_attention"}),
    "analyzing": frozenset({"ready", "needs_attention"}),
    "ready": frozenset({"analyzing"}),
    "needs_attention": frozenset({"processing_audio", "transcribing", "analyzing"}),
}
PROGRESS_LABEL_BY_STATE = {
    "uploaded": "uploaded",
    "processing_audio": "processing_audio",
    "transcribing": "transcribing",
    "analyzing": "analyzing",
    "ready": "ready",
    "needs_attention": "action_required",
}


class Correction(Base):
    """One compact correction sourced from immutable independent evidence."""

    __tablename__ = "corrections"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "source_activity_id"],
            ["activity_instances.owner_id", "activity_instances.id"],
            name="fk_corrections_owner_source_activity_activity_instances",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["owner_id", "source_evidence_event_id"],
            ["skill_evidence_events.owner_id", "skill_evidence_events.id"],
            name="fk_corrections_owner_source_evidence_skill_evidence_events",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["owner_id", "attempt_b_activity_id"],
            ["activity_instances.owner_id", "activity_instances.id"],
            name="fk_corrections_owner_attempt_b_activity_instances",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("owner_id", "id", name="uq_corrections_owner_id_id"),
        CheckConstraint("priority BETWEEN 1 AND 2", name="priority_slot_allowed"),
        CheckConstraint(
            "status IN ('pending', 'scheduled', 'completed', 'dismissed', 'superseded')",
            name="status_allowed",
        ),
        CheckConstraint(
            "btrim(instruction) <> '' AND octet_length(instruction) <= 1024",
            name="instruction_compact",
        ),
        CheckConstraint(
            "attempt_b_activity_id IS NULL OR attempt_b_activity_id <> source_activity_id",
            name="attempt_b_not_source",
        ),
        CheckConstraint(
            "(status = 'pending' AND attempt_b_activity_id IS NULL AND completed_at IS NULL) OR "
            "(status = 'scheduled' AND attempt_b_activity_id IS NOT NULL "
            "AND completed_at IS NULL) OR "
            "(status = 'completed' AND attempt_b_activity_id IS NOT NULL "
            "AND completed_at IS NOT NULL) OR "
            "(status IN ('dismissed', 'superseded') AND completed_at IS NOT NULL)",
            name="lifecycle_coherent",
        ),
        CheckConstraint(
            "updated_at >= created_at AND (completed_at IS NULL OR completed_at >= created_at)",
            name="timestamps_coherent",
        ),
        Index(
            "ix_corrections_owner_due_status_priority",
            "owner_id",
            "due_date",
            "status",
            "priority",
        ),
        Index("ix_corrections_owner_source_activity", "owner_id", "source_activity_id"),
        Index(
            "ix_corrections_owner_source_evidence", "owner_id", "source_evidence_event_id"
        ),
        Index("ix_corrections_owner_attempt_b", "owner_id", "attempt_b_activity_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_activity_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_evidence_event_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    instruction: Mapped[str] = mapped_column(Text, nullable=False)
    attempt_b_activity_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Interview(Base):
    """Today-only real interview schedule and closed permission classification."""

    __tablename__ = "interviews"
    __table_args__ = (
        UniqueConstraint("owner_id", "id", name="uq_interviews_owner_id_id"),
        CheckConstraint(
            "btrim(company) <> '' AND octet_length(company) <= 256 "
            "AND btrim(role) <> '' AND octet_length(role) <= 256 "
            "AND btrim(stage) <> '' AND octet_length(stage) <= 128",
            name="identity_fields_bounded",
        ),
        CheckConstraint(
            "expected_duration_minutes BETWEEN 1 AND 480",
            name="expected_duration_bounded",
        ),
        CheckConstraint(
            "status IN ('scheduled', 'completed', 'cancelled', 'rescheduled')",
            name="status_allowed",
        ),
        CheckConstraint(
            "privacy_permission_code IN ('permission_not_requested', "
            "'permission_granted', 'permission_denied', 'recording_prohibited')",
            name="privacy_permission_allowed",
        ),
        CheckConstraint("updated_at >= created_at", name="timestamps_monotonic"),
        Index("ix_interviews_owner_starts_at", "owner_id", "starts_at", "id"),
        Index("ix_interviews_owner_status_starts", "owner_id", "status", "starts_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("owners.id", name="fk_interviews_owner_id_owners", ondelete="RESTRICT"),
        nullable=False,
    )
    company: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    stage: Mapped[str] = mapped_column(Text, nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expected_duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    privacy_permission_code: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )


class ActivityProcessingStatus(Base):
    """Current asynchronous status for one activity without diagnostic free text."""

    __tablename__ = "activity_processing_statuses"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "activity_instance_id"],
            ["activity_instances.owner_id", "activity_instances.id"],
            name="fk_processing_status_owner_activity_activity_instances",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "owner_id", "activity_instance_id", name="uq_processing_status_owner_activity"
        ),
        CheckConstraint(
            "state IN ('uploaded', 'processing_audio', 'transcribing', 'analyzing', "
            "'ready', 'needs_attention')",
            name="state_allowed",
        ),
        CheckConstraint(
            "progress_label IN ('uploaded', 'processing_audio', 'transcribing', "
            "'analyzing', 'ready', 'action_required')",
            name="progress_label_allowed",
        ),
        CheckConstraint(
            "(state = 'uploaded' AND progress_label = 'uploaded') OR "
            "(state = 'processing_audio' AND progress_label = 'processing_audio') OR "
            "(state = 'transcribing' AND progress_label = 'transcribing') OR "
            "(state = 'analyzing' AND progress_label = 'analyzing') OR "
            "(state = 'ready' AND progress_label = 'ready') OR "
            "(state = 'needs_attention' AND progress_label = 'action_required')",
            name="state_progress_coherent",
        ),
        CheckConstraint(
            "last_error_category IS NULL OR last_error_category IN "
            "('transient_dependency', 'resource_exhausted', 'invalid_input', "
            "'permission_required', 'processing_failure', 'internal_error')",
            name="error_category_allowed",
        ),
        CheckConstraint(
            "(state = 'needs_attention' AND last_error_category IS NOT NULL "
            "AND last_error_details IS NOT NULL "
            "AND public.tamforge_validate_error_details_v1(last_error_details)) OR "
            "(state <> 'needs_attention' AND last_error_category IS NULL "
            "AND last_error_details IS NULL)",
            name="error_details_coherent",
        ),
        CheckConstraint("updated_at >= created_at", name="timestamps_monotonic"),
        Index(
            "ix_processing_status_owner_state_updated",
            "owner_id",
            "state",
            "updated_at",
        ),
        Index(
            "ix_processing_status_owner_activity",
            "owner_id",
            "activity_instance_id",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    activity_instance_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    progress_label: Mapped[str] = mapped_column(Text, nullable=False)
    last_error_category: Mapped[str | None] = mapped_column(Text)
    last_error_details: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )


def _is_persisted_change(target: object, value: object, old_value: object) -> bool:
    state = inspect(target, raiseerr=True)
    assert state is not None
    return (
        (state.persistent or state.detached)
        and old_value not in (LoaderCallableStatus.NO_VALUE, LoaderCallableStatus.NEVER_SET)
        and value != old_value
    )


_CORRECTION_PROVENANCE_ATTRIBUTES = (
    "owner_id",
    "source_activity_id",
    "source_evidence_event_id",
    "priority",
    "due_date",
    "instruction",
    "created_at",
)


def _reject_correction_provenance_change(
    target: Correction,
    value: object,
    old_value: object,
    initiator: object,
) -> object:
    del initiator
    if _is_persisted_change(target, value, old_value):
        raise CorrectionWorkflowError("correction provenance is immutable")
    return value


for _attribute_name in _CORRECTION_PROVENANCE_ATTRIBUTES:
    event.listen(
        getattr(Correction, _attribute_name),
        "set",
        _reject_correction_provenance_change,
        retval=True,
        active_history=True,
    )


def _validate_correction_status_change(
    target: Correction,
    value: str,
    old_value: str | LoaderCallableStatus,
    initiator: object,
) -> str:
    del initiator
    if value not in CORRECTION_STATES:
        raise CorrectionWorkflowError("invalid correction status")
    if _is_persisted_change(target, value, old_value):
        assert isinstance(old_value, str)
        if value not in CORRECTION_TRANSITIONS[old_value]:
            raise CorrectionWorkflowError("invalid correction status transition")
    return value


event.listen(
    Correction.status,
    "set",
    _validate_correction_status_change,
    retval=True,
    active_history=True,
)


def _write_once_correction_completion(
    target: Correction,
    value: datetime | None,
    old_value: datetime | None | LoaderCallableStatus,
    initiator: object,
) -> datetime | None:
    del initiator
    if _is_persisted_change(target, value, old_value) and old_value is not None:
        raise CorrectionWorkflowError("correction completion timestamp is write-once")
    return value


event.listen(
    Correction.completed_at,
    "set",
    _write_once_correction_completion,
    retval=True,
    active_history=True,
)


def _write_once_correction_attempt_b(
    target: Correction,
    value: int | None,
    old_value: int | None | LoaderCallableStatus,
    initiator: object,
) -> int | None:
    del initiator
    if _is_persisted_change(target, value, old_value) and old_value is not None:
        raise CorrectionWorkflowError("correction Attempt B link is write-once")
    return value


event.listen(
    Correction.attempt_b_activity_id,
    "set",
    _write_once_correction_attempt_b,
    retval=True,
    active_history=True,
)


def _validate_correction_updated_at(
    target: Correction,
    value: datetime,
    old_value: datetime | LoaderCallableStatus,
    initiator: object,
) -> datetime:
    del initiator
    if _is_persisted_change(target, value, old_value):
        assert isinstance(old_value, datetime)
        if value < old_value:
            raise CorrectionWorkflowError("correction updated_at must be monotonic")
    return value


event.listen(
    Correction.updated_at,
    "set",
    _validate_correction_updated_at,
    retval=True,
    active_history=True,
)


def validate_correction(
    mapper: Mapper[Correction] | None,
    connection: Connection | None,
    target: Correction,
) -> None:
    del mapper
    if target.source_evidence_event_id is None:
        raise CorrectionWorkflowError("correction source evidence is required")
    if target.status == "pending" and (
        target.attempt_b_activity_id is not None or target.completed_at is not None
    ):
        raise CorrectionWorkflowError("pending correction lifecycle is incoherent")
    if target.status == "scheduled" and (
        target.attempt_b_activity_id is None or target.completed_at is not None
    ):
        raise CorrectionWorkflowError("scheduled correction lifecycle is incoherent")
    if target.status == "completed" and (
        target.attempt_b_activity_id is None or target.completed_at is None
    ):
        raise CorrectionWorkflowError("completed correction lifecycle is incoherent")
    if target.status in {"dismissed", "superseded"} and target.completed_at is None:
        raise CorrectionWorkflowError("closed correction lifecycle is incoherent")
    if target.updated_at < target.created_at or (
        target.completed_at is not None and target.completed_at < target.created_at
    ):
        raise CorrectionWorkflowError("correction timestamps are incoherent")
    if connection is not None:
        evidence = SkillEvidenceEvent.__table__
        attempt = Attempt.__table__
        source_row = connection.execute(
            select(
                evidence.c.activity_instance_id,
                evidence.c.attempt_id,
                attempt.c.attempt_kind,
            )
            .select_from(
                evidence.join(
                    attempt,
                    and_(
                        attempt.c.owner_id == evidence.c.owner_id,
                        attempt.c.activity_instance_id == evidence.c.activity_instance_id,
                        attempt.c.id == evidence.c.attempt_id,
                    ),
                )
            )
            .where(
                evidence.c.owner_id == target.owner_id,
                evidence.c.id == target.source_evidence_event_id,
            )
        ).one_or_none()
        if source_row is None or source_row[0] != target.source_activity_id:
            raise CorrectionWorkflowError(
                "correction source evidence must belong to its source activity"
            )
        source_attempt_id = source_row[1]
        if source_attempt_id is None or source_row[2] != "attempt_a":
            raise CorrectionWorkflowError(
                "correction source evidence must resolve to a committed Attempt A"
            )
    else:
        source_attempt_id = None
    if connection is not None and target.attempt_b_activity_id is not None:
        attempt_kind = connection.execute(
            select(ActivityInstance.__table__.c.attempt_kind).where(
                ActivityInstance.__table__.c.owner_id == target.owner_id,
                ActivityInstance.__table__.c.id == target.attempt_b_activity_id,
            )
        ).scalar_one_or_none()
        if attempt_kind != "attempt_b":
            raise CorrectionWorkflowError("correction target must be an Attempt B activity")
        if target.status == "completed":
            committed_attempt_b_id = connection.execute(
                select(Attempt.__table__.c.id).where(
                    Attempt.__table__.c.owner_id == target.owner_id,
                    Attempt.__table__.c.activity_instance_id == target.attempt_b_activity_id,
                    Attempt.__table__.c.attempt_kind == "attempt_b",
                    Attempt.__table__.c.parent_attempt_id == source_attempt_id,
                )
            ).scalar_one_or_none()
            if committed_attempt_b_id is None:
                raise CorrectionWorkflowError(
                    "completed correction requires an Attempt B whose parent Attempt A "
                    "matches the source evidence"
                )


event.listen(Correction, "before_insert", validate_correction)
event.listen(Correction, "before_update", validate_correction)


_PROCESSING_PROVENANCE_ATTRIBUTES = ("owner_id", "activity_instance_id", "created_at")


def _reject_processing_provenance_change(
    target: ActivityProcessingStatus,
    value: object,
    old_value: object,
    initiator: object,
) -> object:
    del initiator
    if _is_persisted_change(target, value, old_value):
        raise ProcessingWorkflowError("processing status provenance is immutable")
    return value


for _attribute_name in _PROCESSING_PROVENANCE_ATTRIBUTES:
    event.listen(
        getattr(ActivityProcessingStatus, _attribute_name),
        "set",
        _reject_processing_provenance_change,
        retval=True,
        active_history=True,
    )


def _validate_processing_state_change(
    target: ActivityProcessingStatus,
    value: str,
    old_value: str | LoaderCallableStatus,
    initiator: object,
) -> str:
    del initiator
    if value not in PROCESSING_STATES:
        raise ProcessingWorkflowError("invalid processing state")
    if _is_persisted_change(target, value, old_value):
        assert isinstance(old_value, str)
        if value not in PROCESSING_TRANSITIONS[old_value]:
            raise ProcessingWorkflowError("invalid processing state transition")
    return value


event.listen(
    ActivityProcessingStatus.state,
    "set",
    _validate_processing_state_change,
    retval=True,
    active_history=True,
)


def _validate_processing_updated_at(
    target: ActivityProcessingStatus,
    value: datetime,
    old_value: datetime | LoaderCallableStatus,
    initiator: object,
) -> datetime:
    del initiator
    if _is_persisted_change(target, value, old_value):
        assert isinstance(old_value, datetime)
        if value < old_value:
            raise ProcessingWorkflowError("processing updated_at must be monotonic")
    return value


event.listen(
    ActivityProcessingStatus.updated_at,
    "set",
    _validate_processing_updated_at,
    retval=True,
    active_history=True,
)


def _processing_state_is_changing(target: ActivityProcessingStatus) -> bool:
    history = inspect(target).attrs.state.history
    return history.has_changes() and bool(history.deleted)


def _reject_same_state_processing_error_change(
    target: ActivityProcessingStatus,
    value: object,
    old_value: object,
    initiator: object,
) -> object:
    del initiator
    if (
        _is_persisted_change(target, value, old_value)
        and not _processing_state_is_changing(target)
    ):
        raise ProcessingWorkflowError("same-state processing error details are immutable")
    return value


for _attribute_name in ("last_error_category", "last_error_details"):
    event.listen(
        getattr(ActivityProcessingStatus, _attribute_name),
        "set",
        _reject_same_state_processing_error_change,
        retval=True,
        active_history=True,
    )


def validate_processing_status(
    mapper: Mapper[ActivityProcessingStatus] | None,
    connection: Connection | None,
    target: ActivityProcessingStatus,
) -> None:
    del mapper, connection
    if target.state not in PROCESSING_STATES:
        raise ProcessingWorkflowError("invalid processing state")
    if target.progress_label != PROGRESS_LABEL_BY_STATE[target.state]:
        raise ProcessingWorkflowError("processing progress label does not match state")
    if target.updated_at < target.created_at:
        raise ProcessingWorkflowError("processing timestamps are not monotonic")
    if target.state == "needs_attention":
        if (
            target.last_error_category not in ERROR_CATEGORIES
            or not validate_error_details_v1(target.last_error_details)
        ):
            raise ProcessingWorkflowError("processing error details are invalid")
    elif target.last_error_category is not None or target.last_error_details is not None:
        raise ProcessingWorkflowError("non-error processing state cannot retain an error")


event.listen(ActivityProcessingStatus, "before_insert", validate_processing_status)
event.listen(ActivityProcessingStatus, "before_update", validate_processing_status)


__all__ = [
    "CORRECTION_STATES",
    "INTERVIEW_STATES",
    "PRIVACY_PERMISSION_CODES",
    "PROCESSING_STATES",
    "ActivityProcessingStatus",
    "Correction",
    "CorrectionWorkflowError",
    "Interview",
    "ProcessingWorkflowError",
    "validate_correction",
    "validate_processing_status",
]

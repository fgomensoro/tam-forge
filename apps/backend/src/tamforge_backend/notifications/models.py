"""Durable notifications, transactional outbox, jobs, and SSE cursor state."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    event,
    func,
    inspect,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Mapped, Mapper, mapped_column
from sqlalchemy.orm.base import LoaderCallableStatus

from ..models.base import Base, utc_now


class NotificationContractError(ValueError):
    """Raised when a notification or structured operational payload is invalid."""


class OutboxWorkflowError(ValueError):
    """Raised when an outbox mutation would lose or rewrite delivery history."""


class JobWorkflowError(ValueError):
    """Raised when a background-job mutation violates its durable state machine."""


class DeliveryCursorWorkflowError(ValueError):
    """Raised when a resumable delivery cursor moves backwards."""


NOTIFICATION_TYPES = {
    "feedback_ready",
    "correction_due",
    "upcoming_real_interview",
    "saturday_assessment",
    "processing_failure_requires_action",
}
SUBJECT_KINDS = {
    "activity",
    "correction",
    "interview",
    "study_day",
    "processing_status",
}
AGGREGATE_TYPES = SUBJECT_KINDS | {"roadmap", "notification", "background_job"}
ERROR_CATEGORIES = {
    "transient_dependency",
    "resource_exhausted",
    "invalid_input",
    "permission_required",
    "processing_failure",
    "internal_error",
}
JOB_STATES = {"queued", "running", "succeeded", "failed", "canceled"}
JOB_TRANSITIONS = {
    "queued": frozenset({"running", "canceled"}),
    "running": frozenset({"queued", "succeeded", "failed", "canceled"}),
    "succeeded": frozenset(),
    "failed": frozenset(),
    "canceled": frozenset(),
}


def _json_size(value: object) -> int:
    try:
        return len(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode())
    except (TypeError, ValueError):
        return 1 << 30


def _positive_id(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 < value <= 2**63 - 1


def _bounded_int(value: object, minimum: int, maximum: int) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and minimum <= value <= maximum
    )


def validate_reference_payload_v1(value: object) -> bool:
    """Validate the only v1 outbox/job payload: IDs and no free-form strings."""
    if not isinstance(value, dict) or _json_size(value) > 1024:
        return False
    if set(value) - {"schema_version", "subject_id", "related_id"}:
        return False
    return (
        value.get("schema_version") == 1
        and _positive_id(value.get("subject_id"))
        and ("related_id" not in value or _positive_id(value["related_id"]))
    )


def validate_error_details_v1(value: object) -> bool:
    """Validate bounded numeric diagnostics without excerpts, URLs, or secrets."""
    if not isinstance(value, dict) or _json_size(value) > 512:
        return False
    if set(value) - {
        "schema_version",
        "attempt",
        "retry_after_seconds",
        "http_status",
    }:
        return False
    if value.get("schema_version") != 1:
        return False
    return (
        ("attempt" not in value or _bounded_int(value["attempt"], 0, 100))
        and (
            "retry_after_seconds" not in value
            or _bounded_int(value["retry_after_seconds"], 0, 86400)
        )
        and (
            "http_status" not in value
            or _bounded_int(value["http_status"], 100, 599)
        )
    )


class Notification(Base):
    """One approved, actionable in-app notification without arbitrary copy."""

    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("owner_id", "id", name="uq_notifications_owner_id_id"),
        CheckConstraint(
            "notification_type IN ('feedback_ready', 'correction_due', "
            "'upcoming_real_interview', 'saturday_assessment', "
            "'processing_failure_requires_action')",
            name="notification_type_allowed",
        ),
        CheckConstraint(
            "subject_kind IN ('activity', 'correction', 'interview', 'study_day', "
            "'processing_status')",
            name="subject_kind_allowed",
        ),
        CheckConstraint("subject_id > 0", name="subject_id_positive"),
        CheckConstraint("read_at IS NULL OR read_at >= created_at", name="read_after_creation"),
        Index("ix_notifications_owner_created", "owner_id", "created_at", "id"),
        Index(
            "ix_notifications_owner_unread_created",
            "owner_id",
            "created_at",
            "id",
            postgresql_where=text("read_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("owners.id", name="fk_notifications_owner_id_owners", ondelete="RESTRICT"),
        nullable=False,
    )
    notification_type: Mapped[str] = mapped_column(Text, nullable=False)
    subject_kind: Mapped[str] = mapped_column(Text, nullable=False)
    subject_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OutboxEvent(Base):
    """Owner-scoped transactional event with bounded reference-only payload."""

    __tablename__ = "outbox_events"
    __table_args__ = (
        UniqueConstraint("owner_id", "id", name="uq_outbox_events_owner_id_id"),
        UniqueConstraint(
            "owner_id", "idempotency_key", name="uq_outbox_events_owner_idempotency"
        ),
        CheckConstraint(
            "aggregate_type IN ('activity', 'correction', 'interview', 'study_day', "
            "'processing_status', 'roadmap', 'notification', 'background_job')",
            name="aggregate_type_allowed",
        ),
        CheckConstraint("aggregate_id > 0", name="aggregate_id_positive"),
        CheckConstraint(
            "event_type ~ '^[a-z][a-z0-9_]{0,31}(\\.[a-z][a-z0-9_]{0,31}){1,3}$' "
            "AND octet_length(event_type) <= 128",
            name="event_type_safe",
        ),
        CheckConstraint("payload_schema_version = 1", name="payload_version_supported"),
        CheckConstraint(
            "public.tamforge_validate_reference_payload_v1(payload)",
            name="payload_valid",
        ),
        CheckConstraint(
            "payload->>'schema_version' = payload_schema_version::text",
            name="payload_version_coherent",
        ),
        CheckConstraint("attempts BETWEEN 0 AND 100", name="attempts_bounded"),
        CheckConstraint(
            "published_at IS NULL OR (published_at >= occurred_at AND attempts > 0)",
            name="publication_coherent",
        ),
        CheckConstraint(
            "idempotency_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'",
            name="idempotency_key_safe",
        ),
        Index(
            "ix_outbox_events_unpublished_occurred",
            "occurred_at",
            "id",
            postgresql_where=text("published_at IS NULL"),
        ),
        Index("ix_outbox_events_owner_occurred", "owner_id", "occurred_at", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("owners.id", name="fk_outbox_events_owner_id_owners", ondelete="RESTRICT"),
        nullable=False,
    )
    aggregate_type: Mapped[str] = mapped_column(Text, nullable=False)
    aggregate_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    payload_schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)


class BackgroundJob(Base):
    """A leased, retryable PostgreSQL job with typed non-sensitive failure data."""

    __tablename__ = "background_jobs"
    __table_args__ = (
        UniqueConstraint("owner_id", "id", name="uq_background_jobs_owner_id_id"),
        UniqueConstraint(
            "owner_id", "idempotency_key", name="uq_background_jobs_owner_idempotency"
        ),
        CheckConstraint(
            "kind ~ '^[a-z][a-z0-9_]{0,63}$'", name="kind_safe"
        ),
        CheckConstraint("payload_schema_version = 1", name="payload_version_supported"),
        CheckConstraint(
            "public.tamforge_validate_reference_payload_v1(payload)",
            name="payload_valid",
        ),
        CheckConstraint(
            "payload->>'schema_version' = payload_schema_version::text",
            name="payload_version_coherent",
        ),
        CheckConstraint("priority BETWEEN 0 AND 100", name="priority_bounded"),
        CheckConstraint(
            "state IN ('queued', 'running', 'succeeded', 'failed', 'canceled')",
            name="state_allowed",
        ),
        CheckConstraint(
            "idempotency_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'",
            name="idempotency_key_safe",
        ),
        CheckConstraint(
            "attempt_count BETWEEN 0 AND max_attempts AND max_attempts BETWEEN 1 AND 100",
            name="attempts_coherent",
        ),
        CheckConstraint(
            "lease_owner IS NULL OR (lease_owner ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$')",
            name="lease_owner_safe",
        ),
        CheckConstraint(
            "last_error_category IS NULL OR last_error_category IN "
            "('transient_dependency', 'resource_exhausted', 'invalid_input', "
            "'permission_required', 'processing_failure', 'internal_error')",
            name="error_category_allowed",
        ),
        CheckConstraint(
            "(last_error_category IS NULL AND last_error_details IS NULL) OR "
            "(last_error_category IS NOT NULL AND last_error_details IS NOT NULL "
            "AND public.tamforge_validate_error_details_v1(last_error_details))",
            name="error_details_coherent",
        ),
        CheckConstraint(
            "(state = 'queued' AND lease_owner IS NULL AND lease_expires_at IS NULL "
            "AND completed_at IS NULL) OR "
            "(state = 'running' AND attempt_count > 0 AND lease_owner IS NOT NULL "
            "AND lease_expires_at IS NOT NULL AND started_at IS NOT NULL "
            "AND completed_at IS NULL) OR "
            "(state IN ('succeeded', 'failed') AND attempt_count > 0 "
            "AND lease_owner IS NULL AND lease_expires_at IS NULL "
            "AND started_at IS NOT NULL AND completed_at IS NOT NULL) OR "
            "(state = 'canceled' AND lease_owner IS NULL "
            "AND lease_expires_at IS NULL AND completed_at IS NOT NULL)",
            name="lifecycle_coherent",
        ),
        CheckConstraint(
            "(attempt_count = 0 AND started_at IS NULL) OR "
            "(attempt_count > 0 AND started_at IS NOT NULL)",
            name="started_attempt_coherent",
        ),
        CheckConstraint(
            "updated_at >= created_at AND (started_at IS NULL OR started_at >= created_at) "
            "AND (completed_at IS NULL OR completed_at >= started_at) "
            "AND (lease_expires_at IS NULL OR lease_expires_at > updated_at)",
            name="timestamps_coherent",
        ),
        CheckConstraint(
            "state <> 'succeeded' OR last_error_category IS NULL",
            name="success_without_error",
        ),
        CheckConstraint(
            "state <> 'failed' OR last_error_category IS NOT NULL",
            name="failure_has_error",
        ),
        CheckConstraint(
            "state <> 'canceled' OR last_error_category IS NULL",
            name="cancellation_without_error",
        ),
        Index(
            "ix_background_jobs_claimable",
            "priority",
            "available_at",
            "id",
            postgresql_where=text("state = 'queued'"),
        ),
        Index("ix_background_jobs_owner_state", "owner_id", "state", "updated_at"),
        Index(
            "ix_background_jobs_expired_lease",
            "lease_expires_at",
            "id",
            postgresql_where=text("state = 'running'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("owners.id", name="fk_background_jobs_owner_id_owners", ondelete="RESTRICT"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    payload_schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempt_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(Text)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NotificationDeliveryCursor(Base):
    """Monotonic owner/stream cursor used to resume ordered SSE delivery."""

    __tablename__ = "notification_delivery_cursor"
    __table_args__ = (
        UniqueConstraint(
            "owner_id", "stream_key", name="uq_notification_cursor_owner_stream"
        ),
        CheckConstraint(
            "stream_key ~ '^[a-z][a-z0-9_]{0,31}$'", name="stream_key_safe"
        ),
        CheckConstraint("last_event_id >= 0", name="last_event_id_nonnegative"),
        CheckConstraint("updated_at >= created_at", name="timestamps_monotonic"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "owners.id", name="fk_notification_cursor_owner_id_owners", ondelete="RESTRICT"
        ),
        nullable=False,
    )
    stream_key: Mapped[str] = mapped_column(Text, nullable=False)
    last_event_id: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default="0", nullable=False
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


def _validate_payload_attribute(
    target: OutboxEvent | BackgroundJob,
    value: dict[str, Any],
    old_value: object,
    initiator: object,
) -> dict[str, Any]:
    del target, old_value, initiator
    if not validate_reference_payload_v1(value):
        raise NotificationContractError("structured payload is invalid")
    return value


for _payload_class in (OutboxEvent, BackgroundJob):
    event.listen(_payload_class.payload, "set", _validate_payload_attribute, retval=True)


def _validate_notification_type(
    target: Notification,
    value: str,
    old_value: object,
    initiator: object,
) -> str:
    del target, old_value, initiator
    if value not in NOTIFICATION_TYPES:
        raise NotificationContractError("invalid notification type")
    return value


event.listen(Notification.notification_type, "set", _validate_notification_type, retval=True)


def _write_once_notification_read(
    target: Notification,
    value: datetime | None,
    old_value: datetime | None | LoaderCallableStatus,
    initiator: object,
) -> datetime | None:
    del initiator
    if _is_persisted_change(target, value, old_value) and old_value is not None:
        raise NotificationContractError("notification read timestamp is write-once")
    return value


event.listen(
    Notification.read_at,
    "set",
    _write_once_notification_read,
    retval=True,
    active_history=True,
)


def _write_once_outbox_publication(
    target: OutboxEvent,
    value: datetime | None,
    old_value: datetime | None | LoaderCallableStatus,
    initiator: object,
) -> datetime | None:
    del initiator
    if _is_persisted_change(target, value, old_value) and old_value is not None:
        raise OutboxWorkflowError("outbox publication timestamp is write-once")
    return value


def _validate_outbox_attempts(
    target: OutboxEvent,
    value: int,
    old_value: int | LoaderCallableStatus,
    initiator: object,
) -> int:
    del initiator
    if _is_persisted_change(target, value, old_value):
        assert isinstance(old_value, int)
        if value < old_value:
            raise OutboxWorkflowError("outbox attempts cannot decrease")
        if value > old_value + 1:
            raise OutboxWorkflowError("outbox attempts must increase by one")
    return value


event.listen(
    OutboxEvent.published_at,
    "set",
    _write_once_outbox_publication,
    retval=True,
    active_history=True,
)
event.listen(
    OutboxEvent.attempts,
    "set",
    _validate_outbox_attempts,
    retval=True,
    active_history=True,
)


_OUTBOX_PROVENANCE_ATTRIBUTES = (
    "owner_id",
    "aggregate_type",
    "aggregate_id",
    "event_type",
    "payload_schema_version",
    "payload",
    "occurred_at",
    "idempotency_key",
)


def _reject_outbox_provenance_change(
    target: OutboxEvent,
    value: object,
    old_value: object,
    initiator: object,
) -> object:
    del initiator
    if _is_persisted_change(target, value, old_value):
        raise OutboxWorkflowError("outbox provenance is immutable")
    return value


for _attribute_name in _OUTBOX_PROVENANCE_ATTRIBUTES:
    event.listen(
        getattr(OutboxEvent, _attribute_name),
        "set",
        _reject_outbox_provenance_change,
        retval=True,
        active_history=True,
    )


_JOB_PROVENANCE_ATTRIBUTES = (
    "owner_id",
    "kind",
    "payload_schema_version",
    "payload",
    "idempotency_key",
    "max_attempts",
    "created_at",
)


def _reject_job_provenance_change(
    target: BackgroundJob,
    value: object,
    old_value: object,
    initiator: object,
) -> object:
    del initiator
    if _is_persisted_change(target, value, old_value):
        raise JobWorkflowError("background job provenance is immutable")
    return value


for _attribute_name in _JOB_PROVENANCE_ATTRIBUTES:
    event.listen(
        getattr(BackgroundJob, _attribute_name),
        "set",
        _reject_job_provenance_change,
        retval=True,
        active_history=True,
    )


def _validate_job_state_change(
    target: BackgroundJob,
    value: str,
    old_value: str | LoaderCallableStatus,
    initiator: object,
) -> str:
    del initiator
    if value not in JOB_STATES:
        raise JobWorkflowError("invalid background job state")
    return value


event.listen(
    BackgroundJob.state,
    "set",
    _validate_job_state_change,
    retval=True,
    active_history=True,
)


def _validate_job_attempt_count_monotonic(
    target: BackgroundJob,
    value: int,
    old_value: int | LoaderCallableStatus,
    initiator: object,
) -> int:
    del initiator
    if _is_persisted_change(target, value, old_value):
        assert isinstance(old_value, int)
        if value < old_value:
            raise JobWorkflowError("background job attempt count cannot decrease")
    return value


event.listen(
    BackgroundJob.attempt_count,
    "set",
    _validate_job_attempt_count_monotonic,
    retval=True,
    active_history=True,
)


def _validate_monotonic_timestamp(
    error_type: type[ValueError],
    message: str,
) -> Any:
    def validator(
        target: object,
        value: datetime,
        old_value: datetime | LoaderCallableStatus,
        initiator: object,
    ) -> datetime:
        del initiator
        if _is_persisted_change(target, value, old_value):
            assert isinstance(old_value, datetime)
            if value < old_value:
                raise error_type(message)
        return value

    return validator


event.listen(
    BackgroundJob.updated_at,
    "set",
    _validate_monotonic_timestamp(JobWorkflowError, "background job updated_at must be monotonic"),
    retval=True,
    active_history=True,
)


def _write_once_job_timestamp(
    target: BackgroundJob,
    value: datetime | None,
    old_value: datetime | None | LoaderCallableStatus,
    initiator: object,
) -> datetime | None:
    del initiator
    if _is_persisted_change(target, value, old_value) and old_value is not None:
        raise JobWorkflowError("background job lifecycle timestamps are write-once")
    return value


for _attribute_name in ("started_at", "completed_at"):
    event.listen(
        getattr(BackgroundJob, _attribute_name),
        "set",
        _write_once_job_timestamp,
        retval=True,
        active_history=True,
    )


def validate_background_job(
    mapper: Mapper[BackgroundJob] | None,
    connection: object | None,
    target: BackgroundJob,
) -> None:
    del mapper, connection
    if target.state not in JOB_STATES:
        raise JobWorkflowError("invalid background job state")
    if not validate_reference_payload_v1(target.payload):
        raise JobWorkflowError("invalid background job payload")
    if target.payload_schema_version != target.payload.get("schema_version"):
        raise JobWorkflowError("background job payload version is incoherent")
    if not 0 <= target.attempt_count <= target.max_attempts or not 1 <= target.max_attempts <= 100:
        raise JobWorkflowError("background job attempt limits are incoherent")
    if (target.last_error_category is None) != (target.last_error_details is None):
        raise JobWorkflowError("background job error fields are incoherent")
    if target.last_error_category is not None and (
        target.last_error_category not in ERROR_CATEGORIES
        or not validate_error_details_v1(target.last_error_details)
    ):
        raise JobWorkflowError("background job error details are invalid")
    if target.updated_at < target.created_at:
        raise JobWorkflowError("background job timestamps are not monotonic")
    if target.attempt_count == 0 and target.started_at is not None:
        raise JobWorkflowError("background job start is incoherent with attempts")
    if target.attempt_count > 0 and target.started_at is None:
        raise JobWorkflowError("background job start is required after a claim")
    if target.started_at is not None and target.started_at < target.created_at:
        raise JobWorkflowError("background job start precedes creation")
    if target.completed_at is not None:
        if target.started_at is None and target.state != "canceled":
            raise JobWorkflowError("background job completion is incoherent")
        if (
            target.started_at is not None
            and target.completed_at < target.started_at
        ):
            raise JobWorkflowError("background job completion is incoherent")
    if target.state == "queued":
        if target.lease_owner is not None or target.lease_expires_at is not None:
            raise JobWorkflowError("queued background job cannot retain a lease")
        if target.completed_at is not None:
            raise JobWorkflowError("queued background job cannot be completed")
    elif target.state == "running":
        if (
            target.attempt_count == 0
            or target.lease_owner is None
            or target.lease_expires_at is None
            or target.lease_expires_at <= target.updated_at
            or target.completed_at is not None
        ):
            raise JobWorkflowError("running background job lease is incoherent")
        if target.last_error_category is not None:
            raise JobWorkflowError("running background job must clear the prior error")
    elif target.state in {"succeeded", "failed"}:
        if (
            target.attempt_count == 0
            or target.lease_owner is not None
            or target.lease_expires_at is not None
            or target.completed_at is None
        ):
            raise JobWorkflowError("terminal background job lifecycle is incoherent")
        if target.state == "succeeded" and target.last_error_category is not None:
            raise JobWorkflowError("successful background job cannot retain an error")
        if target.state == "failed" and target.last_error_category is None:
            raise JobWorkflowError("failed background job requires a typed error")
    else:
        if (
            target.lease_owner is not None
            or target.lease_expires_at is not None
            or target.completed_at is None
            or target.last_error_category is not None
        ):
            raise JobWorkflowError("canceled background job lifecycle is incoherent")


event.listen(BackgroundJob, "before_insert", validate_background_job)


def validate_background_job_update(
    mapper: Mapper[BackgroundJob] | None,
    connection: Connection,
    target: BackgroundJob,
) -> None:
    """Validate one update against a locked persisted row, independent of assignment order."""
    del mapper
    validate_background_job(None, None, target)
    job_table = BackgroundJob.__table__
    lease_expired = (
        job_table.c.lease_expires_at <= func.current_timestamp()
    ).label("_lease_expired")
    old = connection.execute(
        select(*job_table.c, lease_expired)
        .where(job_table.c.id == target.id)
        .with_for_update()
    ).mappings().one_or_none()
    if old is None:
        raise JobWorkflowError("persisted background job does not exist")

    old_state = old["state"]
    assert isinstance(old_state, str)
    if old_state in {"succeeded", "failed", "canceled"}:
        raise JobWorkflowError("terminal background job is immutable")

    for attribute_name in _JOB_PROVENANCE_ATTRIBUTES:
        if getattr(target, attribute_name) != old[attribute_name]:
            raise JobWorkflowError("background job provenance is immutable")
    if target.updated_at < old["updated_at"]:
        raise JobWorkflowError("background job updated_at must be monotonic")
    for attribute_name in ("started_at", "completed_at"):
        old_value = old[attribute_name]
        if old_value is not None and getattr(target, attribute_name) != old_value:
            raise JobWorkflowError("background job lifecycle timestamps are write-once")

    if target.state != old_state and target.state not in JOB_TRANSITIONS[old_state]:
        raise JobWorkflowError("invalid background job state transition")

    old_attempt_count = old["attempt_count"]
    assert isinstance(old_attempt_count, int)
    if old_state == "queued" and target.state == "running":
        if target.attempt_count != old_attempt_count + 1:
            raise JobWorkflowError(
                "background job claim must increment attempt count exactly once"
            )
    elif target.attempt_count != old_attempt_count:
        raise JobWorkflowError("background job attempt count changes only on claim")

    if old_state == "running" and target.state == "running":
        permitted_changes = {"lease_expires_at", "updated_at"}
        changed = {
            column.name
            for column in BackgroundJob.__table__.columns
            if getattr(target, column.name) != old[column.name]
        }
        if not changed <= permitted_changes or target.lease_owner != old["lease_owner"]:
            raise JobWorkflowError("running heartbeat may only extend its lease")
        old_expiry = old["lease_expires_at"]
        if (
            not isinstance(old_expiry, datetime)
            or target.lease_expires_at is None
            or target.lease_expires_at < old_expiry
        ):
            raise JobWorkflowError("running heartbeat cannot shorten its lease")

    if old_state == "running" and target.state == "queued":
        voluntary_retry = (
            target.last_error_category
            in {"transient_dependency", "resource_exhausted"}
            and target.last_error_details is not None
            and target.available_at >= target.updated_at
        )
        if old["_lease_expired"] is not True and not voluntary_retry:
            raise JobWorkflowError("background job lease has not expired")
        if target.lease_owner is not None or target.lease_expires_at is not None:
            raise JobWorkflowError("reclaimed background job must clear its lease")


event.listen(BackgroundJob, "before_update", validate_background_job_update)


def _validate_cursor_event_id(
    target: NotificationDeliveryCursor,
    value: int,
    old_value: int | LoaderCallableStatus,
    initiator: object,
) -> int:
    del initiator
    if _is_persisted_change(target, value, old_value):
        assert isinstance(old_value, int)
        if value < old_value:
            raise DeliveryCursorWorkflowError("delivery cursor cannot decrease")
    return value


event.listen(
    NotificationDeliveryCursor.last_event_id,
    "set",
    _validate_cursor_event_id,
    retval=True,
    active_history=True,
)
event.listen(
    NotificationDeliveryCursor.updated_at,
    "set",
    _validate_monotonic_timestamp(
        DeliveryCursorWorkflowError, "delivery cursor updated_at must be monotonic"
    ),
    retval=True,
    active_history=True,
)


__all__ = [
    "AGGREGATE_TYPES",
    "ERROR_CATEGORIES",
    "JOB_STATES",
    "NOTIFICATION_TYPES",
    "BackgroundJob",
    "DeliveryCursorWorkflowError",
    "JobWorkflowError",
    "Notification",
    "NotificationContractError",
    "NotificationDeliveryCursor",
    "OutboxEvent",
    "OutboxWorkflowError",
    "validate_background_job",
    "validate_background_job_update",
    "validate_error_details_v1",
    "validate_reference_payload_v1",
]

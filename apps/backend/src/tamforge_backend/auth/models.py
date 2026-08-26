"""Single-owner identity, session, idempotency, and audit persistence models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    LargeBinary,
    Text,
    UniqueConstraint,
    event,
    func,
    inspect,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Mapped, Mapper, mapped_column
from sqlalchemy.orm.base import LoaderCallableStatus
from sqlalchemy.orm.state import InstanceState

from ..models.base import Base, TimestampMixin, utc_now


class ImmutableOwnerIdentityError(ValueError):
    """Raised when persisted immutable owner identity is changed."""


class AppendOnlyAuditEventError(ValueError):
    """Raised when ORM code attempts to mutate an audit event."""


class Owner(TimestampMixin, Base):
    """The single allowed GitHub identity for one TAM Forge installation."""

    __tablename__ = "owners"
    __table_args__ = (
        UniqueConstraint("github_user_id", name="uq_owners_github_user_id"),
        CheckConstraint("github_user_id > 0", name="github_user_id_positive"),
        CheckConstraint("btrim(github_login) <> ''", name="github_login_nonblank"),
        Index("ix_owners_github_login", "github_login"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(always=True),
        primary_key=True,
    )
    github_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    github_login: Mapped[str] = mapped_column(Text, nullable=False)


class AuthSession(Base):
    """A browser session containing only fixed-size token hashes."""

    __tablename__ = "auth_sessions"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_auth_sessions_token_hash"),
        CheckConstraint("octet_length(token_hash) = 32", name="token_hash_length"),
        CheckConstraint("octet_length(csrf_hash) = 32", name="csrf_hash_length"),
        CheckConstraint("expires_at > created_at", name="expires_after_creation"),
        CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at",
            name="revoked_after_creation",
        ),
        CheckConstraint(
            "last_seen_at IS NULL OR "
            "(last_seen_at >= created_at AND last_seen_at <= expires_at)",
            name="last_seen_window",
        ),
        Index("ix_auth_sessions_owner_id", "owner_id"),
        Index("ix_auth_sessions_expires_at", "expires_at"),
        Index(
            "ix_auth_sessions_revoked_at",
            "revoked_at",
            postgresql_where=text("revoked_at IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(always=True),
        primary_key=True,
    )
    owner_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "owners.id",
            name="fk_auth_sessions_owner_id_owners",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    csrf_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
    )


class CommandReceipt(Base):
    """A bounded idempotency receipt without raw request content."""

    __tablename__ = "command_receipts"
    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "command_scope",
            "idempotency_key",
            name="uq_command_receipts_owner_scope_idempotency",
        ),
        CheckConstraint("btrim(command_scope) <> ''", name="command_scope_nonblank"),
        CheckConstraint("btrim(idempotency_key) <> ''", name="idempotency_key_nonblank"),
        CheckConstraint("octet_length(request_hash) = 32", name="request_hash_length"),
        CheckConstraint("btrim(status) <> ''", name="status_nonblank"),
        CheckConstraint(
            "jsonb_typeof(result_payload) = 'object'",
            name="result_payload_object",
        ),
        CheckConstraint("expires_at > created_at", name="expires_after_creation"),
        Index("ix_command_receipts_owner_id_expires_at", "owner_id", "expires_at"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(always=True),
        primary_key=True,
    )
    owner_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "owners.id",
            name="fk_command_receipts_owner_id_owners",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    command_scope: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    request_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    result_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AuditEvent(Base):
    """An append-only, redacted security and domain audit event."""

    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint("btrim(actor_kind) <> ''", name="actor_kind_nonblank"),
        CheckConstraint(
            "octet_length(actor_subject_hash) = 32",
            name="actor_subject_hash_length",
        ),
        CheckConstraint("btrim(action) <> ''", name="action_nonblank"),
        CheckConstraint("btrim(aggregate_type) <> ''", name="aggregate_type_nonblank"),
        CheckConstraint("btrim(aggregate_id) <> ''", name="aggregate_id_nonblank"),
        CheckConstraint(
            "request_id IS NULL OR btrim(request_id) <> ''",
            name="request_id_nonblank",
        ),
        CheckConstraint(
            "idempotency_key IS NULL OR btrim(idempotency_key) <> ''",
            name="idempotency_key_nonblank",
        ),
        CheckConstraint(
            "jsonb_typeof(redacted_metadata) = 'object'",
            name="redacted_metadata_object",
        ),
        Index("ix_audit_events_owner_id_occurred_at", "owner_id", "occurred_at"),
        Index(
            "ix_audit_events_aggregate_occurred_at",
            "aggregate_type",
            "aggregate_id",
            "occurred_at",
        ),
        Index(
            "ix_audit_events_request_id",
            "request_id",
            postgresql_where=text("request_id IS NOT NULL"),
        ),
        Index(
            "ix_audit_events_idempotency_key",
            "idempotency_key",
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(always=True),
        primary_key=True,
    )
    owner_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "owners.id",
            name="fk_audit_events_owner_id_owners",
            ondelete="RESTRICT",
        ),
    )
    actor_kind: Mapped[str] = mapped_column(Text, nullable=False)
    actor_subject_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    aggregate_type: Mapped[str] = mapped_column(Text, nullable=False)
    aggregate_id: Mapped[str] = mapped_column(Text, nullable=False)
    request_id: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str | None] = mapped_column(Text)
    redacted_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
    )


@event.listens_for(Owner.github_user_id, "set", retval=True, active_history=True)
def reject_persisted_owner_github_id_change(
    target: Owner,
    value: int,
    old_value: int | LoaderCallableStatus,
    initiator: object,
) -> int:
    """Reject changes after identity acquisition while allowing initial assignment."""
    del initiator
    state: InstanceState[Owner] = inspect(target)
    previously_set = not isinstance(old_value, LoaderCallableStatus)
    if previously_set and (state.persistent or state.detached) and value != old_value:
        raise ImmutableOwnerIdentityError("persisted owner github_user_id is immutable")
    return value


@event.listens_for(Owner, "before_update")
def reject_orm_owner_github_id_change(
    mapper: Mapper[Owner],
    connection: Connection,
    target: Owner,
) -> None:
    """Catch ORM history changes even when attribute instrumentation is bypassed."""
    del mapper, connection
    if inspect(target).attrs.github_user_id.history.has_changes():
        raise ImmutableOwnerIdentityError("persisted owner github_user_id is immutable")


def reject_audit_event_update(
    mapper: Mapper[AuditEvent] | None,
    connection: Connection | None,
    target: AuditEvent,
) -> None:
    """Reject ORM updates to append-only audit evidence."""
    del mapper, connection, target
    raise AppendOnlyAuditEventError("audit events are append-only")


def reject_audit_event_delete(
    mapper: Mapper[AuditEvent] | None,
    connection: Connection | None,
    target: AuditEvent,
) -> None:
    """Reject ORM deletes of append-only audit evidence."""
    del mapper, connection, target
    raise AppendOnlyAuditEventError("audit events are append-only")


event.listen(AuditEvent, "before_update", reject_audit_event_update)
event.listen(AuditEvent, "before_delete", reject_audit_event_delete)


__all__ = [
    "AppendOnlyAuditEventError",
    "AuditEvent",
    "AuthSession",
    "CommandReceipt",
    "ImmutableOwnerIdentityError",
    "Owner",
    "reject_audit_event_delete",
    "reject_audit_event_update",
]

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
from .audit import (
    AuditContractError,
    validate_audit_hash,
    validate_audit_machine_value,
    validate_audit_metadata,
)


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


class NativeOAuthFlow(Base):
    """Durable single-use native OAuth state bound to one PKCE challenge."""

    __tablename__ = "native_oauth_flows"
    __table_args__ = (
        UniqueConstraint("state_hash", name="uq_native_oauth_flows_state_hash"),
        CheckConstraint("octet_length(state_hash) = 32", name="state_hash_length"),
        CheckConstraint(
            "char_length(pkce_challenge) = 43 AND pkce_challenge ~ '^[A-Za-z0-9_-]+$'",
            name="pkce_challenge_s256",
        ),
        CheckConstraint("expires_at > created_at", name="expires_after_creation"),
        CheckConstraint(
            "consumed_at IS NULL OR consumed_at >= created_at",
            name="consumed_after_creation",
        ),
        Index("ix_native_oauth_flows_expires_at", "expires_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    state_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    pkce_challenge: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )


class NativeExchangeCode(Base):
    """One-time app callback code containing no provider credential."""

    __tablename__ = "native_exchange_codes"
    __table_args__ = (
        UniqueConstraint("code_hash", name="uq_native_exchange_codes_code_hash"),
        CheckConstraint("octet_length(code_hash) = 32", name="code_hash_length"),
        CheckConstraint(
            "char_length(pkce_challenge) = 43 AND pkce_challenge ~ '^[A-Za-z0-9_-]+$'",
            name="pkce_challenge_s256",
        ),
        CheckConstraint("expires_at > created_at", name="expires_after_creation"),
        CheckConstraint(
            "consumed_at IS NULL OR consumed_at >= created_at",
            name="consumed_after_creation",
        ),
        Index("ix_native_exchange_codes_owner_id", "owner_id"),
        Index("ix_native_exchange_codes_expires_at", "expires_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "owners.id",
            name="fk_native_exchange_codes_owner_id_owners",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    code_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    pkce_challenge: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )


class NativeAuthSession(Base):
    """Native session with one current short-lived access-token hash."""

    __tablename__ = "native_auth_sessions"
    __table_args__ = (
        UniqueConstraint("access_token_hash", name="uq_native_auth_sessions_access_hash"),
        CheckConstraint(
            "octet_length(access_token_hash) = 32", name="access_token_hash_length"
        ),
        CheckConstraint("access_expires_at > created_at", name="access_expires_after_creation"),
        CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at", name="revoked_after_creation"
        ),
        Index("ix_native_auth_sessions_owner_id", "owner_id"),
        Index("ix_native_auth_sessions_access_expires_at", "access_expires_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "owners.id",
            name="fk_native_auth_sessions_owner_id_owners",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    access_token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    access_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )


class NativeRefreshToken(Base):
    """Retained refresh-token generation used to reject rotation replay."""

    __tablename__ = "native_refresh_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_native_refresh_tokens_token_hash"),
        CheckConstraint("octet_length(token_hash) = 32", name="token_hash_length"),
        CheckConstraint("expires_at > created_at", name="expires_after_creation"),
        CheckConstraint(
            "consumed_at IS NULL OR consumed_at >= created_at", name="consumed_after_creation"
        ),
        CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at", name="revoked_after_creation"
        ),
        Index("ix_native_refresh_tokens_session_id", "session_id"),
        Index("ix_native_refresh_tokens_expires_at", "expires_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    session_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "native_auth_sessions.id",
            name="fk_native_refresh_tokens_session_id_native_auth_sessions",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replaced_by_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "native_refresh_tokens.id",
            name="fk_native_refresh_tokens_replaced_by_id_native_refresh_tokens",
            ondelete="RESTRICT",
        ),
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
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
            "request_correlation_hash IS NULL OR "
            "octet_length(request_correlation_hash) = 32",
            name="request_correlation_hash_length",
        ),
        CheckConstraint(
            "idempotency_correlation_hash IS NULL OR "
            "octet_length(idempotency_correlation_hash) = 32",
            name="idempotency_correlation_hash_length",
        ),
        CheckConstraint(
            "public.tamforge_is_safe_audit_machine_value(actor_kind, 32)",
            name="actor_kind_safe",
        ),
        CheckConstraint(
            "public.tamforge_is_safe_audit_machine_value(action, 64)",
            name="action_safe",
        ),
        CheckConstraint(
            "public.tamforge_is_safe_audit_machine_value(aggregate_type, 64)",
            name="aggregate_type_safe",
        ),
        CheckConstraint(
            "public.tamforge_is_safe_audit_machine_value(aggregate_id, 128)",
            name="aggregate_id_safe",
        ),
        CheckConstraint(
            "public.tamforge_validate_audit_metadata_v1(redacted_metadata)",
            name="redacted_metadata_v1",
        ),
        Index("ix_audit_events_owner_id_occurred_at", "owner_id", "occurred_at"),
        Index(
            "ix_audit_events_aggregate_occurred_at",
            "aggregate_type",
            "aggregate_id",
            "occurred_at",
        ),
        Index(
            "ix_audit_events_request_correlation_hash",
            "request_correlation_hash",
            postgresql_where=text("request_correlation_hash IS NOT NULL"),
        ),
        Index(
            "ix_audit_events_idempotency_correlation_hash",
            "idempotency_correlation_hash",
            postgresql_where=text("idempotency_correlation_hash IS NOT NULL"),
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
    request_correlation_hash: Mapped[bytes | None] = mapped_column(LargeBinary(32))
    idempotency_correlation_hash: Mapped[bytes | None] = mapped_column(LargeBinary(32))
    redacted_metadata: Mapped[dict[str, object]] = mapped_column(
        JSONB,
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


def validate_audit_event_insert(
    mapper: Mapper[AuditEvent] | None,
    connection: Connection | None,
    target: AuditEvent,
) -> None:
    """Canonicalize and validate an audit row before ORM insertion."""
    del mapper, connection
    validate_audit_hash(target.actor_subject_hash)
    validate_audit_hash(target.request_correlation_hash, nullable=True)
    validate_audit_hash(target.idempotency_correlation_hash, nullable=True)
    validate_audit_machine_value(target.actor_kind, max_bytes=32)
    validate_audit_machine_value(target.action, max_bytes=64)
    validate_audit_machine_value(target.aggregate_type, max_bytes=64)
    validate_audit_machine_value(target.aggregate_id, max_bytes=128)
    metadata = target.redacted_metadata
    if metadata is None:
        raise AuditContractError("audit event violates storage contract")
    target.redacted_metadata = validate_audit_metadata(metadata)


event.listen(AuditEvent, "before_insert", validate_audit_event_insert)


__all__ = [
    "AppendOnlyAuditEventError",
    "AuditContractError",
    "AuditEvent",
    "AuthSession",
    "CommandReceipt",
    "ImmutableOwnerIdentityError",
    "Owner",
    "NativeAuthSession",
    "NativeExchangeCode",
    "NativeOAuthFlow",
    "NativeRefreshToken",
    "reject_audit_event_delete",
    "reject_audit_event_update",
    "validate_audit_event_insert",
]

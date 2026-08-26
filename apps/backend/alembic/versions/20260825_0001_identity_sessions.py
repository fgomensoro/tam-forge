"""Add single-owner identity, sessions, idempotency, and append-only audit.

Revision ID: 20260825_0001_identity_sessions
Revises:
Create Date: 2026-08-25

The pgcrypto and vector extensions are cluster-shared capabilities. This
revision creates them idempotently but deliberately leaves them installed on
downgrade so another schema or application cannot be broken accidentally.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260825_0001_identity_sessions"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')

    op.create_table(
        "owners",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("github_user_id", sa.BigInteger(), nullable=False),
        sa.Column("github_login", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "github_user_id > 0",
            name="ck_owners_github_user_id_positive",
        ),
        sa.CheckConstraint(
            "btrim(github_login) <> ''",
            name="ck_owners_github_login_nonblank",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_owners"),
        sa.UniqueConstraint("github_user_id", name="uq_owners_github_user_id"),
    )
    op.create_index("ix_owners_github_login", "owners", ["github_login"])

    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("csrf_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "octet_length(token_hash) = 32",
            name="ck_auth_sessions_token_hash_length",
        ),
        sa.CheckConstraint(
            "octet_length(csrf_hash) = 32",
            name="ck_auth_sessions_csrf_hash_length",
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name="ck_auth_sessions_expires_after_creation",
        ),
        sa.CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at",
            name="ck_auth_sessions_revoked_after_creation",
        ),
        sa.CheckConstraint(
            "last_seen_at IS NULL OR "
            "(last_seen_at >= created_at AND last_seen_at <= expires_at)",
            name="ck_auth_sessions_last_seen_window",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name="fk_auth_sessions_owner_id_owners",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_auth_sessions"),
        sa.UniqueConstraint("token_hash", name="uq_auth_sessions_token_hash"),
    )
    op.create_index("ix_auth_sessions_owner_id", "auth_sessions", ["owner_id"])
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])
    op.create_index(
        "ix_auth_sessions_revoked_at",
        "auth_sessions",
        ["revoked_at"],
        postgresql_where=sa.text("revoked_at IS NOT NULL"),
    )

    op.create_table(
        "command_receipts",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("command_scope", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("request_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "result_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "btrim(command_scope) <> ''",
            name="ck_command_receipts_command_scope_nonblank",
        ),
        sa.CheckConstraint(
            "btrim(idempotency_key) <> ''",
            name="ck_command_receipts_idempotency_key_nonblank",
        ),
        sa.CheckConstraint(
            "octet_length(request_hash) = 32",
            name="ck_command_receipts_request_hash_length",
        ),
        sa.CheckConstraint(
            "btrim(status) <> ''",
            name="ck_command_receipts_status_nonblank",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(result_payload) = 'object'",
            name="ck_command_receipts_result_payload_object",
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name="ck_command_receipts_expires_after_creation",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name="fk_command_receipts_owner_id_owners",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_command_receipts"),
        sa.UniqueConstraint(
            "owner_id",
            "command_scope",
            "idempotency_key",
            name="uq_command_receipts_owner_scope_idempotency",
        ),
    )
    op.create_index(
        "ix_command_receipts_owner_id_expires_at",
        "command_receipts",
        ["owner_id", "expires_at"],
    )

    op.create_table(
        "audit_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=True),
        sa.Column("actor_kind", sa.Text(), nullable=False),
        sa.Column("actor_subject_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("aggregate_type", sa.Text(), nullable=False),
        sa.Column("aggregate_id", sa.Text(), nullable=False),
        sa.Column("request_id", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column(
            "redacted_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "btrim(actor_kind) <> ''",
            name="ck_audit_events_actor_kind_nonblank",
        ),
        sa.CheckConstraint(
            "octet_length(actor_subject_hash) = 32",
            name="ck_audit_events_actor_subject_hash_length",
        ),
        sa.CheckConstraint(
            "btrim(action) <> ''",
            name="ck_audit_events_action_nonblank",
        ),
        sa.CheckConstraint(
            "btrim(aggregate_type) <> ''",
            name="ck_audit_events_aggregate_type_nonblank",
        ),
        sa.CheckConstraint(
            "btrim(aggregate_id) <> ''",
            name="ck_audit_events_aggregate_id_nonblank",
        ),
        sa.CheckConstraint(
            "request_id IS NULL OR btrim(request_id) <> ''",
            name="ck_audit_events_request_id_nonblank",
        ),
        sa.CheckConstraint(
            "idempotency_key IS NULL OR btrim(idempotency_key) <> ''",
            name="ck_audit_events_idempotency_key_nonblank",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(redacted_metadata) = 'object'",
            name="ck_audit_events_redacted_metadata_object",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name="fk_audit_events_owner_id_owners",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audit_events"),
    )
    op.create_index(
        "ix_audit_events_owner_id_occurred_at",
        "audit_events",
        ["owner_id", "occurred_at"],
    )
    op.create_index(
        "ix_audit_events_aggregate_occurred_at",
        "audit_events",
        ["aggregate_type", "aggregate_id", "occurred_at"],
    )
    op.create_index(
        "ix_audit_events_request_id",
        "audit_events",
        ["request_id"],
        postgresql_where=sa.text("request_id IS NOT NULL"),
    )
    op.create_index(
        "ix_audit_events_idempotency_key",
        "audit_events",
        ["idempotency_key"],
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    op.execute(
        """
        CREATE FUNCTION tamforge_reject_owner_github_id_change()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.github_user_id IS DISTINCT FROM OLD.github_user_id THEN
                RAISE EXCEPTION 'owner identity is immutable'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_owners_immutable_github_user_id
        BEFORE UPDATE OF github_user_id ON owners
        FOR EACH ROW
        EXECUTE FUNCTION tamforge_reject_owner_github_id_change()
        """
    )
    op.execute(
        """
        CREATE FUNCTION tamforge_reject_audit_event_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'audit events are append-only'
                USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_audit_events_append_only
        BEFORE UPDATE OR DELETE ON audit_events
        FOR EACH ROW
        EXECUTE FUNCTION tamforge_reject_audit_event_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_audit_events_append_only ON audit_events")
    op.execute("DROP FUNCTION IF EXISTS tamforge_reject_audit_event_mutation()")
    op.execute("DROP TRIGGER IF EXISTS trg_owners_immutable_github_user_id ON owners")
    op.execute("DROP FUNCTION IF EXISTS tamforge_reject_owner_github_id_change()")

    op.drop_index("ix_audit_events_idempotency_key", table_name="audit_events")
    op.drop_index("ix_audit_events_request_id", table_name="audit_events")
    op.drop_index("ix_audit_events_aggregate_occurred_at", table_name="audit_events")
    op.drop_index("ix_audit_events_owner_id_occurred_at", table_name="audit_events")
    op.drop_table("audit_events")

    op.drop_index(
        "ix_command_receipts_owner_id_expires_at",
        table_name="command_receipts",
    )
    op.drop_table("command_receipts")

    op.drop_index(
        "ix_auth_sessions_revoked_at",
        table_name="auth_sessions",
    )
    op.drop_index("ix_auth_sessions_expires_at", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_owner_id", table_name="auth_sessions")
    op.drop_table("auth_sessions")

    op.drop_index("ix_owners_github_login", table_name="owners")
    op.drop_table("owners")

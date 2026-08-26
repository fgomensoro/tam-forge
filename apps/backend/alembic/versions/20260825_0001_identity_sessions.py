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

    op.execute(
        """
        CREATE FUNCTION public.tamforge_is_safe_audit_machine_value(
            candidate text,
            max_bytes integer
        )
        RETURNS boolean
        LANGUAGE sql
        IMMUTABLE
        PARALLEL SAFE
        SET search_path = pg_catalog
        AS $$
        SELECT
            candidate IS NOT NULL
            AND max_bytes BETWEEN 1 AND 128
            AND octet_length(candidate) BETWEEN 1 AND max_bytes
            AND candidate ~ '^[a-z0-9][a-z0-9_.:-]*$'
            AND lower(candidate) !~
                '^(bearer|gh[pousr]_|github_pat_|sk-|api[_-]?key|session[_-]?token|eyj)'
            AND lower(candidate) !~
                '^[a-z0-9_-]{10,}\\.[a-z0-9_-]{10,}\\.[a-z0-9_-]{10,}$'
            AND (
                lower(candidate) ~
                    '^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
                OR lower(candidate) !~ '^[a-z0-9_-]{32,}$'
            )
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION public.tamforge_validate_audit_metadata_v1(metadata jsonb)
        RETURNS boolean
        LANGUAGE plpgsql
        IMMUTABLE
        PARALLEL SAFE
        SET search_path = pg_catalog
        AS $$
        DECLARE
            metadata_key text;
            item_key text;
            item_value jsonb;
            changed_value text;
            seen_changed text[] := ARRAY[]::text[];
        BEGIN
            IF metadata IS NULL
                OR jsonb_typeof(metadata) <> 'object'
                OR octet_length(metadata::text) > 2048 THEN
                RETURN false;
            END IF;

            IF NOT metadata ?& ARRAY[
                'schema_version', 'outcome', 'reason_code',
                'changed_fields', 'counts', 'flags'
            ] THEN
                RETURN false;
            END IF;
            FOR metadata_key IN SELECT jsonb_object_keys(metadata) LOOP
                IF metadata_key <> ALL (ARRAY[
                    'schema_version', 'outcome', 'reason_code',
                    'changed_fields', 'counts', 'flags'
                ]) THEN
                    RETURN false;
                END IF;
            END LOOP;

            IF jsonb_typeof(metadata->'schema_version') <> 'number'
                OR metadata->>'schema_version' <> '1'
                OR jsonb_typeof(metadata->'outcome') <> 'string'
                OR metadata->>'outcome' NOT IN ('succeeded', 'failed', 'denied', 'noop')
                OR jsonb_typeof(metadata->'reason_code') <> 'string'
                OR metadata->>'reason_code' NOT IN (
                    'none', 'invalid_input', 'unauthorized', 'conflict',
                    'expired', 'revoked', 'not_found', 'internal_error'
                ) THEN
                RETURN false;
            END IF;

            IF jsonb_typeof(metadata->'changed_fields') <> 'array' THEN
                RETURN false;
            END IF;
            IF jsonb_array_length(metadata->'changed_fields') > 16 THEN
                RETURN false;
            END IF;
            FOR item_value IN SELECT value FROM jsonb_array_elements(
                metadata->'changed_fields'
            ) LOOP
                IF jsonb_typeof(item_value) <> 'string' THEN
                    RETURN false;
                END IF;
                changed_value := item_value #>> '{}';
                IF changed_value NOT IN (
                    'github_login', 'expires_at', 'revoked_at', 'last_seen_at',
                    'status', 'state', 'result_payload'
                ) OR changed_value = ANY (seen_changed) THEN
                    RETURN false;
                END IF;
                seen_changed := array_append(seen_changed, changed_value);
            END LOOP;

            IF jsonb_typeof(metadata->'counts') <> 'object' THEN
                RETURN false;
            END IF;
            FOR item_key, item_value IN SELECT key, value FROM jsonb_each(
                metadata->'counts'
            ) LOOP
                IF item_key NOT IN (
                    'attempted', 'succeeded', 'failed', 'affected', 'remaining'
                ) OR jsonb_typeof(item_value) <> 'number' THEN
                    RETURN false;
                END IF;
                IF item_value::text !~ '^(0|[1-9][0-9]{0,6})$' THEN
                    RETURN false;
                END IF;
                IF item_value::text::bigint > 1000000 THEN
                    RETURN false;
                END IF;
            END LOOP;

            IF jsonb_typeof(metadata->'flags') <> 'object' THEN
                RETURN false;
            END IF;
            FOR item_key, item_value IN SELECT key, value FROM jsonb_each(
                metadata->'flags'
            ) LOOP
                IF item_key NOT IN (
                    'replayed', 'retryable', 'authenticated', 'authorized', 'redacted'
                ) OR jsonb_typeof(item_value) <> 'boolean' THEN
                    RETURN false;
                END IF;
            END LOOP;

            RETURN true;
        END;
        $$
        """
    )

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
        sa.Column("request_correlation_hash", sa.LargeBinary(length=32), nullable=True),
        sa.Column(
            "idempotency_correlation_hash",
            sa.LargeBinary(length=32),
            nullable=True,
        ),
        sa.Column(
            "redacted_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text(
                "'{\"changed_fields\":[],\"counts\":{},\"flags\":{},"
                "\"outcome\":\"succeeded\",\"reason_code\":\"none\","
                "\"schema_version\":1}'::jsonb"
            ),
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
            "request_correlation_hash IS NULL OR "
            "octet_length(request_correlation_hash) = 32",
            name="ck_audit_events_request_correlation_hash_length",
        ),
        sa.CheckConstraint(
            "idempotency_correlation_hash IS NULL OR "
            "octet_length(idempotency_correlation_hash) = 32",
            name="ck_audit_events_idempotency_correlation_hash_length",
        ),
        sa.CheckConstraint(
            "public.tamforge_is_safe_audit_machine_value(actor_kind, 32)",
            name="ck_audit_events_actor_kind_safe",
        ),
        sa.CheckConstraint(
            "public.tamforge_is_safe_audit_machine_value(action, 64)",
            name="ck_audit_events_action_safe",
        ),
        sa.CheckConstraint(
            "public.tamforge_is_safe_audit_machine_value(aggregate_type, 64)",
            name="ck_audit_events_aggregate_type_safe",
        ),
        sa.CheckConstraint(
            "public.tamforge_is_safe_audit_machine_value(aggregate_id, 128)",
            name="ck_audit_events_aggregate_id_safe",
        ),
        sa.CheckConstraint(
            "public.tamforge_validate_audit_metadata_v1(redacted_metadata)",
            name="ck_audit_events_redacted_metadata_v1",
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
        "ix_audit_events_request_correlation_hash",
        "audit_events",
        ["request_correlation_hash"],
        postgresql_where=sa.text("request_correlation_hash IS NOT NULL"),
    )
    op.create_index(
        "ix_audit_events_idempotency_correlation_hash",
        "audit_events",
        ["idempotency_correlation_hash"],
        postgresql_where=sa.text("idempotency_correlation_hash IS NOT NULL"),
    )

    op.execute(
        """
        CREATE FUNCTION public.tamforge_validate_audit_event_insert()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            IF NEW.actor_subject_hash IS NULL
                OR octet_length(NEW.actor_subject_hash) <> 32
                OR (
                    NEW.request_correlation_hash IS NOT NULL
                    AND octet_length(NEW.request_correlation_hash) <> 32
                )
                OR (
                    NEW.idempotency_correlation_hash IS NOT NULL
                    AND octet_length(NEW.idempotency_correlation_hash) <> 32
                )
                OR NOT public.tamforge_is_safe_audit_machine_value(NEW.actor_kind, 32)
                OR NOT public.tamforge_is_safe_audit_machine_value(NEW.action, 64)
                OR NOT public.tamforge_is_safe_audit_machine_value(
                    NEW.aggregate_type,
                    64
                )
                OR NOT public.tamforge_is_safe_audit_machine_value(NEW.aggregate_id, 128)
                OR NEW.redacted_metadata IS NULL
                OR NOT public.tamforge_validate_audit_metadata_v1(NEW.redacted_metadata)
            THEN
                RAISE EXCEPTION 'audit event violates storage contract'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_audit_events_validate_insert
        BEFORE INSERT ON audit_events
        FOR EACH ROW
        EXECUTE FUNCTION public.tamforge_validate_audit_event_insert()
        """
    )

    op.execute(
        """
        CREATE FUNCTION public.tamforge_reject_owner_github_id_change()
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
        EXECUTE FUNCTION public.tamforge_reject_owner_github_id_change()
        """
    )
    op.execute(
        """
        CREATE FUNCTION public.tamforge_reject_audit_event_mutation()
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
        EXECUTE FUNCTION public.tamforge_reject_audit_event_mutation()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_audit_events_append_only_truncate
        BEFORE TRUNCATE ON audit_events
        FOR EACH STATEMENT
        EXECUTE FUNCTION public.tamforge_reject_audit_event_mutation()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_audit_events_append_only_truncate ON audit_events"
    )
    op.execute("DROP TRIGGER IF EXISTS trg_audit_events_append_only ON audit_events")
    op.execute("DROP FUNCTION IF EXISTS public.tamforge_reject_audit_event_mutation()")
    op.execute("DROP TRIGGER IF EXISTS trg_audit_events_validate_insert ON audit_events")
    op.execute("DROP FUNCTION IF EXISTS public.tamforge_validate_audit_event_insert()")
    op.execute("DROP TRIGGER IF EXISTS trg_owners_immutable_github_user_id ON owners")
    op.execute("DROP FUNCTION IF EXISTS public.tamforge_reject_owner_github_id_change()")

    op.drop_index(
        "ix_audit_events_idempotency_correlation_hash",
        table_name="audit_events",
    )
    op.drop_index(
        "ix_audit_events_request_correlation_hash",
        table_name="audit_events",
    )
    op.drop_index("ix_audit_events_aggregate_occurred_at", table_name="audit_events")
    op.drop_index("ix_audit_events_owner_id_occurred_at", table_name="audit_events")
    op.drop_table("audit_events")
    op.execute("DROP FUNCTION IF EXISTS public.tamforge_validate_audit_metadata_v1(jsonb)")
    op.execute(
        "DROP FUNCTION IF EXISTS public.tamforge_is_safe_audit_machine_value(text, integer)"
    )

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

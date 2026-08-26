"""Add Today read foundations, notifications, outbox, and durable jobs.

Revision ID: 20260825_0005_today_read_models
Revises: 20260825_0004_evidence_scoring
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260825_0005_today_read_models"
down_revision: str | None = "20260825_0004_evidence_scoring"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _id() -> sa.Column[int]:
    return sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False)


def _created(name: str = "created_at") -> sa.Column[object]:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        server_default=sa.text("CURRENT_TIMESTAMP"),
        nullable=False,
    )


def _jsonb(name: str, *, nullable: bool = False) -> sa.Column[object]:
    return sa.Column(
        name,
        postgresql.JSONB(astext_type=sa.Text()),
        nullable=nullable,
    )


def _create_validation_functions() -> None:
    op.execute(
        """
        CREATE FUNCTION public.tamforge_validate_reference_payload_v1(payload jsonb)
        RETURNS boolean
        LANGUAGE plpgsql
        IMMUTABLE
        PARALLEL SAFE
        SET search_path = pg_catalog
        AS $$
        DECLARE payload_key text;
        BEGIN
            IF payload IS NULL OR jsonb_typeof(payload) <> 'object'
                OR octet_length(payload::text) > 1024
                OR NOT payload ?& ARRAY['schema_version', 'subject_id']
                OR jsonb_typeof(payload->'schema_version') <> 'number'
                OR payload->>'schema_version' <> '1'
                OR jsonb_typeof(payload->'subject_id') <> 'number'
                OR payload->>'subject_id' !~ '^[1-9][0-9]{0,18}$' THEN
                RETURN false;
            END IF;
            FOR payload_key IN SELECT jsonb_object_keys(payload) LOOP
                IF payload_key <> ALL (ARRAY[
                    'schema_version', 'subject_id', 'related_id'
                ]) THEN
                    RETURN false;
                END IF;
            END LOOP;
            IF payload ? 'related_id' AND (
                jsonb_typeof(payload->'related_id') <> 'number'
                OR payload->>'related_id' !~ '^[1-9][0-9]{0,18}$'
            ) THEN
                RETURN false;
            END IF;
            RETURN true;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION public.tamforge_validate_error_details_v1(payload jsonb)
        RETURNS boolean
        LANGUAGE plpgsql
        IMMUTABLE
        PARALLEL SAFE
        SET search_path = pg_catalog
        AS $$
        DECLARE payload_key text;
        BEGIN
            IF payload IS NULL OR jsonb_typeof(payload) <> 'object'
                OR octet_length(payload::text) > 512
                OR NOT payload ? 'schema_version'
                OR jsonb_typeof(payload->'schema_version') <> 'number'
                OR payload->>'schema_version' <> '1' THEN
                RETURN false;
            END IF;
            FOR payload_key IN SELECT jsonb_object_keys(payload) LOOP
                IF payload_key <> ALL (ARRAY[
                    'schema_version', 'attempt', 'retry_after_seconds', 'http_status'
                ]) THEN
                    RETURN false;
                END IF;
            END LOOP;
            IF payload ? 'attempt' AND (
                jsonb_typeof(payload->'attempt') <> 'number'
                OR payload->>'attempt' !~ '^(0|[1-9][0-9]{0,2})$'
                OR (payload->>'attempt')::integer > 100
            ) THEN
                RETURN false;
            END IF;
            IF payload ? 'retry_after_seconds' AND (
                jsonb_typeof(payload->'retry_after_seconds') <> 'number'
                OR payload->>'retry_after_seconds' !~ '^(0|[1-9][0-9]{0,5})$'
                OR (payload->>'retry_after_seconds')::integer > 86400
            ) THEN
                RETURN false;
            END IF;
            IF payload ? 'http_status' AND (
                jsonb_typeof(payload->'http_status') <> 'number'
                OR payload->>'http_status' !~ '^[1-5][0-9]{2}$'
                OR (payload->>'http_status')::integer NOT BETWEEN 100 AND 599
            ) THEN
                RETURN false;
            END IF;
            RETURN true;
        END;
        $$
        """
    )


def _create_tables() -> None:
    op.create_unique_constraint(
        "uq_skill_evidence_events_owner_id_id",
        "skill_evidence_events",
        ["owner_id", "id"],
    )

    op.create_table(
        "corrections",
        _id(),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("source_activity_id", sa.BigInteger(), nullable=False),
        sa.Column("source_evidence_event_id", sa.BigInteger(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("instruction", sa.Text(), nullable=False),
        sa.Column("attempt_b_activity_id", sa.BigInteger(), nullable=True),
        _created(),
        _created("updated_at"),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("priority BETWEEN 1 AND 2", name="priority_slot_allowed"),
        sa.CheckConstraint(
            "status IN ('pending', 'scheduled', 'completed', 'dismissed', 'superseded')",
            name="status_allowed",
        ),
        sa.CheckConstraint(
            "btrim(instruction) <> '' AND octet_length(instruction) <= 1024",
            name="instruction_compact",
        ),
        sa.CheckConstraint(
            "attempt_b_activity_id IS NULL OR attempt_b_activity_id <> source_activity_id",
            name="attempt_b_not_source",
        ),
        sa.CheckConstraint(
            "(status = 'pending' AND attempt_b_activity_id IS NULL AND completed_at IS NULL) OR "
            "(status = 'scheduled' AND attempt_b_activity_id IS NOT NULL "
            "AND completed_at IS NULL) OR "
            "(status = 'completed' AND attempt_b_activity_id IS NOT NULL "
            "AND completed_at IS NOT NULL) OR "
            "(status IN ('dismissed', 'superseded') AND attempt_b_activity_id IS NULL "
            "AND completed_at IS NOT NULL)",
            name="lifecycle_coherent",
        ),
        sa.CheckConstraint(
            "updated_at >= created_at AND (completed_at IS NULL OR completed_at >= created_at)",
            name="timestamps_coherent",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "source_activity_id"],
            ["activity_instances.owner_id", "activity_instances.id"],
            name="fk_corrections_owner_source_activity_activity_instances",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "source_evidence_event_id"],
            ["skill_evidence_events.owner_id", "skill_evidence_events.id"],
            name="fk_corrections_owner_source_evidence_skill_evidence_events",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "attempt_b_activity_id"],
            ["activity_instances.owner_id", "activity_instances.id"],
            name="fk_corrections_owner_attempt_b_activity_instances",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_corrections"),
        sa.UniqueConstraint("owner_id", "id", name="uq_corrections_owner_id_id"),
        sa.UniqueConstraint(
            "owner_id",
            "source_activity_id",
            "priority",
            name="uq_corrections_owner_source_activity_priority",
        ),
    )
    op.create_index(
        "ix_corrections_owner_due_status_priority",
        "corrections",
        ["owner_id", "due_date", "status", "priority"],
    )
    op.create_index(
        "ix_corrections_owner_source_activity",
        "corrections",
        ["owner_id", "source_activity_id"],
    )
    op.create_index(
        "ix_corrections_owner_source_evidence",
        "corrections",
        ["owner_id", "source_evidence_event_id"],
    )
    op.create_index(
        "ix_corrections_owner_attempt_b",
        "corrections",
        ["owner_id", "attempt_b_activity_id"],
    )

    op.create_table(
        "interviews",
        _id(),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("company", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expected_duration_minutes", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("privacy_permission_code", sa.Text(), nullable=False),
        _created(),
        _created("updated_at"),
        sa.CheckConstraint(
            "btrim(company) <> '' AND octet_length(company) <= 256 "
            "AND btrim(role) <> '' AND octet_length(role) <= 256 "
            "AND btrim(stage) <> '' AND octet_length(stage) <= 128",
            name="identity_fields_bounded",
        ),
        sa.CheckConstraint(
            "expected_duration_minutes BETWEEN 1 AND 480",
            name="expected_duration_bounded",
        ),
        sa.CheckConstraint(
            "status IN ('scheduled', 'completed', 'cancelled', 'rescheduled')",
            name="status_allowed",
        ),
        sa.CheckConstraint(
            "privacy_permission_code IN ('permission_not_requested', "
            "'permission_granted', 'permission_denied', 'recording_prohibited')",
            name="privacy_permission_allowed",
        ),
        sa.CheckConstraint("updated_at >= created_at", name="timestamps_monotonic"),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name="fk_interviews_owner_id_owners",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_interviews"),
        sa.UniqueConstraint("owner_id", "id", name="uq_interviews_owner_id_id"),
    )
    op.create_index(
        "ix_interviews_owner_starts_at", "interviews", ["owner_id", "starts_at", "id"]
    )
    op.create_index(
        "ix_interviews_owner_status_starts",
        "interviews",
        ["owner_id", "status", "starts_at"],
    )

    op.create_table(
        "activity_processing_statuses",
        _id(),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("activity_instance_id", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("progress_label", sa.Text(), nullable=False),
        sa.Column("last_error_category", sa.Text(), nullable=True),
        _jsonb("last_error_details", nullable=True),
        _created(),
        _created("updated_at"),
        sa.CheckConstraint(
            "state IN ('uploaded', 'processing_audio', 'transcribing', 'analyzing', "
            "'ready', 'needs_attention')",
            name="state_allowed",
        ),
        sa.CheckConstraint(
            "progress_label IN ('uploaded', 'processing_audio', 'transcribing', "
            "'analyzing', 'ready', 'action_required')",
            name="progress_label_allowed",
        ),
        sa.CheckConstraint(
            "(state = 'uploaded' AND progress_label = 'uploaded') OR "
            "(state = 'processing_audio' AND progress_label = 'processing_audio') OR "
            "(state = 'transcribing' AND progress_label = 'transcribing') OR "
            "(state = 'analyzing' AND progress_label = 'analyzing') OR "
            "(state = 'ready' AND progress_label = 'ready') OR "
            "(state = 'needs_attention' AND progress_label = 'action_required')",
            name="state_progress_coherent",
        ),
        sa.CheckConstraint(
            "last_error_category IS NULL OR last_error_category IN "
            "('transient_dependency', 'resource_exhausted', 'invalid_input', "
            "'permission_required', 'processing_failure', 'internal_error')",
            name="error_category_allowed",
        ),
        sa.CheckConstraint(
            "(state = 'needs_attention' AND last_error_category IS NOT NULL "
            "AND last_error_details IS NOT NULL "
            "AND public.tamforge_validate_error_details_v1(last_error_details)) OR "
            "(state <> 'needs_attention' AND last_error_category IS NULL "
            "AND last_error_details IS NULL)",
            name="error_details_coherent",
        ),
        sa.CheckConstraint("updated_at >= created_at", name="timestamps_monotonic"),
        sa.ForeignKeyConstraint(
            ["owner_id", "activity_instance_id"],
            ["activity_instances.owner_id", "activity_instances.id"],
            name="fk_processing_status_owner_activity_activity_instances",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_activity_processing_statuses"),
        sa.UniqueConstraint(
            "owner_id", "activity_instance_id", name="uq_processing_status_owner_activity"
        ),
    )
    op.create_index(
        "ix_processing_status_owner_state_updated",
        "activity_processing_statuses",
        ["owner_id", "state", "updated_at"],
    )
    op.create_index(
        "ix_processing_status_owner_activity",
        "activity_processing_statuses",
        ["owner_id", "activity_instance_id"],
    )

    op.create_table(
        "notifications",
        _id(),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("notification_type", sa.Text(), nullable=False),
        sa.Column("subject_kind", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.BigInteger(), nullable=False),
        _created(),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "notification_type IN ('feedback_ready', 'correction_due', "
            "'upcoming_real_interview', 'saturday_assessment', "
            "'processing_failure_requires_action')",
            name="notification_type_allowed",
        ),
        sa.CheckConstraint(
            "subject_kind IN ('activity', 'correction', 'interview', 'study_day', "
            "'processing_status')",
            name="subject_kind_allowed",
        ),
        sa.CheckConstraint("subject_id > 0", name="subject_id_positive"),
        sa.CheckConstraint("read_at IS NULL OR read_at >= created_at", name="read_after_creation"),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name="fk_notifications_owner_id_owners",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_notifications"),
        sa.UniqueConstraint("owner_id", "id", name="uq_notifications_owner_id_id"),
    )
    op.create_index(
        "ix_notifications_owner_created", "notifications", ["owner_id", "created_at", "id"]
    )
    op.create_index(
        "ix_notifications_owner_unread_created",
        "notifications",
        ["owner_id", "created_at", "id"],
        postgresql_where=sa.text("read_at IS NULL"),
    )

    op.create_table(
        "outbox_events",
        _id(),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("aggregate_type", sa.Text(), nullable=False),
        sa.Column("aggregate_id", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("payload_schema_version", sa.Integer(), nullable=False),
        _jsonb("payload"),
        _created("occurred_at"),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "aggregate_type IN ('activity', 'correction', 'interview', 'study_day', "
            "'processing_status', 'roadmap', 'notification', 'background_job')",
            name="aggregate_type_allowed",
        ),
        sa.CheckConstraint("aggregate_id > 0", name="aggregate_id_positive"),
        sa.CheckConstraint(
            "event_type ~ '^[a-z][a-z0-9_]{0,31}(\\.[a-z][a-z0-9_]{0,31}){1,3}$' "
            "AND octet_length(event_type) <= 128",
            name="event_type_safe",
        ),
        sa.CheckConstraint("payload_schema_version = 1", name="payload_version_supported"),
        sa.CheckConstraint(
            "public.tamforge_validate_reference_payload_v1(payload)", name="payload_valid"
        ),
        sa.CheckConstraint(
            "payload->>'schema_version' = payload_schema_version::text",
            name="payload_version_coherent",
        ),
        sa.CheckConstraint("attempts BETWEEN 0 AND 100", name="attempts_bounded"),
        sa.CheckConstraint(
            "published_at IS NULL OR (published_at >= occurred_at AND attempts > 0)",
            name="publication_coherent",
        ),
        sa.CheckConstraint(
            "idempotency_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'",
            name="idempotency_key_safe",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name="fk_outbox_events_owner_id_owners",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_outbox_events"),
        sa.UniqueConstraint("owner_id", "id", name="uq_outbox_events_owner_id_id"),
        sa.UniqueConstraint(
            "owner_id", "idempotency_key", name="uq_outbox_events_owner_idempotency"
        ),
    )
    op.create_index(
        "ix_outbox_events_unpublished_occurred",
        "outbox_events",
        ["occurred_at", "id"],
        postgresql_where=sa.text("published_at IS NULL"),
    )
    op.create_index(
        "ix_outbox_events_owner_occurred",
        "outbox_events",
        ["owner_id", "occurred_at", "id"],
    )

    op.create_table(
        "background_jobs",
        _id(),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("payload_schema_version", sa.Integer(), nullable=False),
        _jsonb("payload"),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("lease_owner", sa.Text(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_category", sa.Text(), nullable=True),
        _jsonb("last_error_details", nullable=True),
        _created(),
        _created("updated_at"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("kind ~ '^[a-z][a-z0-9_]{0,63}$'", name="kind_safe"),
        sa.CheckConstraint("payload_schema_version = 1", name="payload_version_supported"),
        sa.CheckConstraint(
            "public.tamforge_validate_reference_payload_v1(payload)", name="payload_valid"
        ),
        sa.CheckConstraint(
            "payload->>'schema_version' = payload_schema_version::text",
            name="payload_version_coherent",
        ),
        sa.CheckConstraint("priority BETWEEN 0 AND 100", name="priority_bounded"),
        sa.CheckConstraint(
            "state IN ('queued', 'running', 'succeeded', 'failed')", name="state_allowed"
        ),
        sa.CheckConstraint(
            "idempotency_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'",
            name="idempotency_key_safe",
        ),
        sa.CheckConstraint(
            "attempt_count BETWEEN 0 AND max_attempts AND max_attempts BETWEEN 1 AND 100",
            name="attempts_coherent",
        ),
        sa.CheckConstraint(
            "lease_owner IS NULL OR lease_owner ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'",
            name="lease_owner_safe",
        ),
        sa.CheckConstraint(
            "last_error_category IS NULL OR last_error_category IN "
            "('transient_dependency', 'resource_exhausted', 'invalid_input', "
            "'permission_required', 'processing_failure', 'internal_error')",
            name="error_category_allowed",
        ),
        sa.CheckConstraint(
            "(last_error_category IS NULL AND last_error_details IS NULL) OR "
            "(last_error_category IS NOT NULL AND last_error_details IS NOT NULL "
            "AND public.tamforge_validate_error_details_v1(last_error_details))",
            name="error_details_coherent",
        ),
        sa.CheckConstraint(
            "(state = 'queued' AND lease_owner IS NULL AND lease_expires_at IS NULL "
            "AND completed_at IS NULL) OR "
            "(state = 'running' AND attempt_count > 0 AND lease_owner IS NOT NULL "
            "AND lease_expires_at IS NOT NULL AND started_at IS NOT NULL "
            "AND completed_at IS NULL) OR "
            "(state IN ('succeeded', 'failed') AND attempt_count > 0 "
            "AND lease_owner IS NULL AND lease_expires_at IS NULL "
            "AND started_at IS NOT NULL AND completed_at IS NOT NULL)",
            name="lifecycle_coherent",
        ),
        sa.CheckConstraint(
            "(attempt_count = 0 AND started_at IS NULL) OR "
            "(attempt_count > 0 AND started_at IS NOT NULL)",
            name="started_attempt_coherent",
        ),
        sa.CheckConstraint(
            "updated_at >= created_at AND (started_at IS NULL OR started_at >= created_at) "
            "AND (completed_at IS NULL OR completed_at >= started_at) "
            "AND (lease_expires_at IS NULL OR lease_expires_at > updated_at)",
            name="timestamps_coherent",
        ),
        sa.CheckConstraint(
            "state <> 'succeeded' OR last_error_category IS NULL",
            name="success_without_error",
        ),
        sa.CheckConstraint(
            "state <> 'failed' OR last_error_category IS NOT NULL", name="failure_has_error"
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name="fk_background_jobs_owner_id_owners",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_background_jobs"),
        sa.UniqueConstraint("owner_id", "id", name="uq_background_jobs_owner_id_id"),
        sa.UniqueConstraint(
            "owner_id", "idempotency_key", name="uq_background_jobs_owner_idempotency"
        ),
    )
    op.create_index(
        "ix_background_jobs_claimable",
        "background_jobs",
        ["priority", "available_at", "id"],
        postgresql_where=sa.text("state = 'queued'"),
    )
    op.create_index(
        "ix_background_jobs_owner_state",
        "background_jobs",
        ["owner_id", "state", "updated_at"],
    )
    op.create_index(
        "ix_background_jobs_expired_lease",
        "background_jobs",
        ["lease_expires_at", "id"],
        postgresql_where=sa.text("state = 'running'"),
    )

    op.create_table(
        "notification_delivery_cursor",
        _id(),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("stream_key", sa.Text(), nullable=False),
        sa.Column("last_event_id", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        _created(),
        _created("updated_at"),
        sa.CheckConstraint(
            "stream_key ~ '^[a-z][a-z0-9_]{0,31}$'", name="stream_key_safe"
        ),
        sa.CheckConstraint("last_event_id >= 0", name="last_event_id_nonnegative"),
        sa.CheckConstraint("updated_at >= created_at", name="timestamps_monotonic"),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name="fk_notification_cursor_owner_id_owners",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_notification_delivery_cursor"),
        sa.UniqueConstraint(
            "owner_id", "stream_key", name="uq_notification_cursor_owner_stream"
        ),
    )


def _create_guards() -> None:
    op.execute(
        """
        CREATE FUNCTION public.tamforge_guard_correction_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        DECLARE attempt_kind_value text;
        DECLARE evidence_activity_id bigint;
        BEGIN
            IF TG_OP = 'UPDATE' THEN
                IF NEW.owner_id IS DISTINCT FROM OLD.owner_id
                    OR NEW.source_activity_id IS DISTINCT FROM OLD.source_activity_id
                    OR NEW.source_evidence_event_id IS DISTINCT FROM OLD.source_evidence_event_id
                    OR NEW.priority IS DISTINCT FROM OLD.priority
                    OR NEW.instruction IS DISTINCT FROM OLD.instruction
                    OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                    RAISE EXCEPTION 'correction provenance is immutable';
                END IF;
                IF OLD.status IN ('completed', 'dismissed', 'superseded') THEN
                    RAISE EXCEPTION 'terminal correction is immutable';
                END IF;
                IF NEW.status IS DISTINCT FROM OLD.status AND NOT (
                    (OLD.status = 'pending' AND NEW.status IN (
                        'scheduled', 'dismissed', 'superseded'
                    )) OR
                    (OLD.status = 'scheduled' AND NEW.status IN (
                        'completed', 'dismissed', 'superseded'
                    ))
                ) THEN
                    RAISE EXCEPTION 'invalid correction status transition';
                END IF;
                IF OLD.completed_at IS NOT NULL
                    AND NEW.completed_at IS DISTINCT FROM OLD.completed_at THEN
                    RAISE EXCEPTION 'correction completion is write-once';
                END IF;
                IF OLD.attempt_b_activity_id IS NOT NULL
                    AND NEW.attempt_b_activity_id IS DISTINCT FROM OLD.attempt_b_activity_id THEN
                    RAISE EXCEPTION 'correction Attempt B link is write-once';
                END IF;
                IF NEW.updated_at < OLD.updated_at THEN
                    RAISE EXCEPTION 'correction updated_at cannot decrease';
                END IF;
            END IF;
            IF NEW.source_evidence_event_id IS NOT NULL THEN
                SELECT item.activity_instance_id INTO evidence_activity_id
                FROM public.skill_evidence_events AS item
                WHERE item.owner_id = NEW.owner_id
                    AND item.id = NEW.source_evidence_event_id;
                IF evidence_activity_id IS DISTINCT FROM NEW.source_activity_id THEN
                    RAISE EXCEPTION 'correction source evidence does not match activity';
                END IF;
            END IF;
            IF NEW.attempt_b_activity_id IS NOT NULL THEN
                SELECT item.attempt_kind INTO attempt_kind_value
                FROM public.activity_instances AS item
                WHERE item.owner_id = NEW.owner_id
                    AND item.id = NEW.attempt_b_activity_id;
                IF attempt_kind_value IS DISTINCT FROM 'attempt_b' THEN
                    RAISE EXCEPTION 'correction target must be Attempt B';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_corrections_guard_mutation
        BEFORE INSERT OR UPDATE ON corrections
        FOR EACH ROW EXECUTE FUNCTION public.tamforge_guard_correction_mutation()
        """
    )
    op.execute(
        """
        CREATE FUNCTION public.tamforge_guard_processing_status_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            IF TG_OP = 'UPDATE' THEN
                IF NEW.owner_id IS DISTINCT FROM OLD.owner_id
                    OR NEW.activity_instance_id IS DISTINCT FROM OLD.activity_instance_id
                    OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                    RAISE EXCEPTION 'processing status provenance is immutable';
                END IF;
                IF NEW.updated_at < OLD.updated_at THEN
                    RAISE EXCEPTION 'processing updated_at cannot decrease';
                END IF;
                IF NEW.state IS DISTINCT FROM OLD.state AND NOT (
                    (OLD.state = 'uploaded' AND NEW.state IN (
                        'processing_audio', 'needs_attention'
                    )) OR
                    (OLD.state = 'processing_audio' AND NEW.state IN (
                        'transcribing', 'needs_attention'
                    )) OR
                    (OLD.state = 'transcribing' AND NEW.state IN (
                        'analyzing', 'needs_attention'
                    )) OR
                    (OLD.state = 'analyzing' AND NEW.state IN ('ready', 'needs_attention')) OR
                    (OLD.state = 'ready' AND NEW.state = 'analyzing') OR
                    (OLD.state = 'needs_attention' AND NEW.state IN (
                        'processing_audio', 'transcribing', 'analyzing'
                    ))
                ) THEN
                    RAISE EXCEPTION 'invalid processing state transition';
                END IF;
                IF NEW.state = OLD.state AND (
                    NEW.progress_label IS DISTINCT FROM OLD.progress_label
                    OR NEW.last_error_category IS DISTINCT FROM OLD.last_error_category
                    OR NEW.last_error_details IS DISTINCT FROM OLD.last_error_details
                ) THEN
                    RAISE EXCEPTION 'same-state processing update may only advance time';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_activity_processing_statuses_guard_mutation
        BEFORE UPDATE ON activity_processing_statuses
        FOR EACH ROW EXECUTE FUNCTION public.tamforge_guard_processing_status_mutation()
        """
    )
    op.execute(
        """
        CREATE FUNCTION public.tamforge_guard_notification_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            IF NEW.owner_id IS DISTINCT FROM OLD.owner_id
                OR NEW.notification_type IS DISTINCT FROM OLD.notification_type
                OR NEW.subject_kind IS DISTINCT FROM OLD.subject_kind
                OR NEW.subject_id IS DISTINCT FROM OLD.subject_id
                OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                RAISE EXCEPTION 'notification provenance is immutable';
            END IF;
            IF OLD.read_at IS NOT NULL AND NEW.read_at IS DISTINCT FROM OLD.read_at THEN
                RAISE EXCEPTION 'notification read timestamp is write-once';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_notifications_guard_mutation
        BEFORE UPDATE ON notifications
        FOR EACH ROW EXECUTE FUNCTION public.tamforge_guard_notification_mutation()
        """
    )
    op.execute(
        """
        CREATE FUNCTION public.tamforge_guard_outbox_event_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            IF OLD.published_at IS NOT NULL THEN
                RAISE EXCEPTION 'published outbox event is immutable';
            END IF;
            IF NEW.owner_id IS DISTINCT FROM OLD.owner_id
                OR NEW.aggregate_type IS DISTINCT FROM OLD.aggregate_type
                OR NEW.aggregate_id IS DISTINCT FROM OLD.aggregate_id
                OR NEW.event_type IS DISTINCT FROM OLD.event_type
                OR NEW.payload_schema_version IS DISTINCT FROM OLD.payload_schema_version
                OR NEW.payload IS DISTINCT FROM OLD.payload
                OR NEW.occurred_at IS DISTINCT FROM OLD.occurred_at
                OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key THEN
                RAISE EXCEPTION 'outbox provenance is immutable';
            END IF;
            IF NEW.attempts < OLD.attempts OR NEW.attempts > OLD.attempts + 1 THEN
                RAISE EXCEPTION 'outbox attempts must advance by at most one';
            END IF;
            IF OLD.published_at IS NOT NULL
                AND NEW.published_at IS DISTINCT FROM OLD.published_at THEN
                RAISE EXCEPTION 'outbox publication is write-once';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_outbox_events_guard_mutation
        BEFORE UPDATE ON outbox_events
        FOR EACH ROW EXECUTE FUNCTION public.tamforge_guard_outbox_event_mutation()
        """
    )
    op.execute(
        """
        CREATE FUNCTION public.tamforge_guard_background_job_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            IF OLD.state IN ('succeeded', 'failed') THEN
                RAISE EXCEPTION 'terminal background job is immutable';
            END IF;
            IF NEW.owner_id IS DISTINCT FROM OLD.owner_id
                OR NEW.kind IS DISTINCT FROM OLD.kind
                OR NEW.payload_schema_version IS DISTINCT FROM OLD.payload_schema_version
                OR NEW.payload IS DISTINCT FROM OLD.payload
                OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
                OR NEW.max_attempts IS DISTINCT FROM OLD.max_attempts
                OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                RAISE EXCEPTION 'background job provenance is immutable';
            END IF;
            IF NEW.updated_at < OLD.updated_at THEN
                RAISE EXCEPTION 'background job updated_at cannot decrease';
            END IF;
            IF OLD.started_at IS NOT NULL AND NEW.started_at IS DISTINCT FROM OLD.started_at THEN
                RAISE EXCEPTION 'background job started_at is write-once';
            END IF;
            IF OLD.completed_at IS NOT NULL
                AND NEW.completed_at IS DISTINCT FROM OLD.completed_at THEN
                RAISE EXCEPTION 'background job completed_at is write-once';
            END IF;
            IF NEW.state IS DISTINCT FROM OLD.state AND NOT (
                (OLD.state = 'queued' AND NEW.state = 'running') OR
                (OLD.state = 'running' AND NEW.state IN ('queued', 'succeeded', 'failed'))
            ) THEN
                RAISE EXCEPTION 'invalid background job state transition';
            END IF;
            IF OLD.state = 'queued' AND NEW.state = 'running' THEN
                IF NEW.attempt_count <> OLD.attempt_count + 1 THEN
                    RAISE EXCEPTION 'background job claim must increment attempt count';
                END IF;
            ELSIF NEW.attempt_count <> OLD.attempt_count THEN
                RAISE EXCEPTION 'background job attempt changes only on claim';
            END IF;
            IF OLD.state = 'running' AND NEW.state = 'queued'
                AND (
                    OLD.lease_expires_at IS NULL
                    OR OLD.lease_expires_at > CURRENT_TIMESTAMP
                ) THEN
                RAISE EXCEPTION 'background job lease has not expired';
            END IF;
            IF NEW.state = OLD.state AND OLD.state = 'running' AND (
                NEW.priority IS DISTINCT FROM OLD.priority
                OR NEW.available_at IS DISTINCT FROM OLD.available_at
                OR NEW.lease_owner IS DISTINCT FROM OLD.lease_owner
                OR NEW.last_error_category IS DISTINCT FROM OLD.last_error_category
                OR NEW.last_error_details IS DISTINCT FROM OLD.last_error_details
                OR NEW.started_at IS DISTINCT FROM OLD.started_at
                OR NEW.completed_at IS DISTINCT FROM OLD.completed_at
                OR NEW.lease_expires_at < OLD.lease_expires_at
            ) THEN
                RAISE EXCEPTION 'running heartbeat may only extend its lease';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_background_jobs_guard_mutation
        BEFORE UPDATE ON background_jobs
        FOR EACH ROW EXECUTE FUNCTION public.tamforge_guard_background_job_mutation()
        """
    )
    op.execute(
        """
        CREATE FUNCTION public.tamforge_guard_notification_cursor_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            IF NEW.owner_id IS DISTINCT FROM OLD.owner_id
                OR NEW.stream_key IS DISTINCT FROM OLD.stream_key
                OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                RAISE EXCEPTION 'delivery cursor provenance is immutable';
            END IF;
            IF NEW.last_event_id < OLD.last_event_id THEN
                RAISE EXCEPTION 'delivery cursor cannot decrease';
            END IF;
            IF NEW.updated_at < OLD.updated_at THEN
                RAISE EXCEPTION 'delivery cursor updated_at cannot decrease';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_notification_delivery_cursor_guard_mutation
        BEFORE UPDATE ON notification_delivery_cursor
        FOR EACH ROW EXECUTE FUNCTION public.tamforge_guard_notification_cursor_mutation()
        """
    )


def upgrade() -> None:
    _create_validation_functions()
    _create_tables()
    _create_guards()


def downgrade() -> None:
    trigger_functions = (
        (
            "trg_notification_delivery_cursor_guard_mutation",
            "notification_delivery_cursor",
            "tamforge_guard_notification_cursor_mutation",
        ),
        (
            "trg_background_jobs_guard_mutation",
            "background_jobs",
            "tamforge_guard_background_job_mutation",
        ),
        (
            "trg_outbox_events_guard_mutation",
            "outbox_events",
            "tamforge_guard_outbox_event_mutation",
        ),
        (
            "trg_notifications_guard_mutation",
            "notifications",
            "tamforge_guard_notification_mutation",
        ),
        (
            "trg_activity_processing_statuses_guard_mutation",
            "activity_processing_statuses",
            "tamforge_guard_processing_status_mutation",
        ),
        (
            "trg_corrections_guard_mutation",
            "corrections",
            "tamforge_guard_correction_mutation",
        ),
    )
    for trigger_name, table_name, function_name in trigger_functions:
        op.execute(f"DROP TRIGGER IF EXISTS {trigger_name} ON {table_name}")
        op.execute(f"DROP FUNCTION IF EXISTS public.{function_name}()")

    for table_name in (
        "notification_delivery_cursor",
        "background_jobs",
        "outbox_events",
        "notifications",
        "activity_processing_statuses",
        "interviews",
        "corrections",
    ):
        op.drop_table(table_name)

    op.drop_constraint(
        "uq_skill_evidence_events_owner_id_id",
        "skill_evidence_events",
        type_="unique",
    )
    op.execute("DROP FUNCTION IF EXISTS public.tamforge_validate_error_details_v1(jsonb)")
    op.execute("DROP FUNCTION IF EXISTS public.tamforge_validate_reference_payload_v1(jsonb)")

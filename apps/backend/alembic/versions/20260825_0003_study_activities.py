"""Add study activities and immutable learning evidence.

Revision ID: 20260825_0003_study_activities
Revises: 20260825_0002_curriculum
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260825_0003_study_activities"
down_revision: str | None = "20260825_0002_curriculum"
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


def _jsonb(name: str) -> sa.Column[object]:
    return sa.Column(name, postgresql.JSONB(astext_type=sa.Text()), nullable=False)


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION public.tamforge_validate_encryption_metadata_v1(metadata jsonb)
        RETURNS boolean
        LANGUAGE plpgsql
        IMMUTABLE
        PARALLEL SAFE
        SET search_path = pg_catalog
        AS $$
        DECLARE metadata_key text;
        BEGIN
            IF metadata IS NULL OR jsonb_typeof(metadata) <> 'object'
                OR octet_length(metadata::text) > 2048
                OR NOT metadata ?& ARRAY[
                    'schema_version', 'encrypted', 'algorithm', 'key_reference'
                ] THEN
                RETURN false;
            END IF;
            FOR metadata_key IN SELECT jsonb_object_keys(metadata) LOOP
                IF metadata_key <> ALL (ARRAY[
                    'schema_version', 'encrypted', 'algorithm', 'key_reference'
                ]) THEN
                    RETURN false;
                END IF;
            END LOOP;
            IF jsonb_typeof(metadata->'schema_version') <> 'number'
                OR metadata->>'schema_version' <> '1'
                OR jsonb_typeof(metadata->'encrypted') <> 'boolean' THEN
                RETURN false;
            END IF;
            IF (metadata->>'encrypted')::boolean = false THEN
                RETURN jsonb_typeof(metadata->'algorithm') = 'null'
                    AND jsonb_typeof(metadata->'key_reference') = 'null';
            END IF;
            RETURN jsonb_typeof(metadata->'algorithm') = 'string'
                AND metadata->>'algorithm' IN ('aes_256_gcm', 'sse_s3', 'sse_kms')
                AND jsonb_typeof(metadata->'key_reference') = 'string'
                AND octet_length(metadata->>'key_reference') BETWEEN 1 AND 256
                AND metadata->>'key_reference' ~ '^[A-Za-z0-9][A-Za-z0-9_.:/-]*$'
                AND lower(metadata->>'key_reference') !~
                    '(password|secret|token|api[_-]?key|bearer)';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION public.tamforge_validate_evidence_manifest_v1(manifest jsonb)
        RETURNS boolean
        LANGUAGE plpgsql
        IMMUTABLE
        PARALLEL SAFE
        SET search_path = pg_catalog
        AS $$
        DECLARE manifest_key text;
        DECLARE item jsonb;
        DECLARE array_key text;
        BEGIN
            IF manifest IS NULL OR jsonb_typeof(manifest) <> 'object'
                OR octet_length(manifest::text) > 16384
                OR NOT manifest ? 'schema_version'
                OR jsonb_typeof(manifest->'schema_version') <> 'number'
                OR manifest->>'schema_version' <> '1' THEN
                RETURN false;
            END IF;
            FOR manifest_key IN SELECT jsonb_object_keys(manifest) LOOP
                IF manifest_key <> ALL (ARRAY[
                    'schema_version', 'activity_ids', 'attempt_ids',
                    'artifact_ids', 'self_review_ids'
                ]) THEN
                    RETURN false;
                END IF;
            END LOOP;
            FOREACH array_key IN ARRAY ARRAY[
                'activity_ids', 'attempt_ids', 'artifact_ids', 'self_review_ids'
            ] LOOP
                IF manifest ? array_key THEN
                    IF jsonb_typeof(manifest->array_key) <> 'array'
                        OR jsonb_array_length(manifest->array_key) > 64 THEN
                        RETURN false;
                    END IF;
                    FOR item IN SELECT value FROM jsonb_array_elements(manifest->array_key) LOOP
                        IF jsonb_typeof(item) <> 'number'
                            OR item::text !~ '^[1-9][0-9]{0,18}$' THEN
                            RETURN false;
                        END IF;
                    END LOOP;
                END IF;
            END LOOP;
            RETURN true;
        END;
        $$
        """
    )

    op.create_table(
        "learner_settings",
        _id(),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("timezone", sa.Text(), nullable=False),
        sa.Column("study_start_date", sa.Date(), nullable=False),
        sa.Column("active_roadmap_version_id", sa.BigInteger(), nullable=True),
        _created(),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "octet_length(timezone) BETWEEN 3 AND 64 "
            "AND timezone ~ '^[A-Za-z][A-Za-z0-9_+-]*/[A-Za-z0-9_+./-]+$' "
            "AND timezone !~ '\\.\\.'",
            name="timezone_iana_shape",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name="fk_learner_settings_owner_id_owners",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "active_roadmap_version_id"],
            ["roadmap_versions.owner_id", "roadmap_versions.id"],
            name="fk_learner_settings_owner_active_version_roadmap_versions",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_learner_settings"),
        sa.UniqueConstraint("owner_id", name="uq_learner_settings_owner_id"),
    )
    op.create_index(
        "ix_learner_settings_owner_active_version",
        "learner_settings",
        ["owner_id", "active_roadmap_version_id"],
    )

    op.create_table(
        "study_days",
        _id(),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("roadmap_version_id", sa.BigInteger(), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("planned_minutes", sa.Integer(), nullable=False),
        sa.Column("focused_minutes", sa.Integer(), server_default="0", nullable=False),
        sa.Column("day_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        _created(),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "planned_minutes BETWEEN 0 AND 255 AND focused_minutes BETWEEN 0 AND 255",
            name="minutes_bounded",
        ),
        sa.CheckConstraint(
            "day_type IN ('weekday', 'saturday', 'sunday', 'interview')",
            name="day_type_allowed",
        ),
        sa.CheckConstraint(
            "(day_type = 'sunday' AND planned_minutes = 0) OR "
            "(day_type = 'saturday' AND planned_minutes <= 120) OR "
            "day_type IN ('weekday', 'interview')",
            name="day_minutes_coherent",
        ),
        sa.CheckConstraint(
            "status IN ('planned', 'in_progress', 'closed', 'incomplete', 'skipped')",
            name="status_allowed",
        ),
        sa.CheckConstraint(
            "started_at IS NULL OR started_at >= created_at", name="started_after_creation"
        ),
        sa.CheckConstraint(
            "closed_at IS NULL OR closed_at >= COALESCE(started_at, created_at)",
            name="closed_after_start",
        ),
        sa.CheckConstraint(
            "(status = 'planned' AND started_at IS NULL AND closed_at IS NULL) OR "
            "(status = 'in_progress' AND started_at IS NOT NULL AND closed_at IS NULL) OR "
            "(status IN ('closed', 'incomplete') AND started_at IS NOT NULL "
            "AND closed_at IS NOT NULL) OR "
            "(status = 'skipped' AND closed_at IS NOT NULL)",
            name="lifecycle_coherent",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "roadmap_version_id"],
            ["roadmap_versions.owner_id", "roadmap_versions.id"],
            name="fk_study_days_owner_version_roadmap_versions",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_study_days"),
        sa.UniqueConstraint("owner_id", "local_date", name="uq_study_days_owner_local_date"),
        sa.UniqueConstraint(
            "owner_id",
            "roadmap_version_id",
            "id",
            name="uq_study_days_owner_version_id_id",
        ),
    )
    op.create_index("ix_study_days_owner_local_date", "study_days", ["owner_id", "local_date"])
    op.create_index("ix_study_days_owner_version", "study_days", ["owner_id", "roadmap_version_id"])
    op.create_index("ix_study_days_status_local_date", "study_days", ["status", "local_date"])

    op.create_table(
        "activity_instances",
        _id(),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("study_day_id", sa.BigInteger(), nullable=False),
        sa.Column("roadmap_version_id", sa.BigInteger(), nullable=False),
        sa.Column("task_definition_id", sa.BigInteger(), nullable=False),
        sa.Column("task_stable_id_snapshot", sa.Text(), nullable=False),
        sa.Column("task_mapping_version_snapshot", sa.Text(), nullable=False),
        sa.Column("task_objective_snapshot", sa.Text(), nullable=False),
        sa.Column("task_timebox_minutes_snapshot", sa.Integer(), nullable=False),
        sa.Column("roadmap_version_key_snapshot", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("attempt_kind", sa.Text(), nullable=False),
        sa.Column("assistance_mode", sa.Text(), nullable=False),
        sa.Column("classification", sa.Text(), nullable=False),
        sa.Column("timebox_minutes", sa.Integer(), nullable=False),
        sa.Column("source_hidden", sa.Boolean(), nullable=False),
        sa.Column("optimistic_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("replacement_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("replaces_activity_id", sa.BigInteger(), nullable=True),
        _created(),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("output_committed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "btrim(task_stable_id_snapshot) <> '' AND octet_length(task_stable_id_snapshot) <= 192",
            name="task_stable_id_snapshot_bounded",
        ),
        sa.CheckConstraint(
            "btrim(task_mapping_version_snapshot) <> '' "
            "AND octet_length(task_mapping_version_snapshot) <= 64",
            name="task_mapping_version_snapshot_bounded",
        ),
        sa.CheckConstraint(
            "btrim(task_objective_snapshot) <> '' "
            "AND octet_length(task_objective_snapshot) <= 4096",
            name="task_objective_snapshot_bounded",
        ),
        sa.CheckConstraint(
            "task_timebox_minutes_snapshot > 0", name="task_timebox_snapshot_positive"
        ),
        sa.CheckConstraint(
            "btrim(roadmap_version_key_snapshot) <> '' "
            "AND octet_length(roadmap_version_key_snapshot) <= 128",
            name="roadmap_version_key_snapshot_bounded",
        ),
        sa.CheckConstraint(
            "state IN ('ready', 'active', 'output_committed', 'self_review_complete', "
            "'ai_processing', 'feedback_ready', 'correction_due', 'demonstrated', "
            "'needs_work', 'incomplete', 'superseded')",
            name="state_allowed",
        ),
        sa.CheckConstraint(
            "attempt_kind IN ('none', 'attempt_a', 'attempt_b', "
            "'no_ai_assessment', 'real_interview')",
            name="attempt_kind_allowed",
        ),
        sa.CheckConstraint(
            "assistance_mode IN ('none', 'coach_preparation', 'hint_ladder', "
            "'time_expired', 'reference_only')",
            name="assistance_mode_allowed",
        ),
        sa.CheckConstraint(
            "classification IN ('required', 'useful', 'optional', 'superseded')",
            name="classification_allowed",
        ),
        sa.CheckConstraint(
            "timebox_minutes > 0 AND timebox_minutes <= 255", name="timebox_bounded"
        ),
        sa.CheckConstraint("optimistic_version > 0", name="optimistic_version_positive"),
        sa.CheckConstraint("replacement_version > 0", name="replacement_version_positive"),
        sa.CheckConstraint(
            "(replacement_version = 1 AND replaces_activity_id IS NULL) OR "
            "(replacement_version > 1 AND replaces_activity_id IS NOT NULL)",
            name="replacement_coherent",
        ),
        sa.CheckConstraint(
            "started_at IS NULL OR started_at >= created_at", name="started_after_creation"
        ),
        sa.CheckConstraint(
            "output_committed_at IS NULL OR output_committed_at >= started_at",
            name="output_committed_after_start",
        ),
        sa.CheckConstraint(
            "completed_at IS NULL OR completed_at >= "
            "COALESCE(output_committed_at, started_at, created_at)",
            name="completed_after_progress",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "roadmap_version_id", "study_day_id"],
            ["study_days.owner_id", "study_days.roadmap_version_id", "study_days.id"],
            name="fk_activity_instances_owner_version_day_study_days",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "roadmap_version_id", "task_definition_id"],
            [
                "task_definitions.owner_id",
                "task_definitions.roadmap_version_id",
                "task_definitions.id",
            ],
            name="fk_activity_instances_owner_version_task_task_definitions",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "study_day_id", "task_definition_id", "replaces_activity_id"],
            [
                "activity_instances.owner_id",
                "activity_instances.study_day_id",
                "activity_instances.task_definition_id",
                "activity_instances.id",
            ],
            name="fk_activity_instances_replacement_same_day_task",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_activity_instances"),
        sa.UniqueConstraint("owner_id", "id", name="uq_activity_instances_owner_id_id"),
        sa.UniqueConstraint(
            "owner_id",
            "study_day_id",
            "id",
            name="uq_activity_instances_owner_study_id_id",
        ),
        sa.UniqueConstraint(
            "owner_id",
            "study_day_id",
            "task_definition_id",
            "id",
            name="uq_activity_instances_owner_study_task_id",
        ),
        sa.UniqueConstraint(
            "owner_id",
            "study_day_id",
            "task_definition_id",
            "replacement_version",
            name="uq_activity_instances_owner_study_task_replacement",
        ),
    )
    op.create_index(
        "ix_activity_instances_owner_study_order",
        "activity_instances",
        ["owner_id", "study_day_id", "id"],
    )
    op.create_index(
        "ix_activity_instances_owner_version_day",
        "activity_instances",
        ["owner_id", "roadmap_version_id", "study_day_id"],
    )
    op.create_index(
        "ix_activity_instances_owner_version_task",
        "activity_instances",
        ["owner_id", "roadmap_version_id", "task_definition_id"],
    )
    op.create_index(
        "ix_activity_instances_owner_study_task_replaces",
        "activity_instances",
        ["owner_id", "study_day_id", "task_definition_id", "replaces_activity_id"],
    )
    op.create_index("ix_activity_instances_state", "activity_instances", ["state"])
    op.create_index(
        "ix_activity_instances_pending_self_review",
        "activity_instances",
        ["owner_id", "output_committed_at"],
        postgresql_where=sa.text("state = 'output_committed'"),
    )
    op.create_table(
        "activity_timer_sessions",
        _id(),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("activity_instance_id", sa.BigInteger(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("counted_seconds", sa.Integer(), server_default="0", nullable=False),
        sa.CheckConstraint("btrim(idempotency_key) <> ''", name="idempotency_key_nonblank"),
        sa.CheckConstraint("octet_length(idempotency_key) <= 256", name="idempotency_key_bounded"),
        sa.CheckConstraint("counted_seconds BETWEEN 0 AND 918000", name="counted_seconds_bounded"),
        sa.CheckConstraint(
            "last_heartbeat_at >= started_at "
            "AND (paused_at IS NULL OR paused_at >= started_at) "
            "AND (ended_at IS NULL OR ended_at >= "
            "COALESCE(paused_at, last_heartbeat_at, started_at)) "
            "AND (ended_at IS NULL OR last_heartbeat_at <= ended_at)",
            name="timestamps_coherent",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "activity_instance_id"],
            ["activity_instances.owner_id", "activity_instances.id"],
            name="fk_activity_timer_sessions_owner_activity_activity_instances",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_activity_timer_sessions"),
        sa.UniqueConstraint(
            "owner_id",
            "idempotency_key",
            name="uq_activity_timer_sessions_owner_idempotency",
        ),
    )
    op.create_index(
        "ix_activity_timer_sessions_owner_activity",
        "activity_timer_sessions",
        ["owner_id", "activity_instance_id"],
    )
    op.create_index(
        "uq_activity_timer_sessions_one_open_per_activity",
        "activity_timer_sessions",
        ["activity_instance_id"],
        unique=True,
        postgresql_where=sa.text("ended_at IS NULL"),
    )

    op.create_table(
        "attempts",
        _id(),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("activity_instance_id", sa.BigInteger(), nullable=False),
        sa.Column("attempt_kind", sa.Text(), nullable=False),
        sa.Column("parent_attempt_id", sa.BigInteger(), nullable=True),
        sa.Column("original_text", sa.Text(), nullable=True),
        sa.Column("original_markdown", sa.Text(), nullable=True),
        sa.Column("original_sql", sa.Text(), nullable=True),
        sa.Column("audience", sa.Text(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("assistance_mode", sa.Text(), nullable=False),
        sa.Column("commitment_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=False),
        _created(),
        sa.CheckConstraint(
            "attempt_kind IN ('attempt_a', 'attempt_b', 'no_ai_assessment', 'real_interview')",
            name="attempt_kind_allowed",
        ),
        sa.CheckConstraint(
            "(attempt_kind = 'attempt_b' AND parent_attempt_id IS NOT NULL) OR "
            "(attempt_kind <> 'attempt_b' AND parent_attempt_id IS NULL)",
            name="ab_relation_coherent",
        ),
        sa.CheckConstraint(
            "num_nonnulls(original_text, original_markdown, original_sql) >= 1",
            name="original_payload_present",
        ),
        sa.CheckConstraint(
            "(original_text IS NULL OR (btrim(original_text) <> '' "
            "AND octet_length(original_text) <= 4194304)) "
            "AND (original_markdown IS NULL OR (btrim(original_markdown) <> '' "
            "AND octet_length(original_markdown) <= 4194304)) "
            "AND (original_sql IS NULL OR (btrim(original_sql) <> '' "
            "AND octet_length(original_sql) <= 4194304))",
            name="original_payload_bounded",
        ),
        sa.CheckConstraint(
            "btrim(audience) <> '' AND octet_length(audience) <= 256", name="audience_bounded"
        ),
        sa.CheckConstraint(
            "btrim(prompt) <> '' AND octet_length(prompt) <= 1048576", name="prompt_bounded"
        ),
        sa.CheckConstraint(
            "assistance_mode IN ('none', 'coach_preparation', 'hint_ladder', "
            "'time_expired', 'reference_only')",
            name="assistance_mode_allowed",
        ),
        sa.CheckConstraint("octet_length(commitment_hash) = 32", name="commitment_hash_length"),
        sa.CheckConstraint("committed_at >= created_at", name="committed_after_creation"),
        sa.ForeignKeyConstraint(
            ["owner_id", "activity_instance_id"],
            ["activity_instances.owner_id", "activity_instances.id"],
            name="fk_attempts_owner_activity_activity_instances",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "parent_attempt_id"],
            ["attempts.owner_id", "attempts.id"],
            name="fk_attempts_owner_parent_attempts",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_attempts"),
        sa.UniqueConstraint("owner_id", "id", name="uq_attempts_owner_id_id"),
        sa.UniqueConstraint(
            "owner_id",
            "activity_instance_id",
            "id",
            name="uq_attempts_owner_activity_id_id",
        ),
        sa.UniqueConstraint(
            "owner_id",
            "activity_instance_id",
            "attempt_kind",
            name="uq_attempts_owner_activity_kind",
        ),
    )
    op.create_index("ix_attempts_owner_activity", "attempts", ["owner_id", "activity_instance_id"])
    op.create_index("ix_attempts_owner_parent", "attempts", ["owner_id", "parent_attempt_id"])

    op.create_table(
        "artifacts",
        _id(),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("artifact_class", sa.Text(), nullable=False),
        _jsonb("encryption_metadata"),
        sa.Column("derived_from_artifact_id", sa.BigInteger(), nullable=True),
        sa.Column("immutable_version", sa.Integer(), nullable=False),
        _created(),
        sa.CheckConstraint("btrim(object_key) <> ''", name="object_key_nonblank"),
        sa.CheckConstraint(
            "octet_length(object_key) <= 1024 AND object_key !~ '^[a-z][a-z0-9+.-]*://' "
            "AND object_key !~ '(^|/)\\.\\.(/|$)' AND object_key !~ '[[:cntrl:]]'",
            name="object_key_private_bounded",
        ),
        sa.CheckConstraint("octet_length(content_hash) = 32", name="content_hash_length"),
        sa.CheckConstraint(
            "content_type ~ '^[a-z0-9][a-z0-9.+-]*/[a-z0-9][a-z0-9.+-]*$' "
            "AND octet_length(content_type) <= 128",
            name="content_type_safe",
        ),
        sa.CheckConstraint(
            "btrim(original_filename) <> '' AND octet_length(original_filename) <= 512 "
            "AND original_filename !~ '[/\\\\]' AND original_filename !~ '[[:cntrl:]]'",
            name="original_filename_safe",
        ),
        sa.CheckConstraint("byte_size >= 0", name="byte_size_nonnegative"),
        sa.CheckConstraint(
            "artifact_class IN ('original_audio', 'transcript', 'written_output', "
            "'sql_output', 'recall_note', 'case_artifact', 'analysis', 'export')",
            name="artifact_class_allowed",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(encryption_metadata) = 'object' "
            "AND octet_length(encryption_metadata::text) <= 2048",
            name="encryption_metadata_object",
        ),
        sa.CheckConstraint(
            "public.tamforge_validate_encryption_metadata_v1(encryption_metadata)",
            name="encryption_metadata_v1",
        ),
        sa.CheckConstraint("immutable_version > 0", name="immutable_version_positive"),
        sa.CheckConstraint(
            "derived_from_artifact_id IS NULL OR derived_from_artifact_id <> id",
            name="lineage_not_self",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name="fk_artifacts_owner_id_owners",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "derived_from_artifact_id"],
            ["artifacts.owner_id", "artifacts.id"],
            name="fk_artifacts_owner_derived_from_artifacts",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_artifacts"),
        sa.UniqueConstraint("owner_id", "id", name="uq_artifacts_owner_id_id"),
        sa.UniqueConstraint("owner_id", "object_key", name="uq_artifacts_owner_object_key"),
        sa.UniqueConstraint("owner_id", "content_hash", name="uq_artifacts_owner_content_hash"),
    )
    op.create_index(
        "ix_artifacts_owner_derived_from", "artifacts", ["owner_id", "derived_from_artifact_id"]
    )
    op.create_index(
        "ix_artifacts_owner_class_created",
        "artifacts",
        ["owner_id", "artifact_class", "created_at"],
    )

    op.create_table(
        "activity_artifact_links",
        _id(),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("activity_instance_id", sa.BigInteger(), nullable=False),
        sa.Column("attempt_id", sa.BigInteger(), nullable=True),
        sa.Column("artifact_id", sa.BigInteger(), nullable=False),
        sa.Column("link_role", sa.Text(), nullable=False),
        _created(),
        sa.CheckConstraint(
            "link_role IN ('original_output', 'presentation_audio', 'transcript', "
            "'analysis', 'supporting', 'correction')",
            name="role_allowed",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "activity_instance_id"],
            ["activity_instances.owner_id", "activity_instances.id"],
            name="fk_activity_artifact_links_owner_activity_activity_instances",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "activity_instance_id", "attempt_id"],
            ["attempts.owner_id", "attempts.activity_instance_id", "attempts.id"],
            name="fk_activity_artifact_links_owner_activity_attempt_attempts",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "artifact_id"],
            ["artifacts.owner_id", "artifacts.id"],
            name="fk_activity_artifact_links_owner_artifact_artifacts",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_activity_artifact_links"),
        sa.UniqueConstraint(
            "owner_id",
            "activity_instance_id",
            "attempt_id",
            "artifact_id",
            "link_role",
            name="uq_activity_artifact_links_binding",
        ),
    )
    op.create_index(
        "ix_activity_artifact_links_owner_activity",
        "activity_artifact_links",
        ["owner_id", "activity_instance_id"],
    )
    op.create_index(
        "ix_activity_artifact_links_owner_activity_attempt",
        "activity_artifact_links",
        ["owner_id", "activity_instance_id", "attempt_id"],
    )
    op.create_index(
        "ix_activity_artifact_links_owner_artifact",
        "activity_artifact_links",
        ["owner_id", "artifact_id"],
    )

    op.create_table(
        "self_reviews",
        _id(),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("activity_instance_id", sa.BigInteger(), nullable=False),
        sa.Column("attempt_id", sa.BigInteger(), nullable=False),
        sa.Column("main_answer", sa.Text(), nullable=False),
        sa.Column("did_well", sa.Text(), nullable=False),
        sa.Column("structure_weakness", sa.Text(), nullable=False),
        sa.Column("vague_points", sa.Text(), nullable=False),
        sa.Column("hesitation_points", sa.Text(), nullable=False),
        sa.Column("change_next", sa.Text(), nullable=False),
        sa.Column("self_score", sa.Integer(), nullable=False),
        _created("submitted_at"),
        sa.CheckConstraint(
            "btrim(main_answer) <> '' AND octet_length(main_answer) <= 8192 "
            "AND btrim(did_well) <> '' AND octet_length(did_well) <= 8192 "
            "AND btrim(structure_weakness) <> '' AND octet_length(structure_weakness) <= 8192 "
            "AND btrim(vague_points) <> '' AND octet_length(vague_points) <= 8192 "
            "AND btrim(hesitation_points) <> '' AND octet_length(hesitation_points) <= 8192 "
            "AND btrim(change_next) <> '' AND octet_length(change_next) <= 8192",
            name="answers_required_bounded",
        ),
        sa.CheckConstraint("self_score BETWEEN 0 AND 4", name="score_range"),
        sa.ForeignKeyConstraint(
            ["owner_id", "activity_instance_id", "attempt_id"],
            ["attempts.owner_id", "attempts.activity_instance_id", "attempts.id"],
            name="fk_self_reviews_owner_activity_attempt_attempts",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_self_reviews"),
        sa.UniqueConstraint(
            "owner_id",
            "activity_instance_id",
            "attempt_id",
            name="uq_self_reviews_owner_activity_attempt",
        ),
    )
    op.create_index(
        "ix_self_reviews_owner_activity_attempt",
        "self_reviews",
        ["owner_id", "activity_instance_id", "attempt_id"],
    )
    op.create_index("ix_self_reviews_owner_submitted", "self_reviews", ["owner_id", "submitted_at"])

    op.create_table(
        "adaptive_changes",
        _id(),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("roadmap_version_id", sa.BigInteger(), nullable=False),
        sa.Column("study_day_id", sa.BigInteger(), nullable=False),
        sa.Column("activity_instance_id", sa.BigInteger(), nullable=True),
        sa.Column("what_changed", sa.Text(), nullable=False),
        sa.Column("why_changed", sa.Text(), nullable=False),
        _jsonb("evidence_manifest"),
        sa.Column("roadmap_objective", sa.Text(), nullable=False),
        sa.Column("coverage_impact", sa.Text(), nullable=False),
        sa.Column("affects_required_coverage", sa.Boolean(), nullable=False),
        sa.Column("time_impact", sa.Text(), nullable=False),
        sa.Column("planned_time_delta_minutes", sa.Integer(), nullable=False),
        _created(),
        sa.CheckConstraint(
            "btrim(what_changed) <> '' AND octet_length(what_changed) <= 4096", name="what_bounded"
        ),
        sa.CheckConstraint(
            "btrim(why_changed) <> '' AND octet_length(why_changed) <= 4096", name="why_bounded"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(evidence_manifest) = 'object' "
            "AND octet_length(evidence_manifest::text) <= 16384",
            name="evidence_manifest_object",
        ),
        sa.CheckConstraint(
            "public.tamforge_validate_evidence_manifest_v1(evidence_manifest)",
            name="evidence_manifest_v1",
        ),
        sa.CheckConstraint(
            "btrim(roadmap_objective) <> '' AND octet_length(roadmap_objective) <= 4096",
            name="roadmap_objective_bounded",
        ),
        sa.CheckConstraint(
            "coverage_impact IN ('none', 'rescheduled_required', "
            "'replaced_adaptive', 'reduced_optional')",
            name="coverage_impact_allowed",
        ),
        sa.CheckConstraint(
            "(coverage_impact = 'none' AND affects_required_coverage = false) "
            "OR coverage_impact <> 'none'",
            name="coverage_impact_coherent",
        ),
        sa.CheckConstraint(
            "time_impact IN ('none', 'reallocated', 'reduced', 'increased')",
            name="time_impact_allowed",
        ),
        sa.CheckConstraint(
            "(time_impact = 'none' AND planned_time_delta_minutes = 0) OR "
            "(time_impact = 'reallocated' AND planned_time_delta_minutes = 0) OR "
            "(time_impact = 'reduced' AND planned_time_delta_minutes BETWEEN -255 AND -1) OR "
            "(time_impact = 'increased' AND planned_time_delta_minutes BETWEEN 1 AND 255)",
            name="time_impact_coherent",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "roadmap_version_id", "study_day_id"],
            ["study_days.owner_id", "study_days.roadmap_version_id", "study_days.id"],
            name="fk_adaptive_changes_owner_version_day_study_days",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "study_day_id", "activity_instance_id"],
            [
                "activity_instances.owner_id",
                "activity_instances.study_day_id",
                "activity_instances.id",
            ],
            name="fk_adaptive_changes_owner_day_activity_activity_instances",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_adaptive_changes"),
    )
    op.create_index(
        "ix_adaptive_changes_owner_study",
        "adaptive_changes",
        ["owner_id", "roadmap_version_id", "study_day_id"],
    )
    op.create_index(
        "ix_adaptive_changes_owner_day_activity",
        "adaptive_changes",
        ["owner_id", "study_day_id", "activity_instance_id"],
    )

    op.create_table(
        "daily_closes",
        _id(),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("roadmap_version_id", sa.BigInteger(), nullable=False),
        sa.Column("study_day_id", sa.BigInteger(), nullable=False),
        sa.Column("evidence_confirmed", sa.Boolean(), nullable=False),
        _jsonb("evidence_manifest"),
        sa.Column("strongest_output", sa.Text(), nullable=False),
        sa.Column("repeated_mistake", sa.Text(), nullable=False),
        sa.Column("unfinished_classification", sa.Text(), nullable=False),
        sa.Column("unfinished_requirement", sa.Text(), nullable=True),
        sa.Column("correction_count", sa.Integer(), nullable=False),
        _created("closed_at"),
        sa.CheckConstraint(
            "jsonb_typeof(evidence_manifest) = 'object' "
            "AND octet_length(evidence_manifest::text) <= 16384",
            name="evidence_manifest_object",
        ),
        sa.CheckConstraint(
            "public.tamforge_validate_evidence_manifest_v1(evidence_manifest)",
            name="evidence_manifest_v1",
        ),
        sa.CheckConstraint(
            "btrim(strongest_output) <> '' AND octet_length(strongest_output) <= 4096",
            name="strongest_output_bounded",
        ),
        sa.CheckConstraint(
            "btrim(repeated_mistake) <> '' AND octet_length(repeated_mistake) <= 4096",
            name="repeated_mistake_bounded",
        ),
        sa.CheckConstraint(
            "unfinished_classification IN ('none', 'required', 'useful', 'optional', 'superseded')",
            name="unfinished_classification_allowed",
        ),
        sa.CheckConstraint(
            "(unfinished_classification = 'none' AND unfinished_requirement IS NULL) OR "
            "(unfinished_classification <> 'none' AND unfinished_requirement IS NOT NULL "
            "AND btrim(unfinished_requirement) <> '' "
            "AND octet_length(unfinished_requirement) <= 4096)",
            name="unfinished_requirement_coherent",
        ),
        sa.CheckConstraint("correction_count BETWEEN 0 AND 2", name="correction_count_range"),
        sa.ForeignKeyConstraint(
            ["owner_id", "roadmap_version_id", "study_day_id"],
            ["study_days.owner_id", "study_days.roadmap_version_id", "study_days.id"],
            name="fk_daily_closes_owner_version_day_study_days",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_daily_closes"),
        sa.UniqueConstraint("owner_id", "study_day_id", name="uq_daily_closes_owner_study_day"),
    )
    op.create_index(
        "ix_daily_closes_owner_study",
        "daily_closes",
        ["owner_id", "roadmap_version_id", "study_day_id"],
    )
    op.create_index("ix_daily_closes_owner_closed", "daily_closes", ["owner_id", "closed_at"])

    op.execute(
        """
        CREATE FUNCTION public.tamforge_guard_study_day_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NEW.status <> 'planned' OR NEW.focused_minutes <> 0
                    OR NEW.started_at IS NOT NULL OR NEW.closed_at IS NOT NULL THEN
                    RAISE EXCEPTION 'study day must begin planned';
                END IF;
                RETURN NEW;
            END IF;
            IF TG_OP <> 'UPDATE' THEN
                RAISE EXCEPTION 'study day history is immutable';
            END IF;
            IF ROW(
                NEW.owner_id, NEW.roadmap_version_id, NEW.local_date,
                NEW.planned_minutes, NEW.day_type, NEW.created_at
            ) IS DISTINCT FROM ROW(
                OLD.owner_id, OLD.roadmap_version_id, OLD.local_date,
                OLD.planned_minutes, OLD.day_type, OLD.created_at
            ) THEN
                RAISE EXCEPTION 'study day provenance is immutable';
            END IF;
            IF NEW.focused_minutes < OLD.focused_minutes THEN
                RAISE EXCEPTION 'focused minutes cannot decrease';
            END IF;
            IF NOT (
                (OLD.status = 'planned' AND NEW.status IN ('in_progress', 'skipped'))
                OR (OLD.status = 'in_progress' AND NEW.status IN ('closed', 'incomplete'))
            ) THEN
                RAISE EXCEPTION 'invalid study day status transition';
            END IF;
            IF OLD.started_at IS NOT NULL
                    AND NEW.started_at IS DISTINCT FROM OLD.started_at
                OR OLD.closed_at IS NOT NULL
                    AND NEW.closed_at IS DISTINCT FROM OLD.closed_at THEN
                RAISE EXCEPTION 'study day lifecycle timestamps are write-once';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_study_days_guard_insert
        BEFORE INSERT ON study_days
        FOR EACH ROW EXECUTE FUNCTION public.tamforge_guard_study_day_mutation()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_study_days_guard_mutation
        BEFORE UPDATE OR DELETE ON study_days
        FOR EACH ROW EXECUTE FUNCTION public.tamforge_guard_study_day_mutation()
        """
    )

    op.execute(
        """
        CREATE FUNCTION public.tamforge_guard_activity_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        DECLARE prior_replacement_version integer;
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NEW.state <> 'ready' OR NEW.started_at IS NOT NULL
                    OR NEW.output_committed_at IS NOT NULL OR NEW.completed_at IS NOT NULL THEN
                    RAISE EXCEPTION 'activity must begin ready';
                END IF;
                IF NEW.replaces_activity_id IS NOT NULL THEN
                    SELECT replacement_version INTO prior_replacement_version
                    FROM public.activity_instances
                    WHERE owner_id = NEW.owner_id
                        AND study_day_id = NEW.study_day_id
                        AND task_definition_id = NEW.task_definition_id
                        AND id = NEW.replaces_activity_id
                    FOR UPDATE;
                    IF prior_replacement_version IS NULL
                        OR NEW.replacement_version <> prior_replacement_version + 1 THEN
                        RAISE EXCEPTION 'invalid activity replacement lineage';
                    END IF;
                END IF;
                RETURN NEW;
            END IF;
            IF TG_OP <> 'UPDATE' THEN
                RAISE EXCEPTION 'activity history is immutable';
            END IF;
            IF ROW(
                NEW.owner_id, NEW.study_day_id, NEW.roadmap_version_id,
                NEW.task_definition_id, NEW.task_stable_id_snapshot,
                NEW.task_mapping_version_snapshot, NEW.task_objective_snapshot,
                NEW.task_timebox_minutes_snapshot, NEW.roadmap_version_key_snapshot,
                NEW.attempt_kind, NEW.assistance_mode, NEW.classification,
                NEW.timebox_minutes, NEW.source_hidden, NEW.replacement_version,
                NEW.replaces_activity_id, NEW.created_at
            ) IS DISTINCT FROM ROW(
                OLD.owner_id, OLD.study_day_id, OLD.roadmap_version_id,
                OLD.task_definition_id, OLD.task_stable_id_snapshot,
                OLD.task_mapping_version_snapshot, OLD.task_objective_snapshot,
                OLD.task_timebox_minutes_snapshot, OLD.roadmap_version_key_snapshot,
                OLD.attempt_kind, OLD.assistance_mode, OLD.classification,
                OLD.timebox_minutes, OLD.source_hidden, OLD.replacement_version,
                OLD.replaces_activity_id, OLD.created_at
            ) THEN
                RAISE EXCEPTION 'activity provenance is immutable';
            END IF;
            IF NEW.optimistic_version <> OLD.optimistic_version + 1 THEN
                RAISE EXCEPTION 'optimistic version must increase by one';
            END IF;
            IF NOT (
                (OLD.state = 'ready' AND NEW.state IN ('active', 'incomplete', 'superseded'))
                OR (OLD.state = 'active' AND NEW.state IN ('output_committed', 'incomplete'))
                OR (OLD.state = 'output_committed' AND NEW.state = 'self_review_complete')
                OR (OLD.state = 'self_review_complete'
                    AND NEW.state IN ('ai_processing', 'feedback_ready'))
                OR (OLD.state = 'ai_processing' AND NEW.state IN ('feedback_ready', 'needs_work'))
                OR (OLD.state = 'feedback_ready'
                    AND NEW.state IN ('correction_due', 'demonstrated', 'needs_work'))
                OR (OLD.state = 'correction_due' AND NEW.state IN ('demonstrated', 'needs_work'))
            ) THEN
                RAISE EXCEPTION 'invalid activity state transition';
            END IF;
            IF OLD.started_at IS NOT NULL AND NEW.started_at IS DISTINCT FROM OLD.started_at
                OR OLD.output_committed_at IS NOT NULL
                    AND NEW.output_committed_at IS DISTINCT FROM OLD.output_committed_at
                OR OLD.completed_at IS NOT NULL
                    AND NEW.completed_at IS DISTINCT FROM OLD.completed_at THEN
                RAISE EXCEPTION 'activity lifecycle timestamps are write-once';
            END IF;
            IF NEW.state = 'active' AND (
                NEW.started_at IS NULL OR NEW.output_committed_at IS NOT NULL
                OR NEW.completed_at IS NOT NULL
            ) OR NEW.state IN (
                'output_committed', 'self_review_complete', 'ai_processing',
                'feedback_ready', 'correction_due', 'demonstrated', 'needs_work'
            ) AND (NEW.started_at IS NULL OR NEW.output_committed_at IS NULL) THEN
                RAISE EXCEPTION 'activity lifecycle timestamps are incoherent';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_activity_instances_guard_insert
        BEFORE INSERT ON activity_instances
        FOR EACH ROW EXECUTE FUNCTION public.tamforge_guard_activity_mutation()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_activity_instances_guard_mutation
        BEFORE UPDATE OR DELETE ON activity_instances
        FOR EACH ROW EXECUTE FUNCTION public.tamforge_guard_activity_mutation()
        """
    )

    op.execute(
        """
        CREATE FUNCTION public.tamforge_guard_timer_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            IF TG_OP <> 'UPDATE' THEN
                RAISE EXCEPTION 'timer history is immutable';
            END IF;
            IF ROW(NEW.owner_id, NEW.activity_instance_id, NEW.idempotency_key, NEW.started_at)
                IS DISTINCT FROM ROW(
                    OLD.owner_id, OLD.activity_instance_id, OLD.idempotency_key, OLD.started_at
                ) THEN
                RAISE EXCEPTION 'timer provenance is immutable';
            END IF;
            IF OLD.ended_at IS NOT NULL THEN
                RAISE EXCEPTION 'ended timer is immutable';
            END IF;
            IF NEW.counted_seconds < OLD.counted_seconds
                OR NEW.last_heartbeat_at < OLD.last_heartbeat_at
                OR OLD.paused_at IS NOT NULL AND NEW.paused_at IS DISTINCT FROM OLD.paused_at THEN
                RAISE EXCEPTION 'timer progress must be monotonic';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_activity_timer_sessions_guard_mutation
        BEFORE UPDATE OR DELETE ON activity_timer_sessions
        FOR EACH ROW EXECUTE FUNCTION public.tamforge_guard_timer_mutation()
        """
    )

    op.execute(
        """
        CREATE FUNCTION public.tamforge_guard_attempt_insert()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        DECLARE parent_kind text;
        BEGIN
            IF NEW.attempt_kind = 'attempt_b' THEN
                SELECT attempt_kind INTO parent_kind
                FROM public.attempts
                WHERE owner_id = NEW.owner_id AND id = NEW.parent_attempt_id
                FOR KEY SHARE;
                IF parent_kind IS DISTINCT FROM 'attempt_a' THEN
                    RAISE EXCEPTION 'Attempt B requires an owner-scoped Attempt A parent';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_attempts_guard_insert
        BEFORE INSERT ON attempts
        FOR EACH ROW EXECUTE FUNCTION public.tamforge_guard_attempt_insert()
        """
    )

    op.execute(
        """
        CREATE FUNCTION public.tamforge_reject_learning_evidence_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            RAISE EXCEPTION 'learning evidence is immutable';
        END;
        $$
        """
    )
    for table_name in (
        "attempts",
        "artifacts",
        "activity_artifact_links",
        "self_reviews",
        "adaptive_changes",
        "daily_closes",
    ):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table_name}_immutable
            BEFORE UPDATE OR DELETE OR TRUNCATE ON {table_name}
            FOR EACH STATEMENT
            EXECUTE FUNCTION public.tamforge_reject_learning_evidence_mutation()
            """
        )


def downgrade() -> None:
    for table_name in (
        "daily_closes",
        "adaptive_changes",
        "self_reviews",
        "activity_artifact_links",
        "artifacts",
        "attempts",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table_name}_immutable ON {table_name}")
    op.execute("DROP FUNCTION IF EXISTS public.tamforge_reject_learning_evidence_mutation()")
    op.execute("DROP TRIGGER IF EXISTS trg_attempts_guard_insert ON attempts")
    op.execute("DROP FUNCTION IF EXISTS public.tamforge_guard_attempt_insert()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_activity_timer_sessions_guard_mutation "
        "ON activity_timer_sessions"
    )
    op.execute("DROP FUNCTION IF EXISTS public.tamforge_guard_timer_mutation()")
    op.execute("DROP TRIGGER IF EXISTS trg_activity_instances_guard_mutation ON activity_instances")
    op.execute("DROP TRIGGER IF EXISTS trg_activity_instances_guard_insert ON activity_instances")
    op.execute("DROP FUNCTION IF EXISTS public.tamforge_guard_activity_mutation()")
    op.execute("DROP TRIGGER IF EXISTS trg_study_days_guard_mutation ON study_days")
    op.execute("DROP TRIGGER IF EXISTS trg_study_days_guard_insert ON study_days")
    op.execute("DROP FUNCTION IF EXISTS public.tamforge_guard_study_day_mutation()")

    for table_name in (
        "daily_closes",
        "adaptive_changes",
        "self_reviews",
        "activity_artifact_links",
        "artifacts",
        "attempts",
        "activity_timer_sessions",
        "activity_instances",
        "study_days",
        "learner_settings",
    ):
        op.drop_table(table_name)

    op.execute("DROP FUNCTION IF EXISTS public.tamforge_validate_evidence_manifest_v1(jsonb)")
    op.execute("DROP FUNCTION IF EXISTS public.tamforge_validate_encryption_metadata_v1(jsonb)")

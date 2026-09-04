"""Add owner-scoped append-only SQL execution receipts.

Revision ID: 20260904_0014_sql_executions
Revises: 20260901_0013_recording_ingest
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260904_0014_sql_executions"
down_revision: str | None = "20260901_0013_recording_ingest"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sql_executions",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("activity_instance_id", sa.BigInteger(), nullable=False),
        sa.Column("task_stable_id_snapshot", sa.Text(), nullable=False),
        sa.Column("task_mapping_version_snapshot", sa.Text(), nullable=False),
        sa.Column("exercise_key", sa.Text(), nullable=False),
        sa.Column("exercise_version", sa.Integer(), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("query_sha256", sa.LargeBinary(length=32), nullable=False),
        sa.Column("canonical_result_json", sa.Text(), nullable=False),
        sa.Column("result_sha256", sa.LargeBinary(length=32), nullable=False),
        sa.Column("elapsed_ms", sa.Integer(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("validation", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("request_digest", sa.LargeBinary(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "btrim(task_stable_id_snapshot) <> '' AND "
            "octet_length(task_stable_id_snapshot) <= 192",
            name="task_stable_id_snapshot_bounded",
        ),
        sa.CheckConstraint(
            "btrim(task_mapping_version_snapshot) <> '' AND "
            "octet_length(task_mapping_version_snapshot) <= 64",
            name="task_mapping_version_snapshot_bounded",
        ),
        sa.CheckConstraint(
            "exercise_key ~ '^[a-z_][a-z0-9_]{0,62}$'",
            name="exercise_key_shape",
        ),
        sa.CheckConstraint("exercise_version > 0", name="exercise_version_positive"),
        sa.CheckConstraint(
            "btrim(query) <> '' AND octet_length(query) <= 65536",
            name="query_bounded",
        ),
        sa.CheckConstraint("octet_length(query_sha256) = 32", name="query_sha256_length"),
        sa.CheckConstraint(
            "query_sha256 = public.digest(pg_catalog.convert_to(query, 'UTF8'), 'sha256')",
            name="query_sha256_matches",
        ),
        sa.CheckConstraint(
            "octet_length(canonical_result_json) <= 262144",
            name="canonical_result_json_bounded",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(canonical_result_json::jsonb) = 'object' AND "
            "canonical_result_json::jsonb ?& ARRAY['columns', 'rows'] AND "
            "canonical_result_json::jsonb - 'columns' - 'rows' = '{}'::jsonb AND "
            "jsonb_typeof(canonical_result_json::jsonb->'columns') = 'array' AND "
            "jsonb_array_length(canonical_result_json::jsonb->'columns') BETWEEN 1 AND 32 AND "
            "jsonb_typeof(canonical_result_json::jsonb->'rows') = 'array'",
            name="canonical_result_shape",
        ),
        sa.CheckConstraint("octet_length(result_sha256) = 32", name="result_sha256_length"),
        sa.CheckConstraint(
            "result_sha256 = public.digest("
            "pg_catalog.convert_to(canonical_result_json, 'UTF8'), 'sha256')",
            name="result_sha256_matches",
        ),
        sa.CheckConstraint("elapsed_ms >= 0", name="elapsed_ms_nonnegative"),
        sa.CheckConstraint("row_count BETWEEN 0 AND 1000", name="row_count_bounded"),
        sa.CheckConstraint(
            "row_count = jsonb_array_length(canonical_result_json::jsonb->'rows')",
            name="row_count_matches",
        ),
        sa.CheckConstraint(
            "validation IN ('matched', 'mismatch', 'wrong_grain')",
            name="validation_allowed",
        ),
        sa.CheckConstraint(
            "idempotency_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'",
            name="idempotency_key_bounded",
        ),
        sa.CheckConstraint("octet_length(request_digest) = 32", name="request_digest_length"),
        sa.ForeignKeyConstraint(
            ["owner_id", "activity_instance_id"],
            ["activity_instances.owner_id", "activity_instances.id"],
            name="fk_sql_executions_owner_activity_activity_instances",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_sql_executions"),
        sa.UniqueConstraint(
            "owner_id",
            "activity_instance_id",
            "idempotency_key",
            name="uq_sql_executions_owner_activity_idempotency",
        ),
    )
    op.create_index(
        "ix_sql_executions_owner_activity_created",
        "sql_executions",
        ["owner_id", "activity_instance_id", "created_at", "id"],
    )
    op.execute(
        """
        CREATE FUNCTION public.tamforge_reject_sql_execution_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            RAISE EXCEPTION 'SQL execution receipts are immutable';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_sql_executions_append_only
        BEFORE UPDATE OR DELETE ON public.sql_executions
        FOR EACH ROW
        EXECUTE FUNCTION public.tamforge_reject_sql_execution_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_sql_executions_append_only ON public.sql_executions")
    op.execute("DROP FUNCTION public.tamforge_reject_sql_execution_mutation()")
    op.drop_index("ix_sql_executions_owner_activity_created", table_name="sql_executions")
    op.drop_table("sql_executions")

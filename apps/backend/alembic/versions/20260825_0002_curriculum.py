"""Add immutable versioned roadmap and curriculum persistence.

Revision ID: 20260825_0002_curriculum
Revises: 20260825_0001_identity_sessions
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260825_0002_curriculum"
down_revision: str | None = "20260825_0001_identity_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _identity_id() -> sa.Column[int]:
    return sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False)


def _created_at() -> sa.Column[object]:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.text("CURRENT_TIMESTAMP"),
        nullable=False,
    )


def _jsonb(name: str, *, default_object: bool = False) -> sa.Column[object]:
    return sa.Column(
        name,
        postgresql.JSONB(astext_type=sa.Text()),
        server_default=sa.text("'{}'::jsonb") if default_object else None,
        nullable=False,
    )


def upgrade() -> None:
    op.create_table(
        "roadmap_sources",
        _identity_id(),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("source_key", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("source_kind", sa.Text(), nullable=False),
        sa.Column("canonical_path", sa.Text(), nullable=True),
        _created_at(),
        sa.CheckConstraint("btrim(source_key) <> ''", name="source_key_nonblank"),
        sa.CheckConstraint("octet_length(source_key) <= 128", name="source_key_bounded"),
        sa.CheckConstraint("btrim(name) <> ''", name="name_nonblank"),
        sa.CheckConstraint("octet_length(name) <= 256", name="name_bounded"),
        sa.CheckConstraint(
            "source_kind IN ('obsidian', 'package', 'manual')",
            name="source_kind_allowed",
        ),
        sa.CheckConstraint(
            "canonical_path IS NULL OR octet_length(canonical_path) <= 2048",
            name="canonical_path_bounded",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name="fk_roadmap_sources_owner_id_owners",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_roadmap_sources"),
        sa.UniqueConstraint("owner_id", "source_key", name="uq_roadmap_sources_owner_source_key"),
        sa.UniqueConstraint("owner_id", "id", name="uq_roadmap_sources_owner_id_id"),
    )
    op.create_index("ix_roadmap_sources_owner_id", "roadmap_sources", ["owner_id"])

    op.create_table(
        "roadmap_imports",
        _identity_id(),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("source_id", sa.BigInteger(), nullable=False),
        sa.Column("package_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        _jsonb("validation_report", default_object=True),
        _jsonb("semantic_diff", default_object=True),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("failure_code", sa.Text(), nullable=True),
        _created_at(),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("octet_length(package_hash) = 32", name="package_hash_length"),
        sa.CheckConstraint("btrim(object_key) <> ''", name="object_key_nonblank"),
        sa.CheckConstraint(
            "octet_length(object_key) <= 1024 AND object_key !~ '^[a-z][a-z0-9+.-]*://'",
            name="object_key_private_bounded",
        ),
        sa.CheckConstraint(
            "status IN ('staged', 'validating', 'validated', 'imported', 'rejected', 'failed')",
            name="status_allowed",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(validation_report) = 'object' AND "
            "octet_length(validation_report::text) <= 1048576",
            name="validation_report_object",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(semantic_diff) = 'object' AND "
            "octet_length(semantic_diff::text) <= 1048576",
            name="semantic_diff_object",
        ),
        sa.CheckConstraint("btrim(idempotency_key) <> ''", name="idempotency_key_nonblank"),
        sa.CheckConstraint(
            "octet_length(idempotency_key) <= 256",
            name="idempotency_key_bounded",
        ),
        sa.CheckConstraint(
            "failure_code IS NULL OR failure_code IN ("
            "'invalid_package', 'unsupported_schema', 'hash_mismatch', "
            "'validation_failed', 'storage_unavailable', 'internal_error')",
            name="failure_code_allowed",
        ),
        sa.CheckConstraint(
            "(status IN ('rejected', 'failed')) = (failure_code IS NOT NULL)",
            name="failure_fields_coherent",
        ),
        sa.CheckConstraint(
            "started_at IS NULL OR started_at >= created_at",
            name="started_after_creation",
        ),
        sa.CheckConstraint(
            "completed_at IS NULL OR completed_at >= COALESCE(started_at, created_at)",
            name="completed_after_start",
        ),
        sa.CheckConstraint(
            "(status = 'staged' AND started_at IS NULL AND completed_at IS NULL) OR "
            "(status = 'validating' AND started_at IS NOT NULL AND completed_at IS NULL) OR "
            "(status IN ('validated', 'imported') AND started_at IS NOT NULL "
            "AND completed_at IS NOT NULL) OR "
            "(status IN ('rejected', 'failed') AND started_at IS NOT NULL "
            "AND completed_at IS NOT NULL)",
            name="lifecycle_coherent",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "source_id"],
            ["roadmap_sources.owner_id", "roadmap_sources.id"],
            name="fk_roadmap_imports_owner_source_roadmap_sources",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_roadmap_imports"),
        sa.UniqueConstraint(
            "owner_id",
            "idempotency_key",
            name="uq_roadmap_imports_owner_idempotency",
        ),
        sa.UniqueConstraint(
            "source_id",
            "package_hash",
            name="uq_roadmap_imports_source_package_hash",
        ),
    )
    op.create_index(
        "ix_roadmap_imports_owner_id_source_id",
        "roadmap_imports",
        ["owner_id", "source_id"],
    )
    op.create_index(
        "ix_roadmap_imports_status_created_at",
        "roadmap_imports",
        ["status", "created_at"],
    )

    op.create_table(
        "roadmap_versions",
        _identity_id(),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("source_id", sa.BigInteger(), nullable=False),
        sa.Column("version_key", sa.Text(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("month_number", sa.Integer(), nullable=False),
        sa.Column("predecessor_id", sa.BigInteger(), nullable=True),
        sa.Column("content_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        _jsonb("manifest"),
        _jsonb("raw_payload"),
        _jsonb("normalized_payload"),
        _created_at(),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("mirror_status", sa.Text(), nullable=False),
        sa.Column("mirror_ref", sa.Text(), nullable=True),
        sa.Column("mirror_error_code", sa.Text(), nullable=True),
        sa.Column("state", sa.Text(), nullable=False),
        sa.CheckConstraint("btrim(version_key) <> ''", name="version_key_nonblank"),
        sa.CheckConstraint("octet_length(version_key) <= 128", name="version_key_bounded"),
        sa.CheckConstraint("version_number > 0", name="version_number_positive"),
        sa.CheckConstraint("month_number > 0", name="month_number_positive"),
        sa.CheckConstraint(
            "predecessor_id IS NULL OR predecessor_id <> id",
            name="predecessor_not_self",
        ),
        sa.CheckConstraint("octet_length(content_hash) = 32", name="content_hash_length"),
        sa.CheckConstraint("btrim(object_key) <> ''", name="object_key_nonblank"),
        sa.CheckConstraint(
            "octet_length(object_key) <= 1024 AND object_key !~ '^[a-z][a-z0-9+.-]*://'",
            name="object_key_private_bounded",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(manifest) = 'object' AND octet_length(manifest::text) <= 1048576",
            name="manifest_object",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(raw_payload) = 'object' AND octet_length(raw_payload::text) <= 16777216",
            name="raw_payload_object",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(normalized_payload) = 'object' AND "
            "octet_length(normalized_payload::text) <= 16777216",
            name="normalized_payload_object",
        ),
        sa.CheckConstraint(
            "mirror_status IN ('pending', 'syncing', 'synced', 'failed', 'not_required')",
            name="mirror_status_allowed",
        ),
        sa.CheckConstraint(
            "mirror_ref IS NULL OR (btrim(mirror_ref) <> '' AND octet_length(mirror_ref) <= 512)",
            name="mirror_ref_bounded",
        ),
        sa.CheckConstraint(
            "mirror_error_code IS NULL OR mirror_error_code IN ("
            "'storage_unavailable', 'write_failed', 'conflict', "
            "'permission_denied', 'invalid_reference', 'internal_error')",
            name="mirror_error_code_allowed",
        ),
        sa.CheckConstraint(
            "(mirror_status = 'synced' AND mirror_ref IS NOT NULL "
            "AND mirror_error_code IS NULL) OR "
            "(mirror_status = 'failed' AND mirror_ref IS NULL "
            "AND mirror_error_code IS NOT NULL) OR "
            "(mirror_status IN ('pending', 'syncing', 'not_required') "
            "AND mirror_ref IS NULL AND mirror_error_code IS NULL)",
            name="mirror_fields_coherent",
        ),
        sa.CheckConstraint(
            "state IN ('draft', 'approved', 'active', 'superseded')",
            name="state_allowed",
        ),
        sa.CheckConstraint(
            "approved_at IS NULL OR approved_at >= created_at",
            name="approved_after_creation",
        ),
        sa.CheckConstraint(
            "activated_at IS NULL OR activated_at >= approved_at",
            name="activated_after_approval",
        ),
        sa.CheckConstraint(
            "superseded_at IS NULL OR superseded_at >= activated_at",
            name="superseded_after_activation",
        ),
        sa.CheckConstraint(
            "(state = 'draft' AND approved_at IS NULL AND activated_at IS NULL "
            "AND superseded_at IS NULL) OR "
            "(state = 'approved' AND approved_at IS NOT NULL "
            "AND activated_at IS NULL AND superseded_at IS NULL) OR "
            "(state = 'active' AND approved_at IS NOT NULL "
            "AND activated_at IS NOT NULL AND superseded_at IS NULL) OR "
            "(state = 'superseded' AND approved_at IS NOT NULL "
            "AND activated_at IS NOT NULL AND superseded_at IS NOT NULL)",
            name="lifecycle_coherent",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "source_id"],
            ["roadmap_sources.owner_id", "roadmap_sources.id"],
            name="fk_roadmap_versions_owner_source_roadmap_sources",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "source_id", "predecessor_id"],
            [
                "roadmap_versions.owner_id",
                "roadmap_versions.source_id",
                "roadmap_versions.id",
            ],
            name="fk_roadmap_versions_predecessor_same_source",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_roadmap_versions"),
        sa.UniqueConstraint("owner_id", "id", name="uq_roadmap_versions_owner_id_id"),
        sa.UniqueConstraint(
            "owner_id",
            "source_id",
            "id",
            name="uq_roadmap_versions_owner_source_id_id",
        ),
        sa.UniqueConstraint(
            "source_id",
            "content_hash",
            name="uq_roadmap_versions_source_content_hash",
        ),
        sa.UniqueConstraint(
            "source_id",
            "version_key",
            name="uq_roadmap_versions_source_version_key",
        ),
        sa.UniqueConstraint(
            "source_id",
            "version_number",
            name="uq_roadmap_versions_source_version_number",
        ),
    )
    op.create_index(
        "ix_roadmap_versions_owner_id_source_id",
        "roadmap_versions",
        ["owner_id", "source_id"],
    )
    op.create_index(
        "ix_roadmap_versions_owner_source_predecessor",
        "roadmap_versions",
        ["owner_id", "source_id", "predecessor_id"],
    )
    op.create_index(
        "uq_roadmap_versions_one_active_per_owner",
        "roadmap_versions",
        ["owner_id"],
        unique=True,
        postgresql_where=sa.text("state = 'active'"),
    )

    op.create_table(
        "curriculum_nodes",
        _identity_id(),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("roadmap_version_id", sa.BigInteger(), nullable=False),
        sa.Column("stable_id", sa.Text(), nullable=False),
        sa.Column("parent_id", sa.BigInteger(), nullable=True),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("source_path", sa.Text(), nullable=True),
        sa.Column("source_anchor", sa.Text(), nullable=True),
        sa.CheckConstraint("btrim(stable_id) <> ''", name="stable_id_nonblank"),
        sa.CheckConstraint("octet_length(stable_id) <= 192", name="stable_id_bounded"),
        sa.CheckConstraint("parent_id IS NULL OR parent_id <> id", name="parent_not_self"),
        sa.CheckConstraint("ordinal >= 0", name="ordinal_nonnegative"),
        sa.CheckConstraint("btrim(kind) <> ''", name="kind_nonblank"),
        sa.CheckConstraint("octet_length(kind) <= 64", name="kind_bounded"),
        sa.CheckConstraint("btrim(title) <> ''", name="title_nonblank"),
        sa.CheckConstraint("octet_length(title) <= 512", name="title_bounded"),
        sa.CheckConstraint(
            "source_path IS NULL OR octet_length(source_path) <= 2048",
            name="source_path_bounded",
        ),
        sa.CheckConstraint(
            "source_anchor IS NULL OR octet_length(source_anchor) <= 512",
            name="source_anchor_bounded",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "roadmap_version_id"],
            ["roadmap_versions.owner_id", "roadmap_versions.id"],
            name="fk_curriculum_nodes_owner_version_roadmap_versions",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "roadmap_version_id", "parent_id"],
            [
                "curriculum_nodes.owner_id",
                "curriculum_nodes.roadmap_version_id",
                "curriculum_nodes.id",
            ],
            name="fk_curriculum_nodes_parent_same_version",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_curriculum_nodes"),
        sa.UniqueConstraint(
            "owner_id",
            "roadmap_version_id",
            "id",
            name="uq_curriculum_nodes_owner_version_id_id",
        ),
        sa.UniqueConstraint(
            "roadmap_version_id",
            "stable_id",
            name="uq_curriculum_nodes_version_stable_id",
        ),
    )
    op.create_index(
        "ix_curriculum_nodes_owner_version",
        "curriculum_nodes",
        ["owner_id", "roadmap_version_id"],
    )
    op.create_index(
        "ix_curriculum_nodes_owner_version_parent",
        "curriculum_nodes",
        ["owner_id", "roadmap_version_id", "parent_id"],
    )
    op.create_index(
        "ix_curriculum_nodes_version_parent_ordinal",
        "curriculum_nodes",
        ["roadmap_version_id", "parent_id", "ordinal"],
    )

    op.create_table(
        "task_definitions",
        _identity_id(),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("roadmap_version_id", sa.BigInteger(), nullable=False),
        sa.Column("curriculum_node_id", sa.BigInteger(), nullable=False),
        sa.Column("stable_id", sa.Text(), nullable=False),
        sa.Column("exercise_type", sa.Text(), nullable=False),
        sa.Column("mapping_version", sa.Text(), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("timebox_minutes", sa.Integer(), nullable=False),
        sa.Column("block", sa.Text(), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False),
        _jsonb("output_contract"),
        _jsonb("pass_contract"),
        _jsonb("evidence_contract"),
        _jsonb("source_references"),
        sa.Column("allowed_ai_role", sa.Text(), nullable=False),
        sa.Column("source_path", sa.Text(), nullable=True),
        sa.Column("source_anchor", sa.Text(), nullable=True),
        sa.CheckConstraint("btrim(stable_id) <> ''", name="stable_id_nonblank"),
        sa.CheckConstraint("octet_length(stable_id) <= 192", name="stable_id_bounded"),
        sa.CheckConstraint("btrim(exercise_type) <> ''", name="exercise_type_nonblank"),
        sa.CheckConstraint("octet_length(exercise_type) <= 64", name="exercise_type_bounded"),
        sa.CheckConstraint("btrim(mapping_version) <> ''", name="mapping_version_nonblank"),
        sa.CheckConstraint("octet_length(mapping_version) <= 64", name="mapping_version_bounded"),
        sa.CheckConstraint("btrim(objective) <> ''", name="objective_nonblank"),
        sa.CheckConstraint("octet_length(objective) <= 4096", name="objective_bounded"),
        sa.CheckConstraint("timebox_minutes > 0", name="timebox_positive"),
        sa.CheckConstraint(
            "block IN ('sql', 'technical_learning', 'career_pipeline', "
            "'correction_warmup', 'tam_case', 'communication_spoken', "
            "'daily_close', 'saturday_assessment')",
            name="block_allowed",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(output_contract) = 'object' AND "
            "octet_length(output_contract::text) <= 262144",
            name="output_contract_object",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(pass_contract) = 'object' AND "
            "octet_length(pass_contract::text) <= 262144",
            name="pass_contract_object",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(evidence_contract) = 'object' AND "
            "octet_length(evidence_contract::text) <= 262144",
            name="evidence_contract_object",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(source_references) = 'array' AND "
            "jsonb_array_length(source_references) <= 256 AND "
            "octet_length(source_references::text) <= 262144",
            name="source_references_array",
        ),
        sa.CheckConstraint(
            "allowed_ai_role IN ('none', 'planner', 'tutor', 'coach', "
            "'interviewer', 'reviewer', 'analyst')",
            name="allowed_ai_role_allowed",
        ),
        sa.CheckConstraint(
            "source_path IS NULL OR octet_length(source_path) <= 2048",
            name="source_path_bounded",
        ),
        sa.CheckConstraint(
            "source_anchor IS NULL OR octet_length(source_anchor) <= 512",
            name="source_anchor_bounded",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "roadmap_version_id"],
            ["roadmap_versions.owner_id", "roadmap_versions.id"],
            name="fk_task_definitions_owner_version_roadmap_versions",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "roadmap_version_id", "curriculum_node_id"],
            [
                "curriculum_nodes.owner_id",
                "curriculum_nodes.roadmap_version_id",
                "curriculum_nodes.id",
            ],
            name="fk_task_definitions_node_same_version",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_task_definitions"),
        sa.UniqueConstraint(
            "owner_id",
            "roadmap_version_id",
            "id",
            name="uq_task_definitions_owner_version_id_id",
        ),
        sa.UniqueConstraint(
            "roadmap_version_id",
            "stable_id",
            name="uq_task_definitions_version_stable_id",
        ),
    )
    op.create_index(
        "ix_task_definitions_owner_version",
        "task_definitions",
        ["owner_id", "roadmap_version_id"],
    )
    op.create_index(
        "ix_task_definitions_owner_version_node",
        "task_definitions",
        ["owner_id", "roadmap_version_id", "curriculum_node_id"],
    )
    op.create_index(
        "ix_task_definitions_version_block",
        "task_definitions",
        ["roadmap_version_id", "block"],
    )

    op.create_table(
        "resources",
        _identity_id(),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("roadmap_version_id", sa.BigInteger(), nullable=False),
        sa.Column("stable_id", sa.Text(), nullable=False),
        sa.Column("curriculum_node_id", sa.BigInteger(), nullable=True),
        sa.Column("task_definition_id", sa.BigInteger(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("locator", sa.Text(), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column("source_path", sa.Text(), nullable=True),
        sa.Column("source_anchor", sa.Text(), nullable=True),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.CheckConstraint("btrim(stable_id) <> ''", name="stable_id_nonblank"),
        sa.CheckConstraint("octet_length(stable_id) <= 192", name="stable_id_bounded"),
        sa.CheckConstraint("btrim(kind) <> ''", name="kind_nonblank"),
        sa.CheckConstraint("octet_length(kind) <= 64", name="kind_bounded"),
        sa.CheckConstraint("btrim(title) <> ''", name="title_nonblank"),
        sa.CheckConstraint("octet_length(title) <= 512", name="title_bounded"),
        sa.CheckConstraint("btrim(locator) <> ''", name="locator_nonblank"),
        sa.CheckConstraint("octet_length(locator) <= 2048", name="locator_bounded"),
        sa.CheckConstraint(
            "source_path IS NULL OR octet_length(source_path) <= 2048",
            name="source_path_bounded",
        ),
        sa.CheckConstraint(
            "source_anchor IS NULL OR octet_length(source_anchor) <= 512",
            name="source_anchor_bounded",
        ),
        sa.CheckConstraint("ordinal >= 0", name="ordinal_nonnegative"),
        sa.ForeignKeyConstraint(
            ["owner_id", "roadmap_version_id"],
            ["roadmap_versions.owner_id", "roadmap_versions.id"],
            name="fk_resources_owner_version_roadmap_versions",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "roadmap_version_id", "curriculum_node_id"],
            [
                "curriculum_nodes.owner_id",
                "curriculum_nodes.roadmap_version_id",
                "curriculum_nodes.id",
            ],
            name="fk_resources_node_same_version",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "roadmap_version_id", "task_definition_id"],
            [
                "task_definitions.owner_id",
                "task_definitions.roadmap_version_id",
                "task_definitions.id",
            ],
            name="fk_resources_task_same_version",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_resources"),
        sa.UniqueConstraint(
            "roadmap_version_id",
            "stable_id",
            name="uq_resources_version_stable_id",
        ),
    )
    op.create_index(
        "ix_resources_owner_version",
        "resources",
        ["owner_id", "roadmap_version_id"],
    )
    op.create_index(
        "ix_resources_owner_version_node",
        "resources",
        ["owner_id", "roadmap_version_id", "curriculum_node_id"],
    )
    op.create_index(
        "ix_resources_owner_version_task",
        "resources",
        ["owner_id", "roadmap_version_id", "task_definition_id"],
    )

    op.create_table(
        "pass_criteria",
        _identity_id(),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("roadmap_version_id", sa.BigInteger(), nullable=False),
        sa.Column("stable_id", sa.Text(), nullable=False),
        sa.Column("curriculum_node_id", sa.BigInteger(), nullable=True),
        sa.Column("task_definition_id", sa.BigInteger(), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        _jsonb("rubric"),
        _jsonb("evidence"),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.CheckConstraint("btrim(stable_id) <> ''", name="stable_id_nonblank"),
        sa.CheckConstraint("octet_length(stable_id) <= 192", name="stable_id_bounded"),
        sa.CheckConstraint(
            "num_nonnulls(curriculum_node_id, task_definition_id) = 1",
            name="exactly_one_target",
        ),
        sa.CheckConstraint("btrim(description) <> ''", name="description_nonblank"),
        sa.CheckConstraint("octet_length(description) <= 4096", name="description_bounded"),
        sa.CheckConstraint(
            "jsonb_typeof(rubric) = 'object' AND octet_length(rubric::text) <= 262144",
            name="rubric_object",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(evidence) = 'object' AND octet_length(evidence::text) <= 262144",
            name="evidence_object",
        ),
        sa.CheckConstraint("ordinal >= 0", name="ordinal_nonnegative"),
        sa.ForeignKeyConstraint(
            ["owner_id", "roadmap_version_id"],
            ["roadmap_versions.owner_id", "roadmap_versions.id"],
            name="fk_pass_criteria_owner_version_roadmap_versions",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "roadmap_version_id", "curriculum_node_id"],
            [
                "curriculum_nodes.owner_id",
                "curriculum_nodes.roadmap_version_id",
                "curriculum_nodes.id",
            ],
            name="fk_pass_criteria_node_same_version",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "roadmap_version_id", "task_definition_id"],
            [
                "task_definitions.owner_id",
                "task_definitions.roadmap_version_id",
                "task_definitions.id",
            ],
            name="fk_pass_criteria_task_same_version",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_pass_criteria"),
        sa.UniqueConstraint(
            "roadmap_version_id",
            "stable_id",
            name="uq_pass_criteria_version_stable_id",
        ),
    )
    op.create_index(
        "ix_pass_criteria_owner_version",
        "pass_criteria",
        ["owner_id", "roadmap_version_id"],
    )
    op.create_index(
        "ix_pass_criteria_owner_version_node",
        "pass_criteria",
        ["owner_id", "roadmap_version_id", "curriculum_node_id"],
    )
    op.create_index(
        "ix_pass_criteria_owner_version_task",
        "pass_criteria",
        ["owner_id", "roadmap_version_id", "task_definition_id"],
    )

    op.create_table(
        "exit_criteria",
        _identity_id(),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("roadmap_version_id", sa.BigInteger(), nullable=False),
        sa.Column("stable_id", sa.Text(), nullable=False),
        sa.Column("month_number", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        _jsonb("rubric"),
        _jsonb("evidence"),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.CheckConstraint("btrim(stable_id) <> ''", name="stable_id_nonblank"),
        sa.CheckConstraint("octet_length(stable_id) <= 192", name="stable_id_bounded"),
        sa.CheckConstraint("month_number > 0", name="month_number_positive"),
        sa.CheckConstraint("btrim(description) <> ''", name="description_nonblank"),
        sa.CheckConstraint("octet_length(description) <= 4096", name="description_bounded"),
        sa.CheckConstraint(
            "jsonb_typeof(rubric) = 'object' AND octet_length(rubric::text) <= 262144",
            name="rubric_object",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(evidence) = 'object' AND octet_length(evidence::text) <= 262144",
            name="evidence_object",
        ),
        sa.CheckConstraint("ordinal >= 0", name="ordinal_nonnegative"),
        sa.ForeignKeyConstraint(
            ["owner_id", "roadmap_version_id"],
            ["roadmap_versions.owner_id", "roadmap_versions.id"],
            name="fk_exit_criteria_owner_version_roadmap_versions",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_exit_criteria"),
        sa.UniqueConstraint(
            "roadmap_version_id",
            "stable_id",
            name="uq_exit_criteria_version_stable_id",
        ),
    )
    op.create_index(
        "ix_exit_criteria_owner_version",
        "exit_criteria",
        ["owner_id", "roadmap_version_id"],
    )

    op.create_table(
        "month_exit_reviews",
        _identity_id(),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("roadmap_version_id", sa.BigInteger(), nullable=False),
        sa.Column("review_number", sa.Integer(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("decision", sa.Text(), nullable=False),
        _jsonb("evidence"),
        sa.Column("activation_eligible", sa.Boolean(), nullable=True),
        _jsonb("eligibility_evidence"),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("review_number > 0", name="review_number_positive"),
        sa.CheckConstraint(
            "state IN ('draft', 'in_progress', 'completed')",
            name="state_allowed",
        ),
        sa.CheckConstraint("decision IN ('pending', 'advance', 'hold')", name="decision_allowed"),
        sa.CheckConstraint(
            "jsonb_typeof(evidence) = 'object' AND octet_length(evidence::text) <= 1048576",
            name="evidence_object",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(eligibility_evidence) = 'object' AND "
            "octet_length(eligibility_evidence::text) <= 1048576",
            name="eligibility_evidence_object",
        ),
        sa.CheckConstraint(
            "completed_at IS NULL OR completed_at >= started_at",
            name="completed_after_start",
        ),
        sa.CheckConstraint(
            "(state IN ('draft', 'in_progress') AND decision = 'pending' "
            "AND completed_at IS NULL AND activation_eligible IS NULL) OR "
            "(state = 'completed' AND decision IN ('advance', 'hold') "
            "AND completed_at IS NOT NULL AND activation_eligible IS NOT NULL)",
            name="lifecycle_coherent",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "roadmap_version_id"],
            ["roadmap_versions.owner_id", "roadmap_versions.id"],
            name="fk_month_exit_reviews_owner_version_roadmap_versions",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_month_exit_reviews"),
        sa.UniqueConstraint(
            "roadmap_version_id",
            "review_number",
            name="uq_month_exit_reviews_version_review_number",
        ),
    )
    op.create_index(
        "ix_month_exit_reviews_owner_version",
        "month_exit_reviews",
        ["owner_id", "roadmap_version_id"],
    )

    op.execute(
        """
        CREATE FUNCTION public.tamforge_reject_roadmap_source_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            RAISE EXCEPTION 'roadmap source history is immutable'
                USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_roadmap_sources_immutable
        BEFORE UPDATE OR DELETE ON roadmap_sources
        FOR EACH ROW
        EXECUTE FUNCTION public.tamforge_reject_roadmap_source_mutation()
        """
    )

    op.execute(
        """
        CREATE FUNCTION public.tamforge_guard_roadmap_import_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'roadmap import history is immutable'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF NEW.owner_id IS DISTINCT FROM OLD.owner_id
                OR NEW.source_id IS DISTINCT FROM OLD.source_id
                OR NEW.package_hash IS DISTINCT FROM OLD.package_hash
                OR NEW.object_key IS DISTINCT FROM OLD.object_key
                OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
                OR NEW.created_at IS DISTINCT FROM OLD.created_at
            THEN
                RAISE EXCEPTION 'roadmap import provenance is immutable'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF (OLD.started_at IS NOT NULL AND NEW.started_at IS DISTINCT FROM OLD.started_at)
                OR (
                    OLD.completed_at IS NOT NULL
                    AND NEW.completed_at IS DISTINCT FROM OLD.completed_at
                )
            THEN
                RAISE EXCEPTION 'roadmap import timestamps are write-once'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF OLD.status IN ('imported', 'rejected', 'failed')
                AND to_jsonb(NEW) IS DISTINCT FROM to_jsonb(OLD)
            THEN
                RAISE EXCEPTION 'terminal roadmap import is immutable'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF NEW.status IS DISTINCT FROM OLD.status AND NOT (
                (OLD.status = 'staged' AND NEW.status = 'validating')
                OR (OLD.status = 'validating' AND NEW.status IN (
                    'validated', 'rejected', 'failed'
                ))
                OR (OLD.status = 'validated' AND NEW.status = 'imported')
            ) THEN
                RAISE EXCEPTION 'invalid roadmap import transition'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_roadmap_imports_guard_mutation
        BEFORE UPDATE OR DELETE ON roadmap_imports
        FOR EACH ROW
        EXECUTE FUNCTION public.tamforge_guard_roadmap_import_mutation()
        """
    )

    op.execute(
        """
        CREATE FUNCTION public.tamforge_guard_roadmap_version_update()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'roadmap version history is immutable'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF NEW.owner_id IS DISTINCT FROM OLD.owner_id
                OR NEW.source_id IS DISTINCT FROM OLD.source_id
                OR NEW.version_key IS DISTINCT FROM OLD.version_key
                OR NEW.version_number IS DISTINCT FROM OLD.version_number
                OR NEW.month_number IS DISTINCT FROM OLD.month_number
                OR NEW.predecessor_id IS DISTINCT FROM OLD.predecessor_id
                OR NEW.content_hash IS DISTINCT FROM OLD.content_hash
                OR NEW.object_key IS DISTINCT FROM OLD.object_key
                OR NEW.manifest IS DISTINCT FROM OLD.manifest
                OR NEW.raw_payload IS DISTINCT FROM OLD.raw_payload
                OR NEW.normalized_payload IS DISTINCT FROM OLD.normalized_payload
                OR NEW.created_at IS DISTINCT FROM OLD.created_at
            THEN
                RAISE EXCEPTION 'roadmap version provenance is immutable'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF (
                OLD.approved_at IS NOT NULL
                AND NEW.approved_at IS DISTINCT FROM OLD.approved_at
            ) OR (
                OLD.activated_at IS NOT NULL
                AND NEW.activated_at IS DISTINCT FROM OLD.activated_at
            ) OR (
                OLD.superseded_at IS NOT NULL
                AND NEW.superseded_at IS DISTINCT FROM OLD.superseded_at
            )
            THEN
                RAISE EXCEPTION 'roadmap lifecycle timestamps are write-once'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF NEW.state IS DISTINCT FROM OLD.state AND NOT (
                (OLD.state = 'draft' AND NEW.state = 'approved')
                OR (OLD.state = 'approved' AND NEW.state = 'active')
                OR (OLD.state = 'active' AND NEW.state = 'superseded')
            ) THEN
                RAISE EXCEPTION 'invalid roadmap lifecycle transition'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF NEW.mirror_status IS DISTINCT FROM OLD.mirror_status AND NOT (
                (OLD.mirror_status = 'pending' AND NEW.mirror_status IN (
                    'syncing', 'not_required'
                ))
                OR (OLD.mirror_status = 'syncing' AND NEW.mirror_status IN (
                    'synced', 'failed'
                ))
                OR (OLD.mirror_status = 'failed' AND NEW.mirror_status = 'syncing')
            ) THEN
                RAISE EXCEPTION 'invalid roadmap mirror transition'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF OLD.mirror_status IN ('synced', 'not_required') AND (
                NEW.mirror_status IS DISTINCT FROM OLD.mirror_status
                OR NEW.mirror_ref IS DISTINCT FROM OLD.mirror_ref
                OR NEW.mirror_error_code IS DISTINCT FROM OLD.mirror_error_code
            ) THEN
                RAISE EXCEPTION 'completed roadmap mirror state is immutable'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_roadmap_versions_guard_update
        BEFORE UPDATE OR DELETE ON roadmap_versions
        FOR EACH ROW
        EXECUTE FUNCTION public.tamforge_guard_roadmap_version_update()
        """
    )

    op.execute(
        """
        CREATE FUNCTION public.tamforge_reject_curriculum_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            RAISE EXCEPTION 'imported curriculum content is immutable'
                USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$
        """
    )
    for table_name in (
        "curriculum_nodes",
        "task_definitions",
        "resources",
        "pass_criteria",
        "exit_criteria",
    ):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table_name}_immutable
            BEFORE UPDATE OR DELETE ON {table_name}
            FOR EACH ROW
            EXECUTE FUNCTION public.tamforge_reject_curriculum_mutation()
            """
        )

    op.execute(
        """
        CREATE FUNCTION public.tamforge_guard_month_exit_review_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'month exit review history is immutable'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF OLD.state = 'completed' THEN
                RAISE EXCEPTION 'completed month exit review is immutable'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF NEW.owner_id IS DISTINCT FROM OLD.owner_id
                OR NEW.roadmap_version_id IS DISTINCT FROM OLD.roadmap_version_id
                OR NEW.review_number IS DISTINCT FROM OLD.review_number
                OR NEW.started_at IS DISTINCT FROM OLD.started_at
                OR (
                    OLD.completed_at IS NOT NULL
                    AND NEW.completed_at IS DISTINCT FROM OLD.completed_at
                )
            THEN
                RAISE EXCEPTION 'month exit review identity is immutable'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF NEW.state IS DISTINCT FROM OLD.state AND NOT (
                (OLD.state = 'draft' AND NEW.state IN ('in_progress', 'completed'))
                OR (OLD.state = 'in_progress' AND NEW.state = 'completed')
            ) THEN
                RAISE EXCEPTION 'invalid month exit review transition'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_month_exit_reviews_guard_mutation
        BEFORE UPDATE OR DELETE ON month_exit_reviews
        FOR EACH ROW
        EXECUTE FUNCTION public.tamforge_guard_month_exit_review_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_month_exit_reviews_guard_mutation ON month_exit_reviews")
    op.execute("DROP FUNCTION IF EXISTS public.tamforge_guard_month_exit_review_mutation()")

    for table_name in (
        "exit_criteria",
        "pass_criteria",
        "resources",
        "task_definitions",
        "curriculum_nodes",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table_name}_immutable ON {table_name}")
    op.execute("DROP FUNCTION IF EXISTS public.tamforge_reject_curriculum_mutation()")

    op.execute("DROP TRIGGER IF EXISTS trg_roadmap_versions_guard_update ON roadmap_versions")
    op.execute("DROP FUNCTION IF EXISTS public.tamforge_guard_roadmap_version_update()")
    op.execute("DROP TRIGGER IF EXISTS trg_roadmap_imports_guard_mutation ON roadmap_imports")
    op.execute("DROP FUNCTION IF EXISTS public.tamforge_guard_roadmap_import_mutation()")
    op.execute("DROP TRIGGER IF EXISTS trg_roadmap_sources_immutable ON roadmap_sources")
    op.execute("DROP FUNCTION IF EXISTS public.tamforge_reject_roadmap_source_mutation()")

    op.drop_index("ix_month_exit_reviews_owner_version", table_name="month_exit_reviews")
    op.drop_table("month_exit_reviews")

    op.drop_index("ix_exit_criteria_owner_version", table_name="exit_criteria")
    op.drop_table("exit_criteria")

    op.drop_index("ix_pass_criteria_owner_version_task", table_name="pass_criteria")
    op.drop_index("ix_pass_criteria_owner_version_node", table_name="pass_criteria")
    op.drop_index("ix_pass_criteria_owner_version", table_name="pass_criteria")
    op.drop_table("pass_criteria")

    op.drop_index("ix_resources_owner_version_task", table_name="resources")
    op.drop_index("ix_resources_owner_version_node", table_name="resources")
    op.drop_index("ix_resources_owner_version", table_name="resources")
    op.drop_table("resources")

    op.drop_index("ix_task_definitions_version_block", table_name="task_definitions")
    op.drop_index("ix_task_definitions_owner_version_node", table_name="task_definitions")
    op.drop_index("ix_task_definitions_owner_version", table_name="task_definitions")
    op.drop_table("task_definitions")

    op.drop_index("ix_curriculum_nodes_version_parent_ordinal", table_name="curriculum_nodes")
    op.drop_index("ix_curriculum_nodes_owner_version_parent", table_name="curriculum_nodes")
    op.drop_index("ix_curriculum_nodes_owner_version", table_name="curriculum_nodes")
    op.drop_table("curriculum_nodes")

    op.drop_index("uq_roadmap_versions_one_active_per_owner", table_name="roadmap_versions")
    op.drop_index("ix_roadmap_versions_owner_source_predecessor", table_name="roadmap_versions")
    op.drop_index("ix_roadmap_versions_owner_id_source_id", table_name="roadmap_versions")
    op.drop_table("roadmap_versions")

    op.drop_index("ix_roadmap_imports_status_created_at", table_name="roadmap_imports")
    op.drop_index("ix_roadmap_imports_owner_id_source_id", table_name="roadmap_imports")
    op.drop_table("roadmap_imports")

    op.drop_index("ix_roadmap_sources_owner_id", table_name="roadmap_sources")
    op.drop_table("roadmap_sources")

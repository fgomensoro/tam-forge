"""Immutable, version-scoped roadmap and curriculum models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
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

from ..models.base import Base, utc_now


class RoadmapVersionImmutableError(ValueError):
    """Raised when immutable roadmap-version provenance is changed."""


class RoadmapSourceImmutableError(ValueError):
    """Raised when immutable roadmap-source provenance is changed."""


class RoadmapImportWorkflowError(ValueError):
    """Raised when an import violates its persistence workflow."""


class RoadmapVersionWorkflowError(ValueError):
    """Raised when a roadmap version violates lifecycle or mirror workflow."""


class CurriculumContentImmutableError(ValueError):
    """Raised when imported curriculum content is mutated through the ORM."""


IMPORT_FAILURE_CODES = frozenset(
    {
        "invalid_package",
        "unsupported_schema",
        "hash_mismatch",
        "validation_failed",
        "storage_unavailable",
        "internal_error",
    }
)
MIRROR_ERROR_CODES = frozenset(
    {
        "storage_unavailable",
        "write_failed",
        "conflict",
        "permission_denied",
        "invalid_reference",
        "internal_error",
    }
)
IMPORT_TRANSITIONS = {
    "staged": frozenset({"validating"}),
    "validating": frozenset({"validated", "rejected", "failed"}),
    "validated": frozenset({"imported"}),
    "imported": frozenset(),
    "rejected": frozenset(),
    "failed": frozenset(),
}
VERSION_STATE_TRANSITIONS = {
    "draft": frozenset({"approved"}),
    "approved": frozenset({"active"}),
    "active": frozenset({"superseded"}),
    "superseded": frozenset(),
}
MIRROR_TRANSITIONS = {
    "pending": frozenset({"syncing", "not_required"}),
    "syncing": frozenset({"synced", "failed"}),
    "failed": frozenset({"syncing"}),
    "synced": frozenset(),
    "not_required": frozenset(),
}
_TERMINAL_IMPORT_STATES = frozenset({"imported", "rejected", "failed"})
_TERMINAL_MIRROR_STATES = frozenset({"synced", "not_required"})


class RoadmapSource(Base):
    """A stable owner-scoped import source; canonical_path is provenance only."""

    __tablename__ = "roadmap_sources"
    __table_args__ = (
        UniqueConstraint("owner_id", "source_key", name="uq_roadmap_sources_owner_source_key"),
        UniqueConstraint("owner_id", "id", name="uq_roadmap_sources_owner_id_id"),
        CheckConstraint("btrim(source_key) <> ''", name="source_key_nonblank"),
        CheckConstraint("octet_length(source_key) <= 128", name="source_key_bounded"),
        CheckConstraint("btrim(name) <> ''", name="name_nonblank"),
        CheckConstraint("octet_length(name) <= 256", name="name_bounded"),
        CheckConstraint(
            "source_kind IN ('obsidian', 'package', 'manual')",
            name="source_kind_allowed",
        ),
        CheckConstraint(
            "canonical_path IS NULL OR octet_length(canonical_path) <= 2048",
            name="canonical_path_bounded",
        ),
        Index("ix_roadmap_sources_owner_id", "owner_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "owners.id",
            name="fk_roadmap_sources_owner_id_owners",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    source_key: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    source_kind: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_path: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
    )


class RoadmapImport(Base):
    """One idempotent staged roadmap package; package bytes remain in object storage."""

    __tablename__ = "roadmap_imports"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "source_id"],
            ["roadmap_sources.owner_id", "roadmap_sources.id"],
            name="fk_roadmap_imports_owner_source_roadmap_sources",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "owner_id", "idempotency_key", name="uq_roadmap_imports_owner_idempotency"
        ),
        UniqueConstraint(
            "source_id", "package_hash", name="uq_roadmap_imports_source_package_hash"
        ),
        CheckConstraint("octet_length(package_hash) = 32", name="package_hash_length"),
        CheckConstraint("btrim(object_key) <> ''", name="object_key_nonblank"),
        CheckConstraint(
            "octet_length(object_key) <= 1024 AND object_key !~ '^[a-z][a-z0-9+.-]*://'",
            name="object_key_private_bounded",
        ),
        CheckConstraint(
            "status IN ('staged', 'validating', 'validated', 'imported', 'rejected', 'failed')",
            name="status_allowed",
        ),
        CheckConstraint(
            "jsonb_typeof(validation_report) = 'object' AND "
            "octet_length(validation_report::text) <= 1048576",
            name="validation_report_object",
        ),
        CheckConstraint(
            "jsonb_typeof(semantic_diff) = 'object' AND "
            "octet_length(semantic_diff::text) <= 1048576",
            name="semantic_diff_object",
        ),
        CheckConstraint("btrim(idempotency_key) <> ''", name="idempotency_key_nonblank"),
        CheckConstraint("octet_length(idempotency_key) <= 256", name="idempotency_key_bounded"),
        CheckConstraint(
            "failure_code IS NULL OR failure_code IN ("
            "'invalid_package', 'unsupported_schema', 'hash_mismatch', "
            "'validation_failed', 'storage_unavailable', 'internal_error')",
            name="failure_code_allowed",
        ),
        CheckConstraint(
            "(status IN ('rejected', 'failed')) = (failure_code IS NOT NULL)",
            name="failure_fields_coherent",
        ),
        CheckConstraint(
            "started_at IS NULL OR started_at >= created_at",
            name="started_after_creation",
        ),
        CheckConstraint(
            "completed_at IS NULL OR completed_at >= COALESCE(started_at, created_at)",
            name="completed_after_start",
        ),
        CheckConstraint(
            "(status = 'staged' AND started_at IS NULL AND completed_at IS NULL) OR "
            "(status = 'validating' AND started_at IS NOT NULL AND completed_at IS NULL) OR "
            "(status IN ('validated', 'imported') AND started_at IS NOT NULL "
            "AND completed_at IS NOT NULL) OR "
            "(status IN ('rejected', 'failed') AND started_at IS NOT NULL "
            "AND completed_at IS NOT NULL)",
            name="lifecycle_coherent",
        ),
        Index("ix_roadmap_imports_owner_id_source_id", "owner_id", "source_id"),
        Index("ix_roadmap_imports_status_created_at", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    package_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    validation_report: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False
    )
    semantic_diff: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    failure_code: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RoadmapVersion(Base):
    """An immutable source payload with tightly controlled lifecycle fields."""

    __tablename__ = "roadmap_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "source_id"],
            ["roadmap_sources.owner_id", "roadmap_sources.id"],
            name="fk_roadmap_versions_owner_source_roadmap_sources",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["owner_id", "source_id", "predecessor_id"],
            [
                "roadmap_versions.owner_id",
                "roadmap_versions.source_id",
                "roadmap_versions.id",
            ],
            name="fk_roadmap_versions_predecessor_same_source",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("owner_id", "id", name="uq_roadmap_versions_owner_id_id"),
        UniqueConstraint(
            "owner_id", "source_id", "id", name="uq_roadmap_versions_owner_source_id_id"
        ),
        UniqueConstraint(
            "source_id", "content_hash", name="uq_roadmap_versions_source_content_hash"
        ),
        UniqueConstraint("source_id", "version_key", name="uq_roadmap_versions_source_version_key"),
        UniqueConstraint(
            "source_id", "version_number", name="uq_roadmap_versions_source_version_number"
        ),
        CheckConstraint("btrim(version_key) <> ''", name="version_key_nonblank"),
        CheckConstraint("octet_length(version_key) <= 128", name="version_key_bounded"),
        CheckConstraint("version_number > 0", name="version_number_positive"),
        CheckConstraint("month_number > 0", name="month_number_positive"),
        CheckConstraint(
            "predecessor_id IS NULL OR predecessor_id <> id", name="predecessor_not_self"
        ),
        CheckConstraint("octet_length(content_hash) = 32", name="content_hash_length"),
        CheckConstraint("btrim(object_key) <> ''", name="object_key_nonblank"),
        CheckConstraint(
            "octet_length(object_key) <= 1024 AND object_key !~ '^[a-z][a-z0-9+.-]*://'",
            name="object_key_private_bounded",
        ),
        CheckConstraint(
            "jsonb_typeof(manifest) = 'object' AND octet_length(manifest::text) <= 1048576",
            name="manifest_object",
        ),
        CheckConstraint(
            "jsonb_typeof(raw_payload) = 'object' AND octet_length(raw_payload::text) <= 16777216",
            name="raw_payload_object",
        ),
        CheckConstraint(
            "jsonb_typeof(normalized_payload) = 'object' AND "
            "octet_length(normalized_payload::text) <= 16777216",
            name="normalized_payload_object",
        ),
        CheckConstraint(
            "mirror_status IN ('pending', 'syncing', 'synced', 'failed', 'not_required')",
            name="mirror_status_allowed",
        ),
        CheckConstraint(
            "mirror_ref IS NULL OR (btrim(mirror_ref) <> '' AND octet_length(mirror_ref) <= 512)",
            name="mirror_ref_bounded",
        ),
        CheckConstraint(
            "mirror_error_code IS NULL OR mirror_error_code IN ("
            "'storage_unavailable', 'write_failed', 'conflict', "
            "'permission_denied', 'invalid_reference', 'internal_error')",
            name="mirror_error_code_allowed",
        ),
        CheckConstraint(
            "(mirror_status = 'synced' AND mirror_ref IS NOT NULL "
            "AND mirror_error_code IS NULL) OR "
            "(mirror_status = 'failed' AND mirror_ref IS NULL "
            "AND mirror_error_code IS NOT NULL) OR "
            "(mirror_status IN ('pending', 'syncing', 'not_required') "
            "AND mirror_ref IS NULL AND mirror_error_code IS NULL)",
            name="mirror_fields_coherent",
        ),
        CheckConstraint(
            "state IN ('draft', 'approved', 'active', 'superseded')",
            name="state_allowed",
        ),
        CheckConstraint(
            "approved_at IS NULL OR approved_at >= created_at",
            name="approved_after_creation",
        ),
        CheckConstraint(
            "activated_at IS NULL OR activated_at >= approved_at",
            name="activated_after_approval",
        ),
        CheckConstraint(
            "superseded_at IS NULL OR superseded_at >= activated_at",
            name="superseded_after_activation",
        ),
        CheckConstraint(
            "(state = 'draft' AND approved_at IS NULL AND activated_at IS NULL "
            "AND superseded_at IS NULL) OR "
            "(state = 'approved' AND approved_at IS NOT NULL AND activated_at IS NULL "
            "AND superseded_at IS NULL) OR "
            "(state = 'active' AND approved_at IS NOT NULL AND activated_at IS NOT NULL "
            "AND superseded_at IS NULL) OR "
            "(state = 'superseded' AND approved_at IS NOT NULL AND activated_at IS NOT NULL "
            "AND superseded_at IS NOT NULL)",
            name="lifecycle_coherent",
        ),
        Index("ix_roadmap_versions_owner_id_source_id", "owner_id", "source_id"),
        Index(
            "ix_roadmap_versions_owner_source_predecessor",
            "owner_id",
            "source_id",
            "predecessor_id",
        ),
        Index(
            "uq_roadmap_versions_one_active_per_owner",
            "owner_id",
            unique=True,
            postgresql_where=text("state = 'active'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    version_key: Mapped[str] = mapped_column(Text, nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    month_number: Mapped[int] = mapped_column(Integer, nullable=False)
    predecessor_id: Mapped[int | None] = mapped_column(BigInteger)
    content_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    manifest: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    normalized_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mirror_status: Mapped[str] = mapped_column(Text, nullable=False)
    mirror_ref: Mapped[str | None] = mapped_column(Text)
    mirror_error_code: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str] = mapped_column(Text, nullable=False)


class CurriculumNode(Base):
    """A version-scoped immutable curriculum hierarchy node."""

    __tablename__ = "curriculum_nodes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "roadmap_version_id"],
            ["roadmap_versions.owner_id", "roadmap_versions.id"],
            name="fk_curriculum_nodes_owner_version_roadmap_versions",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["owner_id", "roadmap_version_id", "parent_id"],
            [
                "curriculum_nodes.owner_id",
                "curriculum_nodes.roadmap_version_id",
                "curriculum_nodes.id",
            ],
            name="fk_curriculum_nodes_parent_same_version",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "owner_id",
            "roadmap_version_id",
            "id",
            name="uq_curriculum_nodes_owner_version_id_id",
        ),
        UniqueConstraint(
            "roadmap_version_id",
            "stable_id",
            name="uq_curriculum_nodes_version_stable_id",
        ),
        CheckConstraint("btrim(stable_id) <> ''", name="stable_id_nonblank"),
        CheckConstraint("octet_length(stable_id) <= 192", name="stable_id_bounded"),
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="parent_not_self"),
        CheckConstraint("ordinal >= 0", name="ordinal_nonnegative"),
        CheckConstraint("btrim(kind) <> ''", name="kind_nonblank"),
        CheckConstraint("octet_length(kind) <= 64", name="kind_bounded"),
        CheckConstraint("btrim(title) <> ''", name="title_nonblank"),
        CheckConstraint("octet_length(title) <= 512", name="title_bounded"),
        CheckConstraint(
            "source_path IS NULL OR octet_length(source_path) <= 2048", name="source_path_bounded"
        ),
        CheckConstraint(
            "source_anchor IS NULL OR octet_length(source_anchor) <= 512",
            name="source_anchor_bounded",
        ),
        Index("ix_curriculum_nodes_owner_version", "owner_id", "roadmap_version_id"),
        Index(
            "ix_curriculum_nodes_owner_version_parent",
            "owner_id",
            "roadmap_version_id",
            "parent_id",
        ),
        Index(
            "ix_curriculum_nodes_version_parent_ordinal",
            "roadmap_version_id",
            "parent_id",
            "ordinal",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    roadmap_version_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    stable_id: Mapped[str] = mapped_column(Text, nullable=False)
    parent_id: Mapped[int | None] = mapped_column(BigInteger)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    source_path: Mapped[str | None] = mapped_column(Text)
    source_anchor: Mapped[str | None] = mapped_column(Text)


class TaskDefinition(Base):
    """A versioned task definition preserving the roadmap's AI-role boundary."""

    __tablename__ = "task_definitions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "roadmap_version_id"],
            ["roadmap_versions.owner_id", "roadmap_versions.id"],
            name="fk_task_definitions_owner_version_roadmap_versions",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["owner_id", "roadmap_version_id", "curriculum_node_id"],
            [
                "curriculum_nodes.owner_id",
                "curriculum_nodes.roadmap_version_id",
                "curriculum_nodes.id",
            ],
            name="fk_task_definitions_node_same_version",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "owner_id",
            "roadmap_version_id",
            "id",
            name="uq_task_definitions_owner_version_id_id",
        ),
        UniqueConstraint(
            "roadmap_version_id",
            "stable_id",
            name="uq_task_definitions_version_stable_id",
        ),
        CheckConstraint("btrim(stable_id) <> ''", name="stable_id_nonblank"),
        CheckConstraint("octet_length(stable_id) <= 192", name="stable_id_bounded"),
        CheckConstraint("btrim(exercise_type) <> ''", name="exercise_type_nonblank"),
        CheckConstraint("octet_length(exercise_type) <= 64", name="exercise_type_bounded"),
        CheckConstraint("btrim(mapping_version) <> ''", name="mapping_version_nonblank"),
        CheckConstraint("octet_length(mapping_version) <= 64", name="mapping_version_bounded"),
        CheckConstraint("btrim(objective) <> ''", name="objective_nonblank"),
        CheckConstraint("octet_length(objective) <= 4096", name="objective_bounded"),
        CheckConstraint("timebox_minutes > 0", name="timebox_positive"),
        CheckConstraint(
            "block IN ('sql', 'technical_learning', 'career_pipeline', "
            "'correction_warmup', 'tam_case', 'communication_spoken', "
            "'daily_close', 'saturday_assessment')",
            name="block_allowed",
        ),
        CheckConstraint(
            "jsonb_typeof(output_contract) = 'object' AND "
            "octet_length(output_contract::text) <= 262144",
            name="output_contract_object",
        ),
        CheckConstraint(
            "jsonb_typeof(pass_contract) = 'object' AND "
            "octet_length(pass_contract::text) <= 262144",
            name="pass_contract_object",
        ),
        CheckConstraint(
            "jsonb_typeof(evidence_contract) = 'object' AND "
            "octet_length(evidence_contract::text) <= 262144",
            name="evidence_contract_object",
        ),
        CheckConstraint(
            "jsonb_typeof(source_references) = 'array' AND "
            "jsonb_array_length(source_references) <= 256 AND "
            "octet_length(source_references::text) <= 262144",
            name="source_references_array",
        ),
        CheckConstraint(
            "allowed_ai_role IN ('none', 'planner', 'tutor', 'coach', "
            "'interviewer', 'reviewer', 'analyst')",
            name="allowed_ai_role_allowed",
        ),
        CheckConstraint(
            "source_path IS NULL OR octet_length(source_path) <= 2048", name="source_path_bounded"
        ),
        CheckConstraint(
            "source_anchor IS NULL OR octet_length(source_anchor) <= 512",
            name="source_anchor_bounded",
        ),
        Index("ix_task_definitions_owner_version", "owner_id", "roadmap_version_id"),
        Index(
            "ix_task_definitions_owner_version_node",
            "owner_id",
            "roadmap_version_id",
            "curriculum_node_id",
        ),
        Index("ix_task_definitions_version_block", "roadmap_version_id", "block"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    roadmap_version_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    curriculum_node_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    stable_id: Mapped[str] = mapped_column(Text, nullable=False)
    exercise_type: Mapped[str] = mapped_column(Text, nullable=False)
    mapping_version: Mapped[str] = mapped_column(Text, nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    timebox_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    block: Mapped[str] = mapped_column(Text, nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    output_contract: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    pass_contract: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    evidence_contract: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    source_references: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    allowed_ai_role: Mapped[str] = mapped_column(Text, nullable=False)
    source_path: Mapped[str | None] = mapped_column(Text)
    source_anchor: Mapped[str | None] = mapped_column(Text)


class Resource(Base):
    """A roadmap-assigned resource locator without fetched content."""

    __tablename__ = "resources"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "roadmap_version_id"],
            ["roadmap_versions.owner_id", "roadmap_versions.id"],
            name="fk_resources_owner_version_roadmap_versions",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["owner_id", "roadmap_version_id", "curriculum_node_id"],
            [
                "curriculum_nodes.owner_id",
                "curriculum_nodes.roadmap_version_id",
                "curriculum_nodes.id",
            ],
            name="fk_resources_node_same_version",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["owner_id", "roadmap_version_id", "task_definition_id"],
            [
                "task_definitions.owner_id",
                "task_definitions.roadmap_version_id",
                "task_definitions.id",
            ],
            name="fk_resources_task_same_version",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("roadmap_version_id", "stable_id", name="uq_resources_version_stable_id"),
        CheckConstraint("btrim(stable_id) <> ''", name="stable_id_nonblank"),
        CheckConstraint("octet_length(stable_id) <= 192", name="stable_id_bounded"),
        CheckConstraint("btrim(kind) <> ''", name="kind_nonblank"),
        CheckConstraint("octet_length(kind) <= 64", name="kind_bounded"),
        CheckConstraint("btrim(title) <> ''", name="title_nonblank"),
        CheckConstraint("octet_length(title) <= 512", name="title_bounded"),
        CheckConstraint("btrim(locator) <> ''", name="locator_nonblank"),
        CheckConstraint("octet_length(locator) <= 2048", name="locator_bounded"),
        CheckConstraint(
            "source_path IS NULL OR octet_length(source_path) <= 2048", name="source_path_bounded"
        ),
        CheckConstraint(
            "source_anchor IS NULL OR octet_length(source_anchor) <= 512",
            name="source_anchor_bounded",
        ),
        CheckConstraint("ordinal >= 0", name="ordinal_nonnegative"),
        Index("ix_resources_owner_version", "owner_id", "roadmap_version_id"),
        Index(
            "ix_resources_owner_version_node",
            "owner_id",
            "roadmap_version_id",
            "curriculum_node_id",
        ),
        Index(
            "ix_resources_owner_version_task",
            "owner_id",
            "roadmap_version_id",
            "task_definition_id",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    roadmap_version_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    stable_id: Mapped[str] = mapped_column(Text, nullable=False)
    curriculum_node_id: Mapped[int | None] = mapped_column(BigInteger)
    task_definition_id: Mapped[int | None] = mapped_column(BigInteger)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    locator: Mapped[str] = mapped_column(Text, nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    source_path: Mapped[str | None] = mapped_column(Text)
    source_anchor: Mapped[str | None] = mapped_column(Text)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)


class PassCriterion(Base):
    """An immutable node- or task-level pass criterion."""

    __tablename__ = "pass_criteria"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "roadmap_version_id"],
            ["roadmap_versions.owner_id", "roadmap_versions.id"],
            name="fk_pass_criteria_owner_version_roadmap_versions",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["owner_id", "roadmap_version_id", "curriculum_node_id"],
            [
                "curriculum_nodes.owner_id",
                "curriculum_nodes.roadmap_version_id",
                "curriculum_nodes.id",
            ],
            name="fk_pass_criteria_node_same_version",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["owner_id", "roadmap_version_id", "task_definition_id"],
            [
                "task_definitions.owner_id",
                "task_definitions.roadmap_version_id",
                "task_definitions.id",
            ],
            name="fk_pass_criteria_task_same_version",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "roadmap_version_id", "stable_id", name="uq_pass_criteria_version_stable_id"
        ),
        CheckConstraint("btrim(stable_id) <> ''", name="stable_id_nonblank"),
        CheckConstraint("octet_length(stable_id) <= 192", name="stable_id_bounded"),
        CheckConstraint(
            "num_nonnulls(curriculum_node_id, task_definition_id) = 1", name="exactly_one_target"
        ),
        CheckConstraint("btrim(description) <> ''", name="description_nonblank"),
        CheckConstraint("octet_length(description) <= 4096", name="description_bounded"),
        CheckConstraint(
            "jsonb_typeof(rubric) = 'object' AND octet_length(rubric::text) <= 262144",
            name="rubric_object",
        ),
        CheckConstraint(
            "jsonb_typeof(evidence) = 'object' AND octet_length(evidence::text) <= 262144",
            name="evidence_object",
        ),
        CheckConstraint("ordinal >= 0", name="ordinal_nonnegative"),
        Index("ix_pass_criteria_owner_version", "owner_id", "roadmap_version_id"),
        Index(
            "ix_pass_criteria_owner_version_node",
            "owner_id",
            "roadmap_version_id",
            "curriculum_node_id",
        ),
        Index(
            "ix_pass_criteria_owner_version_task",
            "owner_id",
            "roadmap_version_id",
            "task_definition_id",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    roadmap_version_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    stable_id: Mapped[str] = mapped_column(Text, nullable=False)
    curriculum_node_id: Mapped[int | None] = mapped_column(BigInteger)
    task_definition_id: Mapped[int | None] = mapped_column(BigInteger)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    rubric: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)


class ExitCriterion(Base):
    """An immutable month-exit criterion for one roadmap version."""

    __tablename__ = "exit_criteria"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "roadmap_version_id"],
            ["roadmap_versions.owner_id", "roadmap_versions.id"],
            name="fk_exit_criteria_owner_version_roadmap_versions",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "roadmap_version_id", "stable_id", name="uq_exit_criteria_version_stable_id"
        ),
        CheckConstraint("btrim(stable_id) <> ''", name="stable_id_nonblank"),
        CheckConstraint("octet_length(stable_id) <= 192", name="stable_id_bounded"),
        CheckConstraint("month_number > 0", name="month_number_positive"),
        CheckConstraint("btrim(description) <> ''", name="description_nonblank"),
        CheckConstraint("octet_length(description) <= 4096", name="description_bounded"),
        CheckConstraint(
            "jsonb_typeof(rubric) = 'object' AND octet_length(rubric::text) <= 262144",
            name="rubric_object",
        ),
        CheckConstraint(
            "jsonb_typeof(evidence) = 'object' AND octet_length(evidence::text) <= 262144",
            name="evidence_object",
        ),
        CheckConstraint("ordinal >= 0", name="ordinal_nonnegative"),
        Index("ix_exit_criteria_owner_version", "owner_id", "roadmap_version_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    roadmap_version_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    stable_id: Mapped[str] = mapped_column(Text, nullable=False)
    month_number: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    rubric: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)


class MonthExitReview(Base):
    """A retained, version-scoped month-exit review attempt."""

    __tablename__ = "month_exit_reviews"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "roadmap_version_id"],
            ["roadmap_versions.owner_id", "roadmap_versions.id"],
            name="fk_month_exit_reviews_owner_version_roadmap_versions",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "roadmap_version_id",
            "review_number",
            name="uq_month_exit_reviews_version_review_number",
        ),
        CheckConstraint("review_number > 0", name="review_number_positive"),
        CheckConstraint("state IN ('draft', 'in_progress', 'completed')", name="state_allowed"),
        CheckConstraint("decision IN ('pending', 'advance', 'hold')", name="decision_allowed"),
        CheckConstraint(
            "jsonb_typeof(evidence) = 'object' AND octet_length(evidence::text) <= 1048576",
            name="evidence_object",
        ),
        CheckConstraint(
            "jsonb_typeof(eligibility_evidence) = 'object' AND "
            "octet_length(eligibility_evidence::text) <= 1048576",
            name="eligibility_evidence_object",
        ),
        CheckConstraint(
            "completed_at IS NULL OR completed_at >= started_at", name="completed_after_start"
        ),
        CheckConstraint(
            "(state IN ('draft', 'in_progress') AND decision = 'pending' "
            "AND completed_at IS NULL AND activation_eligible IS NULL) OR "
            "(state = 'completed' AND decision IN ('advance', 'hold') "
            "AND completed_at IS NOT NULL AND activation_eligible IS NOT NULL)",
            name="lifecycle_coherent",
        ),
        Index("ix_month_exit_reviews_owner_version", "owner_id", "roadmap_version_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    roadmap_version_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    review_number: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    decision: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    activation_eligible: Mapped[bool | None] = mapped_column(Boolean)
    eligibility_evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


def _is_persisted_change(target: Base, value: object, old_value: object) -> bool:
    state = inspect(target)
    return (
        not isinstance(old_value, LoaderCallableStatus)
        and (state.persistent or state.detached)
        and value != old_value
    )


_IMMUTABLE_SOURCE_ATTRIBUTES = (
    "owner_id",
    "source_key",
    "name",
    "source_kind",
    "canonical_path",
    "created_at",
)


def _reject_persisted_source_attribute_change(
    target: RoadmapSource,
    value: object,
    old_value: object,
    initiator: object,
) -> object:
    del initiator
    if _is_persisted_change(target, value, old_value):
        raise RoadmapSourceImmutableError("roadmap source provenance is immutable")
    return value


for _attribute_name in _IMMUTABLE_SOURCE_ATTRIBUTES:
    event.listen(
        getattr(RoadmapSource, _attribute_name),
        "set",
        _reject_persisted_source_attribute_change,
        retval=True,
        active_history=True,
    )


def reject_roadmap_source_update(
    mapper: Mapper[RoadmapSource] | None,
    connection: Connection | None,
    target: RoadmapSource,
) -> None:
    del mapper, connection, target
    raise RoadmapSourceImmutableError("roadmap source provenance is immutable")


def reject_roadmap_source_delete(
    mapper: Mapper[RoadmapSource] | None,
    connection: Connection | None,
    target: RoadmapSource,
) -> None:
    del mapper, connection, target
    raise RoadmapSourceImmutableError("roadmap source history is immutable")


event.listen(RoadmapSource, "before_update", reject_roadmap_source_update)
event.listen(RoadmapSource, "before_delete", reject_roadmap_source_delete)


_IMMUTABLE_IMPORT_ATTRIBUTES = (
    "owner_id",
    "source_id",
    "package_hash",
    "object_key",
    "idempotency_key",
    "created_at",
)


def _reject_persisted_import_attribute_change(
    target: RoadmapImport,
    value: object,
    old_value: object,
    initiator: object,
) -> object:
    del initiator
    if _is_persisted_change(target, value, old_value):
        raise RoadmapImportWorkflowError("roadmap import provenance is immutable")
    return value


for _attribute_name in _IMMUTABLE_IMPORT_ATTRIBUTES:
    event.listen(
        getattr(RoadmapImport, _attribute_name),
        "set",
        _reject_persisted_import_attribute_change,
        retval=True,
        active_history=True,
    )


def _validate_import_status_transition(
    target: RoadmapImport,
    value: str,
    old_value: str | LoaderCallableStatus,
    initiator: object,
) -> str:
    del initiator
    if value not in IMPORT_TRANSITIONS:
        raise RoadmapImportWorkflowError("invalid roadmap import transition")
    if _is_persisted_change(target, value, old_value):
        assert isinstance(old_value, str)
        if old_value in _TERMINAL_IMPORT_STATES:
            raise RoadmapImportWorkflowError("terminal roadmap import is immutable")
        if value not in IMPORT_TRANSITIONS.get(old_value, frozenset()):
            raise RoadmapImportWorkflowError("invalid roadmap import transition")
    return value


event.listen(
    RoadmapImport.status,
    "set",
    _validate_import_status_transition,
    retval=True,
    active_history=True,
)


def _import_was_terminal(target: RoadmapImport) -> bool:
    status_history = inspect(target).attrs.status.history
    previous_status = status_history.deleted[0] if status_history.deleted else target.status
    return previous_status in _TERMINAL_IMPORT_STATES


def _validate_import_failure_code(
    target: RoadmapImport,
    value: str | None,
    old_value: str | None | LoaderCallableStatus,
    initiator: object,
) -> str | None:
    del initiator
    if value is not None and value not in IMPORT_FAILURE_CODES:
        raise RoadmapImportWorkflowError("invalid roadmap import failure machine code")
    if _is_persisted_change(target, value, old_value) and _import_was_terminal(target):
        raise RoadmapImportWorkflowError("terminal roadmap import is immutable")
    return value


event.listen(
    RoadmapImport.failure_code,
    "set",
    _validate_import_failure_code,
    retval=True,
    active_history=True,
)


def _reject_terminal_import_result_change(
    target: RoadmapImport,
    value: object,
    old_value: object,
    initiator: object,
) -> object:
    del initiator
    if _is_persisted_change(target, value, old_value) and _import_was_terminal(target):
        raise RoadmapImportWorkflowError("terminal roadmap import is immutable")
    return value


for _attribute_name in (
    "validation_report",
    "semantic_diff",
    "started_at",
    "completed_at",
):
    event.listen(
        getattr(RoadmapImport, _attribute_name),
        "set",
        _reject_terminal_import_result_change,
        retval=True,
        active_history=True,
    )


def _reject_import_timestamp_rewrite(
    target: RoadmapImport,
    value: datetime | None,
    old_value: datetime | None | LoaderCallableStatus,
    initiator: object,
) -> datetime | None:
    del initiator
    if (
        _is_persisted_change(target, value, old_value)
        and old_value is not None
        and not isinstance(old_value, LoaderCallableStatus)
    ):
        raise RoadmapImportWorkflowError("roadmap import timestamps are write-once immutable")
    return value


for _attribute_name in ("started_at", "completed_at"):
    event.listen(
        getattr(RoadmapImport, _attribute_name),
        "set",
        _reject_import_timestamp_rewrite,
        retval=True,
        active_history=True,
    )


def validate_roadmap_import_workflow(
    mapper: Mapper[RoadmapImport] | None,
    connection: Connection | None,
    target: RoadmapImport,
) -> None:
    del mapper, connection
    instance_state = inspect(target)
    status_history = instance_state.attrs.status.history
    previous_status = status_history.deleted[0] if status_history.deleted else target.status
    has_persisted_changes = (instance_state.persistent or instance_state.detached) and any(
        instance_state.attrs[column_name].history.has_changes()
        for column_name in RoadmapImport.__table__.columns.keys()
    )
    if previous_status in _TERMINAL_IMPORT_STATES and has_persisted_changes:
        raise RoadmapImportWorkflowError("terminal roadmap import is immutable")
    if (
        (instance_state.persistent or instance_state.detached)
        and status_history.deleted
        and target.status != previous_status
        and target.status not in IMPORT_TRANSITIONS.get(previous_status, frozenset())
    ):
        raise RoadmapImportWorkflowError("invalid roadmap import transition")

    status = target.status
    if status not in IMPORT_TRANSITIONS:
        raise RoadmapImportWorkflowError("roadmap import lifecycle is not coherent")
    failure_code = target.failure_code
    if failure_code is not None and failure_code not in IMPORT_FAILURE_CODES:
        raise RoadmapImportWorkflowError("invalid roadmap import failure machine code")
    coherent = (
        (
            status == "staged"
            and target.started_at is None
            and target.completed_at is None
            and failure_code is None
        )
        or (
            status == "validating"
            and target.started_at is not None
            and target.completed_at is None
            and failure_code is None
        )
        or (
            status in {"validated", "imported"}
            and target.started_at is not None
            and target.completed_at is not None
            and failure_code is None
        )
        or (
            status in {"rejected", "failed"}
            and target.started_at is not None
            and target.completed_at is not None
            and failure_code in IMPORT_FAILURE_CODES
        )
    )
    if not coherent:
        raise RoadmapImportWorkflowError("roadmap import lifecycle fields are not coherent")


def reject_roadmap_import_delete(
    mapper: Mapper[RoadmapImport] | None,
    connection: Connection | None,
    target: RoadmapImport,
) -> None:
    del mapper, connection, target
    raise RoadmapImportWorkflowError("roadmap import history is immutable")


def validate_roadmap_import_initial_insert(
    mapper: Mapper[RoadmapImport] | None,
    connection: Connection | None,
    target: RoadmapImport,
) -> None:
    del mapper, connection
    if (
        target.status != "staged"
        or target.started_at is not None
        or target.completed_at is not None
        or target.failure_code is not None
    ):
        raise RoadmapImportWorkflowError("new roadmap imports require the initial staged lifecycle")


event.listen(RoadmapImport, "before_insert", validate_roadmap_import_initial_insert)
event.listen(RoadmapImport, "before_insert", validate_roadmap_import_workflow)
event.listen(RoadmapImport, "before_update", validate_roadmap_import_workflow)
event.listen(RoadmapImport, "before_delete", reject_roadmap_import_delete)


_IMMUTABLE_VERSION_ATTRIBUTES = (
    "owner_id",
    "source_id",
    "version_key",
    "version_number",
    "month_number",
    "predecessor_id",
    "content_hash",
    "object_key",
    "manifest",
    "raw_payload",
    "normalized_payload",
    "created_at",
)


def _reject_persisted_version_attribute_change(
    target: RoadmapVersion,
    value: object,
    old_value: object,
    initiator: object,
) -> object:
    del initiator
    if _is_persisted_change(target, value, old_value):
        raise RoadmapVersionImmutableError("roadmap version provenance is immutable")
    return value


for _attribute_name in _IMMUTABLE_VERSION_ATTRIBUTES:
    event.listen(
        getattr(RoadmapVersion, _attribute_name),
        "set",
        _reject_persisted_version_attribute_change,
        retval=True,
        active_history=True,
    )


def _validate_version_state_transition(
    target: RoadmapVersion,
    value: str,
    old_value: str | LoaderCallableStatus,
    initiator: object,
) -> str:
    del initiator
    if value not in VERSION_STATE_TRANSITIONS:
        raise RoadmapVersionWorkflowError("invalid roadmap state transition")
    if _is_persisted_change(target, value, old_value):
        assert isinstance(old_value, str)
        if value not in VERSION_STATE_TRANSITIONS.get(old_value, frozenset()):
            raise RoadmapVersionWorkflowError("invalid roadmap state transition")
    return value


event.listen(
    RoadmapVersion.state,
    "set",
    _validate_version_state_transition,
    retval=True,
    active_history=True,
)


def _reject_version_timestamp_rewrite(
    target: RoadmapVersion,
    value: datetime | None,
    old_value: datetime | None | LoaderCallableStatus,
    initiator: object,
) -> datetime | None:
    del initiator
    if (
        _is_persisted_change(target, value, old_value)
        and old_value is not None
        and not isinstance(old_value, LoaderCallableStatus)
    ):
        raise RoadmapVersionWorkflowError("roadmap lifecycle timestamps are write-once")
    return value


for _attribute_name in ("approved_at", "activated_at", "superseded_at"):
    event.listen(
        getattr(RoadmapVersion, _attribute_name),
        "set",
        _reject_version_timestamp_rewrite,
        retval=True,
        active_history=True,
    )


def _validate_mirror_status_transition(
    target: RoadmapVersion,
    value: str,
    old_value: str | LoaderCallableStatus,
    initiator: object,
) -> str:
    del initiator
    if value not in MIRROR_TRANSITIONS:
        raise RoadmapVersionWorkflowError("invalid roadmap mirror transition")
    if _is_persisted_change(target, value, old_value):
        assert isinstance(old_value, str)
        if old_value in _TERMINAL_MIRROR_STATES:
            raise RoadmapVersionWorkflowError("terminal roadmap mirror is immutable")
        if value not in MIRROR_TRANSITIONS.get(old_value, frozenset()):
            raise RoadmapVersionWorkflowError("invalid roadmap mirror transition")
    return value


event.listen(
    RoadmapVersion.mirror_status,
    "set",
    _validate_mirror_status_transition,
    retval=True,
    active_history=True,
)


def _mirror_was_terminal(target: RoadmapVersion) -> bool:
    status_history = inspect(target).attrs.mirror_status.history
    previous_status = status_history.deleted[0] if status_history.deleted else target.mirror_status
    return previous_status in _TERMINAL_MIRROR_STATES


def _validate_mirror_error_code(
    target: RoadmapVersion,
    value: str | None,
    old_value: str | None | LoaderCallableStatus,
    initiator: object,
) -> str | None:
    del initiator
    if value is not None and value not in MIRROR_ERROR_CODES:
        raise RoadmapVersionWorkflowError("invalid roadmap mirror error machine code")
    if _is_persisted_change(target, value, old_value) and _mirror_was_terminal(target):
        raise RoadmapVersionWorkflowError("terminal roadmap mirror is immutable")
    return value


event.listen(
    RoadmapVersion.mirror_error_code,
    "set",
    _validate_mirror_error_code,
    retval=True,
    active_history=True,
)


def _reject_terminal_mirror_ref_change(
    target: RoadmapVersion,
    value: str | None,
    old_value: str | None | LoaderCallableStatus,
    initiator: object,
) -> str | None:
    del initiator
    if _is_persisted_change(target, value, old_value) and _mirror_was_terminal(target):
        raise RoadmapVersionWorkflowError("terminal roadmap mirror is immutable")
    return value


event.listen(
    RoadmapVersion.mirror_ref,
    "set",
    _reject_terminal_mirror_ref_change,
    retval=True,
    active_history=True,
)


def validate_roadmap_version_workflow(
    mapper: Mapper[RoadmapVersion] | None,
    connection: Connection | None,
    target: RoadmapVersion,
) -> None:
    del mapper, connection
    instance_state = inspect(target)
    if (instance_state.persistent or instance_state.detached) and any(
        instance_state.attrs[attribute_name].history.has_changes()
        for attribute_name in _IMMUTABLE_VERSION_ATTRIBUTES
    ):
        raise RoadmapVersionImmutableError("roadmap version provenance is immutable")

    state = target.state
    state_history = instance_state.attrs.state.history
    if (
        (instance_state.persistent or instance_state.detached)
        and state_history.deleted
        and state != state_history.deleted[0]
        and state not in VERSION_STATE_TRANSITIONS.get(state_history.deleted[0], frozenset())
    ):
        raise RoadmapVersionWorkflowError("invalid roadmap state transition")
    state_coherent = (
        (
            state == "draft"
            and target.approved_at is None
            and target.activated_at is None
            and target.superseded_at is None
        )
        or (
            state == "approved"
            and target.approved_at is not None
            and target.activated_at is None
            and target.superseded_at is None
        )
        or (
            state == "active"
            and target.approved_at is not None
            and target.activated_at is not None
            and target.superseded_at is None
        )
        or (
            state == "superseded"
            and target.approved_at is not None
            and target.activated_at is not None
            and target.superseded_at is not None
        )
    )
    if not state_coherent:
        raise RoadmapVersionWorkflowError("roadmap state lifecycle is not coherent")

    mirror_status = target.mirror_status
    mirror_status_history = instance_state.attrs.mirror_status.history
    if (
        (instance_state.persistent or instance_state.detached)
        and mirror_status_history.deleted
        and mirror_status != mirror_status_history.deleted[0]
        and mirror_status
        not in MIRROR_TRANSITIONS.get(mirror_status_history.deleted[0], frozenset())
    ):
        raise RoadmapVersionWorkflowError("invalid roadmap mirror transition")
    mirror_ref = target.mirror_ref
    mirror_error_code = target.mirror_error_code
    if mirror_error_code is not None and mirror_error_code not in MIRROR_ERROR_CODES:
        raise RoadmapVersionWorkflowError("invalid roadmap mirror error machine code")
    mirror_coherent = (
        (
            mirror_status in {"pending", "syncing", "not_required"}
            and mirror_ref is None
            and mirror_error_code is None
        )
        or (
            mirror_status == "synced"
            and mirror_ref is not None
            and bool(mirror_ref.strip())
            and mirror_error_code is None
        )
        or (
            mirror_status == "failed"
            and mirror_ref is None
            and mirror_error_code in MIRROR_ERROR_CODES
        )
    )
    if not mirror_coherent:
        raise RoadmapVersionWorkflowError("roadmap mirror fields are not coherent")


def validate_roadmap_version_initial_insert(
    mapper: Mapper[RoadmapVersion] | None,
    connection: Connection | None,
    target: RoadmapVersion,
) -> None:
    del mapper, connection
    if (
        target.state != "draft"
        or target.approved_at is not None
        or target.activated_at is not None
        or target.superseded_at is not None
    ):
        raise RoadmapVersionWorkflowError(
            "new roadmap versions require the initial draft lifecycle"
        )
    if (
        target.mirror_status not in {"pending", "not_required"}
        or target.mirror_ref is not None
        or target.mirror_error_code is not None
    ):
        raise RoadmapVersionWorkflowError("new roadmap versions require an initial mirror state")


event.listen(RoadmapVersion, "before_insert", validate_roadmap_version_initial_insert)
event.listen(RoadmapVersion, "before_insert", validate_roadmap_version_workflow)
event.listen(RoadmapVersion, "before_update", validate_roadmap_version_workflow)


def reject_curriculum_content_update(
    mapper: Mapper[Base] | None,
    connection: Connection | None,
    target: Base,
) -> None:
    del mapper, connection, target
    raise CurriculumContentImmutableError("imported curriculum content is immutable")


def reject_curriculum_content_delete(
    mapper: Mapper[Base] | None,
    connection: Connection | None,
    target: Base,
) -> None:
    del mapper, connection, target
    raise CurriculumContentImmutableError("imported curriculum content is immutable")


for _content_model in (
    CurriculumNode,
    TaskDefinition,
    Resource,
    PassCriterion,
    ExitCriterion,
):
    event.listen(_content_model, "before_update", reject_curriculum_content_update)
    event.listen(_content_model, "before_delete", reject_curriculum_content_delete)


__all__ = [
    "CurriculumContentImmutableError",
    "CurriculumNode",
    "ExitCriterion",
    "IMPORT_FAILURE_CODES",
    "IMPORT_TRANSITIONS",
    "MIRROR_ERROR_CODES",
    "MIRROR_TRANSITIONS",
    "MonthExitReview",
    "PassCriterion",
    "Resource",
    "RoadmapImport",
    "RoadmapImportWorkflowError",
    "RoadmapSource",
    "RoadmapSourceImmutableError",
    "RoadmapVersion",
    "RoadmapVersionImmutableError",
    "RoadmapVersionWorkflowError",
    "TaskDefinition",
    "VERSION_STATE_TRANSITIONS",
    "reject_roadmap_import_delete",
    "reject_roadmap_source_delete",
    "reject_roadmap_source_update",
    "reject_curriculum_content_delete",
    "reject_curriculum_content_update",
    "validate_roadmap_import_workflow",
    "validate_roadmap_import_initial_insert",
    "validate_roadmap_version_initial_insert",
    "validate_roadmap_version_workflow",
]

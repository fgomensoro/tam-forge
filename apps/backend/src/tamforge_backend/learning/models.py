"""Persistent study activity state and immutable learning evidence."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, cast

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    LargeBinary,
    Text,
    UniqueConstraint,
    and_,
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


class ActivityWorkflowError(ValueError):
    """Raised when an activity violates its persisted state machine."""


class StudyDayWorkflowError(ValueError):
    """Raised when a study day violates its persisted state machine."""


class AttemptWorkflowError(ValueError):
    """Raised when an attempt violates the A/B evidence contract."""


class TimerWorkflowError(ValueError):
    """Raised when a timer mutation would corrupt measured time."""


class AppendOnlyLearningEvidenceError(ValueError):
    """Raised when historical learning evidence is mutated or deleted."""


ACTIVITY_STATES = frozenset(
    {
        "ready",
        "active",
        "paused",
        "output_committed",
        "self_review_complete",
        "ai_processing",
        "feedback_ready",
        "correction_due",
        "demonstrated",
        "needs_work",
        "incomplete",
        "superseded",
    }
)
ACTIVITY_TRANSITIONS = {
    "ready": frozenset({"active"}),
    "active": frozenset({"paused", "output_committed", "incomplete"}),
    "paused": frozenset({"active", "incomplete"}),
    "output_committed": frozenset({"self_review_complete"}),
    "self_review_complete": frozenset({"ai_processing"}),
    "ai_processing": frozenset({"feedback_ready"}),
    "feedback_ready": frozenset({"correction_due"}),
    "correction_due": frozenset({"demonstrated", "needs_work"}),
    "demonstrated": frozenset(),
    "needs_work": frozenset(),
    "incomplete": frozenset(),
    "superseded": frozenset(),
}
ATTEMPT_KINDS = frozenset({"none", "attempt_a", "attempt_b", "no_ai_assessment", "real_interview"})
SAVED_ATTEMPT_KINDS = ATTEMPT_KINDS - {"none"}
ASSISTANCE_MODES = frozenset(
    {"none", "coach_preparation", "hint_ladder", "time_expired", "reference_only"}
)
STUDY_DAY_TRANSITIONS = {
    "planned": frozenset({"in_progress", "skipped"}),
    "in_progress": frozenset({"closed", "incomplete"}),
    "closed": frozenset(),
    "incomplete": frozenset(),
    "skipped": frozenset(),
}


class LearnerSetting(Base):
    """Single owner's local-study settings and selected roadmap."""

    __tablename__ = "learner_settings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "active_roadmap_version_id"],
            ["roadmap_versions.owner_id", "roadmap_versions.id"],
            name="fk_learner_settings_owner_active_version_roadmap_versions",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("owner_id", name="uq_learner_settings_owner_id"),
        CheckConstraint(
            "octet_length(timezone) BETWEEN 3 AND 64 "
            "AND timezone ~ '^[A-Za-z][A-Za-z0-9_+-]*/[A-Za-z0-9_+./-]+$' "
            "AND timezone !~ '\\.\\.'",
            name="timezone_iana_shape",
        ),
        Index(
            "ix_learner_settings_owner_active_version",
            "owner_id",
            "active_roadmap_version_id",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("owners.id", name="fk_learner_settings_owner_id_owners", ondelete="RESTRICT"),
        nullable=False,
    )
    timezone: Mapped[str] = mapped_column(Text, nullable=False)
    study_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    active_roadmap_version_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        onupdate=utc_now,
        nullable=False,
    )


class StudyDay(Base):
    """One owner-local calendar day bound to an immutable roadmap version."""

    __tablename__ = "study_days"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "roadmap_version_id"],
            ["roadmap_versions.owner_id", "roadmap_versions.id"],
            name="fk_study_days_owner_version_roadmap_versions",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("owner_id", "local_date", name="uq_study_days_owner_local_date"),
        UniqueConstraint(
            "owner_id",
            "roadmap_version_id",
            "id",
            name="uq_study_days_owner_version_id_id",
        ),
        CheckConstraint(
            "planned_minutes BETWEEN 0 AND 255 AND focused_minutes BETWEEN 0 AND 255",
            name="minutes_bounded",
        ),
        CheckConstraint(
            "day_type IN ('weekday', 'saturday', 'sunday', 'interview')",
            name="day_type_allowed",
        ),
        CheckConstraint(
            "(day_type = 'sunday' AND planned_minutes = 0) OR "
            "(day_type = 'saturday' AND planned_minutes <= 120) OR "
            "day_type IN ('weekday', 'interview')",
            name="day_minutes_coherent",
        ),
        CheckConstraint(
            "status IN ('planned', 'in_progress', 'closed', 'incomplete', 'skipped')",
            name="status_allowed",
        ),
        CheckConstraint(
            "started_at IS NULL OR started_at >= created_at",
            name="started_after_creation",
        ),
        CheckConstraint(
            "closed_at IS NULL OR closed_at >= COALESCE(started_at, created_at)",
            name="closed_after_start",
        ),
        CheckConstraint(
            "(status = 'planned' AND started_at IS NULL AND closed_at IS NULL) OR "
            "(status = 'in_progress' AND started_at IS NOT NULL AND closed_at IS NULL) OR "
            "(status IN ('closed', 'incomplete') AND started_at IS NOT NULL "
            "AND closed_at IS NOT NULL) OR "
            "(status = 'skipped' AND closed_at IS NOT NULL)",
            name="lifecycle_coherent",
        ),
        Index("ix_study_days_owner_local_date", "owner_id", "local_date"),
        Index("ix_study_days_owner_version", "owner_id", "roadmap_version_id"),
        Index("ix_study_days_status_local_date", "status", "local_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    roadmap_version_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    local_date: Mapped[date] = mapped_column(Date, nullable=False)
    planned_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    focused_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    day_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ActivityInstance(Base):
    """One scheduled execution of a versioned task with frozen task snapshots."""

    __tablename__ = "activity_instances"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "roadmap_version_id", "study_day_id"],
            ["study_days.owner_id", "study_days.roadmap_version_id", "study_days.id"],
            name="fk_activity_instances_owner_version_day_study_days",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["owner_id", "roadmap_version_id", "task_definition_id"],
            [
                "task_definitions.owner_id",
                "task_definitions.roadmap_version_id",
                "task_definitions.id",
            ],
            name="fk_activity_instances_owner_version_task_task_definitions",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
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
        ForeignKeyConstraint(
            ["owner_id", "stronger_evidence_activity_id"],
            ["activity_instances.owner_id", "activity_instances.id"],
            name="fk_activity_instances_owner_stronger_activity",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("owner_id", "id", name="uq_activity_instances_owner_id_id"),
        UniqueConstraint(
            "owner_id",
            "study_day_id",
            "id",
            name="uq_activity_instances_owner_study_id_id",
        ),
        UniqueConstraint(
            "owner_id",
            "study_day_id",
            "task_definition_id",
            "id",
            name="uq_activity_instances_owner_study_task_id",
        ),
        UniqueConstraint(
            "owner_id",
            "study_day_id",
            "task_definition_id",
            "replacement_version",
            name="uq_activity_instances_owner_study_task_replacement",
        ),
        CheckConstraint(
            "btrim(task_stable_id_snapshot) <> '' AND octet_length(task_stable_id_snapshot) <= 192",
            name="task_stable_id_snapshot_bounded",
        ),
        CheckConstraint(
            "btrim(task_mapping_version_snapshot) <> '' AND "
            "octet_length(task_mapping_version_snapshot) <= 64",
            name="task_mapping_version_snapshot_bounded",
        ),
        CheckConstraint(
            "btrim(task_objective_snapshot) <> '' AND "
            "octet_length(task_objective_snapshot) <= 4096",
            name="task_objective_snapshot_bounded",
        ),
        CheckConstraint("task_timebox_minutes_snapshot > 0", name="task_timebox_snapshot_positive"),
        CheckConstraint(
            "btrim(roadmap_version_key_snapshot) <> '' AND "
            "octet_length(roadmap_version_key_snapshot) <= 128",
            name="roadmap_version_key_snapshot_bounded",
        ),
        CheckConstraint(
            "state IN ('ready', 'active', 'paused', 'output_committed', 'self_review_complete', "
            "'ai_processing', 'feedback_ready', 'correction_due', 'demonstrated', "
            "'needs_work', 'incomplete', 'superseded')",
            name="state_allowed",
        ),
        CheckConstraint(
            "attempt_kind IN ('none', 'attempt_a', 'attempt_b', "
            "'no_ai_assessment', 'real_interview')",
            name="attempt_kind_allowed",
        ),
        CheckConstraint(
            "assistance_mode IN ('none', 'coach_preparation', 'hint_ladder', "
            "'time_expired', 'reference_only')",
            name="assistance_mode_allowed",
        ),
        CheckConstraint(
            "classification IN ('required', 'useful', 'optional', 'superseded')",
            name="classification_allowed",
        ),
        CheckConstraint(
            "(classification = 'superseded') = (stronger_evidence_activity_id IS NOT NULL)",
            name="stronger_evidence_classification_coherent",
        ),
        CheckConstraint(
            "stronger_evidence_activity_id IS NULL OR stronger_evidence_activity_id <> id",
            name="stronger_evidence_not_self",
        ),
        CheckConstraint("timebox_minutes > 0 AND timebox_minutes <= 255", name="timebox_bounded"),
        CheckConstraint("optimistic_version > 0", name="optimistic_version_positive"),
        CheckConstraint("replacement_version > 0", name="replacement_version_positive"),
        CheckConstraint(
            "(replacement_version = 1 AND replaces_activity_id IS NULL) OR "
            "(replacement_version > 1 AND replaces_activity_id IS NOT NULL)",
            name="replacement_coherent",
        ),
        CheckConstraint(
            "started_at IS NULL OR started_at >= created_at",
            name="started_after_creation",
        ),
        CheckConstraint(
            "output_committed_at IS NULL OR output_committed_at >= started_at",
            name="output_committed_after_start",
        ),
        CheckConstraint(
            "completed_at IS NULL OR completed_at >= "
            "COALESCE(output_committed_at, started_at, created_at)",
            name="completed_after_progress",
        ),
        Index("ix_activity_instances_owner_study_order", "owner_id", "study_day_id", "id"),
        Index(
            "ix_activity_instances_owner_version_day",
            "owner_id",
            "roadmap_version_id",
            "study_day_id",
        ),
        Index(
            "ix_activity_instances_owner_version_task",
            "owner_id",
            "roadmap_version_id",
            "task_definition_id",
        ),
        Index(
            "ix_activity_instances_owner_study_task_replaces",
            "owner_id",
            "study_day_id",
            "task_definition_id",
            "replaces_activity_id",
        ),
        Index(
            "ix_activity_instances_owner_stronger_evidence",
            "owner_id",
            "stronger_evidence_activity_id",
        ),
        Index("ix_activity_instances_state", "state"),
        Index(
            "ix_activity_instances_pending_self_review",
            "owner_id",
            "output_committed_at",
            postgresql_where=text("state = 'output_committed'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    study_day_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    roadmap_version_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    task_definition_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    task_stable_id_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    task_mapping_version_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    task_objective_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    task_timebox_minutes_snapshot: Mapped[int] = mapped_column(Integer, nullable=False)
    roadmap_version_key_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    attempt_kind: Mapped[str] = mapped_column(Text, nullable=False)
    assistance_mode: Mapped[str] = mapped_column(Text, nullable=False)
    classification: Mapped[str] = mapped_column(Text, nullable=False)
    timebox_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    source_hidden: Mapped[bool] = mapped_column(Boolean, nullable=False)
    optimistic_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    replacement_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    replaces_activity_id: Mapped[int | None] = mapped_column(BigInteger)
    stronger_evidence_activity_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    output_committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ActivityTimerSession(Base):
    """One idempotently created measured-time interval for an activity."""

    __tablename__ = "activity_timer_sessions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "activity_instance_id"],
            ["activity_instances.owner_id", "activity_instances.id"],
            name="fk_activity_timer_sessions_owner_activity_activity_instances",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "owner_id",
            "idempotency_key",
            name="uq_activity_timer_sessions_owner_idempotency",
        ),
        CheckConstraint("btrim(idempotency_key) <> ''", name="idempotency_key_nonblank"),
        CheckConstraint("octet_length(idempotency_key) <= 256", name="idempotency_key_bounded"),
        CheckConstraint("counted_seconds BETWEEN 0 AND 918000", name="counted_seconds_bounded"),
        CheckConstraint("last_client_sequence >= 0", name="last_client_sequence_nonnegative"),
        CheckConstraint(
            "last_heartbeat_at >= started_at "
            "AND (paused_at IS NULL OR paused_at >= started_at) "
            "AND (ended_at IS NULL OR ended_at >= "
            "COALESCE(paused_at, last_heartbeat_at, started_at)) "
            "AND (ended_at IS NULL OR last_heartbeat_at <= ended_at)",
            name="timestamps_coherent",
        ),
        Index(
            "ix_activity_timer_sessions_owner_activity",
            "owner_id",
            "activity_instance_id",
        ),
        Index(
            "uq_activity_timer_sessions_one_open_per_activity",
            "activity_instance_id",
            unique=True,
            postgresql_where=text("ended_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    activity_instance_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    counted_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_client_sequence: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )


class Attempt(Base):
    """One immutable committed independent performance artifact."""

    __tablename__ = "attempts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "activity_instance_id"],
            ["activity_instances.owner_id", "activity_instances.id"],
            name="fk_attempts_owner_activity_activity_instances",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["owner_id", "parent_attempt_id"],
            ["attempts.owner_id", "attempts.id"],
            name="fk_attempts_owner_parent_attempts",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("owner_id", "id", name="uq_attempts_owner_id_id"),
        UniqueConstraint(
            "owner_id",
            "activity_instance_id",
            "id",
            name="uq_attempts_owner_activity_id_id",
        ),
        UniqueConstraint(
            "owner_id",
            "activity_instance_id",
            "attempt_kind",
            name="uq_attempts_owner_activity_kind",
        ),
        CheckConstraint(
            "attempt_kind IN ('attempt_a', 'attempt_b', 'no_ai_assessment', 'real_interview')",
            name="attempt_kind_allowed",
        ),
        CheckConstraint(
            "(attempt_kind = 'attempt_b' AND parent_attempt_id IS NOT NULL) OR "
            "(attempt_kind <> 'attempt_b' AND parent_attempt_id IS NULL)",
            name="ab_relation_coherent",
        ),
        CheckConstraint(
            "num_nonnulls(original_text, original_markdown, original_sql) >= 1",
            name="original_payload_present",
        ),
        CheckConstraint(
            "(original_text IS NULL OR (btrim(original_text) <> '' "
            "AND octet_length(original_text) <= 4194304)) "
            "AND (original_markdown IS NULL OR (btrim(original_markdown) <> '' "
            "AND octet_length(original_markdown) <= 4194304)) "
            "AND (original_sql IS NULL OR (btrim(original_sql) <> '' "
            "AND octet_length(original_sql) <= 4194304))",
            name="original_payload_bounded",
        ),
        CheckConstraint(
            "btrim(audience) <> '' AND octet_length(audience) <= 256", name="audience_bounded"
        ),
        CheckConstraint(
            "btrim(prompt) <> '' AND octet_length(prompt) <= 1048576", name="prompt_bounded"
        ),
        CheckConstraint(
            "assistance_mode IN ('none', 'coach_preparation', 'hint_ladder', "
            "'time_expired', 'reference_only')",
            name="assistance_mode_allowed",
        ),
        CheckConstraint("octet_length(commitment_hash) = 32", name="commitment_hash_length"),
        CheckConstraint("committed_at >= created_at", name="committed_after_creation"),
        Index("ix_attempts_owner_activity", "owner_id", "activity_instance_id"),
        Index("ix_attempts_owner_parent", "owner_id", "parent_attempt_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    activity_instance_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    attempt_kind: Mapped[str] = mapped_column(Text, nullable=False)
    parent_attempt_id: Mapped[int | None] = mapped_column(BigInteger)
    original_text: Mapped[str | None] = mapped_column(Text)
    original_markdown: Mapped[str | None] = mapped_column(Text)
    original_sql: Mapped[str | None] = mapped_column(Text)
    audience: Mapped[str] = mapped_column(Text, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    assistance_mode: Mapped[str] = mapped_column(Text, nullable=False)
    commitment_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    committed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )


class Artifact(Base):
    """Owner-scoped content-addressed immutable object metadata."""

    __tablename__ = "artifacts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "derived_from_artifact_id"],
            ["artifacts.owner_id", "artifacts.id"],
            name="fk_artifacts_owner_derived_from_artifacts",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("owner_id", "id", name="uq_artifacts_owner_id_id"),
        UniqueConstraint("owner_id", "object_key", name="uq_artifacts_owner_object_key"),
        UniqueConstraint("owner_id", "content_hash", name="uq_artifacts_owner_content_hash"),
        CheckConstraint("btrim(object_key) <> ''", name="object_key_nonblank"),
        CheckConstraint(
            "octet_length(object_key) <= 1024 AND object_key !~ '^[a-z][a-z0-9+.-]*://' "
            "AND object_key !~ '(^|/)\\.\\.(/|$)' AND object_key !~ '[[:cntrl:]]'",
            name="object_key_private_bounded",
        ),
        CheckConstraint("octet_length(content_hash) = 32", name="content_hash_length"),
        CheckConstraint(
            "content_type ~ '^[a-z0-9][a-z0-9.+-]*/[a-z0-9][a-z0-9.+-]*$' "
            "AND octet_length(content_type) <= 128",
            name="content_type_safe",
        ),
        CheckConstraint(
            "btrim(original_filename) <> '' AND octet_length(original_filename) <= 512 "
            "AND original_filename !~ '[/\\\\]' AND original_filename !~ '[[:cntrl:]]'",
            name="original_filename_safe",
        ),
        CheckConstraint("byte_size >= 0", name="byte_size_nonnegative"),
        CheckConstraint(
            "artifact_class IN ('original_audio', 'transcript', 'written_output', "
            "'sql_output', 'recall_note', 'case_artifact', 'analysis', 'export')",
            name="artifact_class_allowed",
        ),
        CheckConstraint(
            "jsonb_typeof(encryption_metadata) = 'object' "
            "AND octet_length(encryption_metadata::text) <= 2048",
            name="encryption_metadata_object",
        ),
        CheckConstraint(
            "public.tamforge_validate_encryption_metadata_v1(encryption_metadata)",
            name="encryption_metadata_v1",
        ),
        CheckConstraint("immutable_version > 0", name="immutable_version_positive"),
        CheckConstraint(
            "derived_from_artifact_id IS NULL OR derived_from_artifact_id <> id",
            name="lineage_not_self",
        ),
        Index("ix_artifacts_owner_derived_from", "owner_id", "derived_from_artifact_id"),
        Index("ix_artifacts_owner_class_created", "owner_id", "artifact_class", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("owners.id", name="fk_artifacts_owner_id_owners", ondelete="RESTRICT"),
        nullable=False,
    )
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    content_type: Mapped[str] = mapped_column(Text, nullable=False)
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    artifact_class: Mapped[str] = mapped_column(Text, nullable=False)
    encryption_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    derived_from_artifact_id: Mapped[int | None] = mapped_column(BigInteger)
    immutable_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )


class ActivityArtifactLink(Base):
    """Append-only binding from an activity/attempt to a reusable artifact."""

    __tablename__ = "activity_artifact_links"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "activity_instance_id"],
            ["activity_instances.owner_id", "activity_instances.id"],
            name="fk_activity_artifact_links_owner_activity_activity_instances",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["owner_id", "activity_instance_id", "attempt_id"],
            ["attempts.owner_id", "attempts.activity_instance_id", "attempts.id"],
            name="fk_activity_artifact_links_owner_activity_attempt_attempts",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["owner_id", "artifact_id"],
            ["artifacts.owner_id", "artifacts.id"],
            name="fk_activity_artifact_links_owner_artifact_artifacts",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "link_role IN ('original_output', 'presentation_audio', 'transcript', "
            "'analysis', 'supporting', 'correction')",
            name="role_allowed",
        ),
        Index(
            "ix_activity_artifact_links_owner_activity",
            "owner_id",
            "activity_instance_id",
        ),
        Index(
            "ix_activity_artifact_links_owner_activity_attempt",
            "owner_id",
            "activity_instance_id",
            "attempt_id",
        ),
        Index("ix_activity_artifact_links_owner_artifact", "owner_id", "artifact_id"),
        Index(
            "uq_activity_artifact_links_without_attempt",
            "owner_id",
            "activity_instance_id",
            "artifact_id",
            "link_role",
            unique=True,
            postgresql_where=text("attempt_id IS NULL"),
        ),
        Index(
            "uq_activity_artifact_links_with_attempt",
            "owner_id",
            "activity_instance_id",
            "attempt_id",
            "artifact_id",
            "link_role",
            unique=True,
            postgresql_where=text("attempt_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    activity_instance_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    attempt_id: Mapped[int | None] = mapped_column(BigInteger)
    artifact_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    link_role: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )


class SelfReview(Base):
    """Required learner reflection retained separately from external scoring."""

    __tablename__ = "self_reviews"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "activity_instance_id", "attempt_id"],
            ["attempts.owner_id", "attempts.activity_instance_id", "attempts.id"],
            name="fk_self_reviews_owner_activity_attempt_attempts",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "owner_id",
            "activity_instance_id",
            "attempt_id",
            name="uq_self_reviews_owner_activity_attempt",
        ),
        CheckConstraint(
            "btrim(main_answer) <> '' AND octet_length(main_answer) <= 8192 "
            "AND btrim(did_well) <> '' AND octet_length(did_well) <= 8192 "
            "AND btrim(structure_weakness) <> '' AND octet_length(structure_weakness) <= 8192 "
            "AND btrim(vague_points) <> '' AND octet_length(vague_points) <= 8192 "
            "AND btrim(hesitation_points) <> '' AND octet_length(hesitation_points) <= 8192 "
            "AND btrim(change_next) <> '' AND octet_length(change_next) <= 8192",
            name="answers_required_bounded",
        ),
        CheckConstraint("self_score BETWEEN 0 AND 4", name="score_range"),
        Index(
            "ix_self_reviews_owner_activity_attempt",
            "owner_id",
            "activity_instance_id",
            "attempt_id",
        ),
        Index("ix_self_reviews_owner_submitted", "owner_id", "submitted_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    activity_instance_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    attempt_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    main_answer: Mapped[str] = mapped_column(Text, nullable=False)
    did_well: Mapped[str] = mapped_column(Text, nullable=False)
    structure_weakness: Mapped[str] = mapped_column(Text, nullable=False)
    vague_points: Mapped[str] = mapped_column(Text, nullable=False)
    hesitation_points: Mapped[str] = mapped_column(Text, nullable=False)
    change_next: Mapped[str] = mapped_column(Text, nullable=False)
    self_score: Mapped[int] = mapped_column(Integer, nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )


class AdaptiveChange(Base):
    """Append-only explanation of one evidence-backed adaptive scheduling change."""

    __tablename__ = "adaptive_changes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "roadmap_version_id", "study_day_id"],
            ["study_days.owner_id", "study_days.roadmap_version_id", "study_days.id"],
            name="fk_adaptive_changes_owner_version_day_study_days",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["owner_id", "study_day_id", "activity_instance_id"],
            [
                "activity_instances.owner_id",
                "activity_instances.study_day_id",
                "activity_instances.id",
            ],
            name="fk_adaptive_changes_owner_day_activity_activity_instances",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "btrim(what_changed) <> '' AND octet_length(what_changed) <= 4096", name="what_bounded"
        ),
        CheckConstraint(
            "btrim(why_changed) <> '' AND octet_length(why_changed) <= 4096", name="why_bounded"
        ),
        CheckConstraint(
            "jsonb_typeof(evidence_manifest) = 'object' "
            "AND octet_length(evidence_manifest::text) <= 16384",
            name="evidence_manifest_object",
        ),
        CheckConstraint(
            "public.tamforge_validate_evidence_manifest_v1(evidence_manifest)",
            name="evidence_manifest_v1",
        ),
        CheckConstraint(
            "btrim(roadmap_objective) <> '' AND octet_length(roadmap_objective) <= 4096",
            name="roadmap_objective_bounded",
        ),
        CheckConstraint(
            "coverage_impact IN ('none', 'rescheduled_required', "
            "'replaced_adaptive', 'reduced_optional')",
            name="coverage_impact_allowed",
        ),
        CheckConstraint(
            "(coverage_impact = 'none' AND affects_required_coverage = false) OR "
            "coverage_impact <> 'none'",
            name="coverage_impact_coherent",
        ),
        CheckConstraint(
            "time_impact IN ('none', 'reallocated', 'reduced', 'increased')",
            name="time_impact_allowed",
        ),
        CheckConstraint(
            "(time_impact = 'none' AND planned_time_delta_minutes = 0) OR "
            "(time_impact = 'reallocated' AND planned_time_delta_minutes = 0) OR "
            "(time_impact = 'reduced' AND planned_time_delta_minutes BETWEEN -255 AND -1) OR "
            "(time_impact = 'increased' AND planned_time_delta_minutes BETWEEN 1 AND 255)",
            name="time_impact_coherent",
        ),
        Index("ix_adaptive_changes_owner_study", "owner_id", "roadmap_version_id", "study_day_id"),
        Index(
            "ix_adaptive_changes_owner_day_activity",
            "owner_id",
            "study_day_id",
            "activity_instance_id",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    roadmap_version_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    study_day_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    activity_instance_id: Mapped[int | None] = mapped_column(BigInteger)
    what_changed: Mapped[str] = mapped_column(Text, nullable=False)
    why_changed: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_manifest: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    roadmap_objective: Mapped[str] = mapped_column(Text, nullable=False)
    coverage_impact: Mapped[str] = mapped_column(Text, nullable=False)
    affects_required_coverage: Mapped[bool] = mapped_column(Boolean, nullable=False)
    time_impact: Mapped[str] = mapped_column(Text, nullable=False)
    planned_time_delta_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )


class DailyClose(Base):
    """Append-only daily close with evidence and at most two corrections."""

    __tablename__ = "daily_closes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "roadmap_version_id", "study_day_id"],
            ["study_days.owner_id", "study_days.roadmap_version_id", "study_days.id"],
            name="fk_daily_closes_owner_version_day_study_days",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("owner_id", "study_day_id", name="uq_daily_closes_owner_study_day"),
        CheckConstraint(
            "jsonb_typeof(evidence_manifest) = 'object' "
            "AND octet_length(evidence_manifest::text) <= 16384",
            name="evidence_manifest_object",
        ),
        CheckConstraint(
            "public.tamforge_validate_evidence_manifest_v1(evidence_manifest)",
            name="evidence_manifest_v1",
        ),
        CheckConstraint(
            "btrim(strongest_output) <> '' AND octet_length(strongest_output) <= 4096",
            name="strongest_output_bounded",
        ),
        CheckConstraint(
            "btrim(repeated_mistake) <> '' AND octet_length(repeated_mistake) <= 4096",
            name="repeated_mistake_bounded",
        ),
        CheckConstraint(
            "unfinished_classification IN ('none', 'required', 'useful', 'optional', 'superseded')",
            name="unfinished_classification_allowed",
        ),
        CheckConstraint(
            "(unfinished_classification = 'none' AND unfinished_requirement IS NULL) OR "
            "(unfinished_classification <> 'none' AND unfinished_requirement IS NOT NULL "
            "AND btrim(unfinished_requirement) <> '' "
            "AND octet_length(unfinished_requirement) <= 4096)",
            name="unfinished_requirement_coherent",
        ),
        CheckConstraint("correction_count BETWEEN 0 AND 2", name="correction_count_range"),
        Index("ix_daily_closes_owner_study", "owner_id", "roadmap_version_id", "study_day_id"),
        Index("ix_daily_closes_owner_closed", "owner_id", "closed_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    roadmap_version_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    study_day_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    evidence_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    evidence_manifest: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    strongest_output: Mapped[str] = mapped_column(Text, nullable=False)
    repeated_mistake: Mapped[str] = mapped_column(Text, nullable=False)
    unfinished_classification: Mapped[str] = mapped_column(Text, nullable=False)
    unfinished_requirement: Mapped[str | None] = mapped_column(Text)
    correction_count: Mapped[int] = mapped_column(Integer, nullable=False)
    closed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )


def _is_persisted_change(target: Base, value: object, old_value: object) -> bool:
    state = inspect(target)
    return (
        not isinstance(old_value, LoaderCallableStatus)
        and (state.persistent or state.detached)
        and value != old_value
    )


_STUDY_DAY_PROVENANCE_ATTRIBUTES = (
    "owner_id",
    "roadmap_version_id",
    "local_date",
    "planned_minutes",
    "day_type",
    "created_at",
)


def _reject_study_day_provenance_change(
    target: StudyDay,
    value: object,
    old_value: object,
    initiator: object,
) -> object:
    del initiator
    if _is_persisted_change(target, value, old_value):
        raise StudyDayWorkflowError("study day provenance is immutable")
    return value


for _attribute_name in _STUDY_DAY_PROVENANCE_ATTRIBUTES:
    event.listen(
        getattr(StudyDay, _attribute_name),
        "set",
        _reject_study_day_provenance_change,
        retval=True,
        active_history=True,
    )


def _validate_study_day_status_change(
    target: StudyDay,
    value: str,
    old_value: str | LoaderCallableStatus,
    initiator: object,
) -> str:
    del initiator
    if value not in STUDY_DAY_TRANSITIONS:
        raise StudyDayWorkflowError("invalid study day status")
    if _is_persisted_change(target, value, old_value):
        assert isinstance(old_value, str)
        if value not in STUDY_DAY_TRANSITIONS.get(old_value, frozenset()):
            raise StudyDayWorkflowError("invalid study day status transition")
    return value


event.listen(
    StudyDay.status,
    "set",
    _validate_study_day_status_change,
    retval=True,
    active_history=True,
)


def _reject_write_once_study_day_timestamp(
    target: StudyDay,
    value: datetime | None,
    old_value: datetime | None | LoaderCallableStatus,
    initiator: object,
) -> datetime | None:
    del initiator
    if _is_persisted_change(target, value, old_value) and old_value is not None:
        raise StudyDayWorkflowError("study day lifecycle timestamps are write-once")
    return value


for _attribute_name in ("started_at", "closed_at"):
    event.listen(
        getattr(StudyDay, _attribute_name),
        "set",
        _reject_write_once_study_day_timestamp,
        retval=True,
        active_history=True,
    )


def validate_study_day_workflow(
    mapper: Mapper[StudyDay] | None,
    connection: Connection | None,
    target: StudyDay,
) -> None:
    del mapper, connection
    state = inspect(target)
    if state.persistent or state.detached:
        status_history = state.attrs.status.history
        previous_status = status_history.deleted[0] if status_history.deleted else target.status
        has_changes = any(attribute.history.has_changes() for attribute in state.attrs)
        if has_changes and previous_status == target.status and target.status != "in_progress":
            raise StudyDayWorkflowError("same-status study day updates are limited to in_progress")
        focused_history = state.attrs.focused_minutes.history
        if focused_history.deleted and target.focused_minutes < focused_history.deleted[0]:
            raise StudyDayWorkflowError("focused minutes cannot decrease")
    if target.status == "planned" and (
        target.started_at is not None or target.closed_at is not None
    ):
        raise StudyDayWorkflowError("planned study day timestamps are incoherent")
    if target.status == "in_progress" and (
        target.started_at is None or target.closed_at is not None
    ):
        raise StudyDayWorkflowError("active study day timestamps are incoherent")
    if target.status in {"closed", "incomplete"} and (
        target.started_at is None or target.closed_at is None
    ):
        raise StudyDayWorkflowError("closed study day timestamps are incoherent")


event.listen(StudyDay, "before_insert", validate_study_day_workflow)
event.listen(StudyDay, "before_update", validate_study_day_workflow)


_ACTIVITY_PROVENANCE_ATTRIBUTES = (
    "owner_id",
    "study_day_id",
    "roadmap_version_id",
    "task_definition_id",
    "task_stable_id_snapshot",
    "task_mapping_version_snapshot",
    "task_objective_snapshot",
    "task_timebox_minutes_snapshot",
    "roadmap_version_key_snapshot",
    "attempt_kind",
    "assistance_mode",
    "timebox_minutes",
    "source_hidden",
    "replacement_version",
    "replaces_activity_id",
    "created_at",
)


def _reject_activity_provenance_change(
    target: ActivityInstance,
    value: object,
    old_value: object,
    initiator: object,
) -> object:
    del initiator
    if _is_persisted_change(target, value, old_value):
        raise ActivityWorkflowError("activity provenance is immutable")
    return value


for _attribute_name in _ACTIVITY_PROVENANCE_ATTRIBUTES:
    event.listen(
        getattr(ActivityInstance, _attribute_name),
        "set",
        _reject_activity_provenance_change,
        retval=True,
        active_history=True,
    )


def _reject_write_once_activity_timestamp(
    target: ActivityInstance,
    value: datetime | None,
    old_value: datetime | None | LoaderCallableStatus,
    initiator: object,
) -> datetime | None:
    del initiator
    if _is_persisted_change(target, value, old_value) and old_value is not None:
        raise ActivityWorkflowError("activity lifecycle timestamps are write-once")
    return value


for _attribute_name in ("started_at", "output_committed_at", "completed_at"):
    event.listen(
        getattr(ActivityInstance, _attribute_name),
        "set",
        _reject_write_once_activity_timestamp,
        retval=True,
        active_history=True,
    )


def _validate_activity_state_change(
    target: ActivityInstance,
    value: str,
    old_value: str | LoaderCallableStatus,
    initiator: object,
) -> str:
    del initiator
    if value not in ACTIVITY_STATES:
        raise ActivityWorkflowError("invalid activity state")
    if _is_persisted_change(target, value, old_value):
        assert isinstance(old_value, str)
        if value not in ACTIVITY_TRANSITIONS.get(old_value, frozenset()):
            raise ActivityWorkflowError("invalid activity state transition")
    return value


event.listen(
    ActivityInstance.state,
    "set",
    _validate_activity_state_change,
    retval=True,
    active_history=True,
)


def validate_activity_workflow(
    mapper: Mapper[ActivityInstance] | None,
    connection: Connection | None,
    target: ActivityInstance,
) -> None:
    del mapper, connection
    state = inspect(target)
    version_history = state.attrs.optimistic_version.history
    if state.persistent:
        if not version_history.has_changes() or not version_history.deleted:
            raise ActivityWorkflowError("optimistic version must increase by one")
        old_version = version_history.deleted[0]
        if target.optimistic_version != old_version + 1:
            raise ActivityWorkflowError("optimistic version must increase by one")
        classification_history = state.attrs.classification.history
        stronger_evidence_history = state.attrs.stronger_evidence_activity_id.history
        if classification_history.has_changes() or stronger_evidence_history.has_changes():
            status_history = state.attrs.state.history
            previous_state = status_history.deleted[0] if status_history.deleted else target.state
            if target.state != "incomplete" or previous_state not in {"active", "paused"}:
                raise ActivityWorkflowError(
                    "incomplete classification can change only when work becomes incomplete"
                )

    if (target.classification == "superseded") != (
        target.stronger_evidence_activity_id is not None
    ):
        raise ActivityWorkflowError("superseded work must link stronger evidence")
    if (
        target.stronger_evidence_activity_id is not None
        and target.stronger_evidence_activity_id == target.id
    ):
        raise ActivityWorkflowError("activity cannot supersede itself")

    if target.state == "ready" and any(
        value is not None
        for value in (target.started_at, target.output_committed_at, target.completed_at)
    ):
        raise ActivityWorkflowError("ready activity timestamps are incoherent")
    if target.state in {"active", "paused"} and (
        target.started_at is None
        or target.output_committed_at is not None
        or target.completed_at is not None
    ):
        raise ActivityWorkflowError("active activity timestamps are incoherent")
    if target.state == "incomplete" and (target.started_at is None or target.completed_at is None):
        raise ActivityWorkflowError("incomplete activity timestamps are incoherent")
    if target.state in {
        "output_committed",
        "self_review_complete",
        "ai_processing",
        "feedback_ready",
        "correction_due",
        "demonstrated",
        "needs_work",
    } and (target.started_at is None or target.output_committed_at is None):
        raise ActivityWorkflowError("committed activity timestamps are incoherent")


event.listen(ActivityInstance, "before_insert", validate_activity_workflow)
event.listen(ActivityInstance, "before_update", validate_activity_workflow)


def _validate_attempt_kind(
    target: Attempt,
    value: str,
    old_value: str | LoaderCallableStatus,
    initiator: object,
) -> str:
    del target, old_value, initiator
    if value not in SAVED_ATTEMPT_KINDS:
        raise AttemptWorkflowError("invalid attempt kind")
    return value


event.listen(Attempt.attempt_kind, "set", _validate_attempt_kind, retval=True)


def validate_attempt_workflow(
    mapper: Mapper[Attempt] | None,
    connection: Connection | None,
    target: Attempt,
) -> None:
    """Validate final A/B shape after all constructor assignments have run."""
    del mapper
    if target.attempt_kind not in SAVED_ATTEMPT_KINDS:
        raise AttemptWorkflowError("invalid attempt kind")
    if (target.attempt_kind == "attempt_b") != (target.parent_attempt_id is not None):
        raise AttemptWorkflowError("invalid Attempt A/B relation shape")
    if connection is None:
        return

    activity_table = ActivityInstance.__table__
    activity_kind = connection.execute(
        select(activity_table.c.attempt_kind)
        .where(
            activity_table.c.owner_id == target.owner_id,
            activity_table.c.id == target.activity_instance_id,
        )
        .with_for_update(read=True, key_share=True)
    ).scalar_one_or_none()
    if activity_kind != target.attempt_kind:
        raise AttemptWorkflowError("attempt kind must match child activity kind")

    if target.attempt_kind == "attempt_b":
        parent_attempt = Attempt.__table__.alias("parent_attempt")
        parent_activity = ActivityInstance.__table__.alias("parent_activity")
        parent = connection.execute(
            select(
                parent_attempt.c.attempt_kind,
                parent_activity.c.attempt_kind,
                parent_attempt.c.prompt,
            )
            .select_from(
                parent_attempt.join(
                    parent_activity,
                    and_(
                        parent_activity.c.owner_id == parent_attempt.c.owner_id,
                        parent_activity.c.id == parent_attempt.c.activity_instance_id,
                    ),
                )
            )
            .where(
                parent_attempt.c.owner_id == target.owner_id,
                parent_attempt.c.id == target.parent_attempt_id,
            )
            .with_for_update(
                of=(parent_attempt, parent_activity),
                read=True,
                key_share=True,
            )
        ).one_or_none()
        if parent is None:
            raise AttemptWorkflowError(
                "invalid Attempt A/B relation: parent must be an owner-scoped Attempt A"
            )
        parent_kind, parent_activity_kind, parent_prompt = parent
        if parent_kind != "attempt_a":
            raise AttemptWorkflowError(
                "invalid Attempt A/B relation: parent must be an owner-scoped Attempt A"
            )
        if parent_activity_kind != "attempt_a":
            raise AttemptWorkflowError("Attempt A parent activity kind must be attempt_a")
        if parent_prompt != target.prompt:
            raise AttemptWorkflowError("Attempt B must use the same prompt as Attempt A")


event.listen(Attempt, "before_insert", validate_attempt_workflow)
event.listen(Attempt, "before_update", validate_attempt_workflow)


_APPEND_ONLY_CLASSES: tuple[type[Base], ...] = (
    Attempt,
    Artifact,
    ActivityArtifactLink,
    SelfReview,
    AdaptiveChange,
    DailyClose,
)


def _reject_learning_evidence_attribute_change(
    target: Base,
    value: object,
    old_value: object,
    initiator: object,
) -> object:
    del initiator
    if _is_persisted_change(target, value, old_value):
        raise AppendOnlyLearningEvidenceError("learning evidence is immutable")
    return value


for _evidence_class in _APPEND_ONLY_CLASSES:
    for _mapped_attribute in inspect(_evidence_class).column_attrs:
        event.listen(
            getattr(_evidence_class, _mapped_attribute.key),
            "set",
            _reject_learning_evidence_attribute_change,
            retval=True,
            active_history=True,
        )


def reject_learning_evidence_update(
    mapper: Mapper[Base] | None,
    connection: Connection | None,
    target: Base,
) -> None:
    del mapper, connection, target
    raise AppendOnlyLearningEvidenceError("learning evidence is immutable")


def reject_learning_evidence_delete(
    mapper: Mapper[Base] | None,
    connection: Connection | None,
    target: Base,
) -> None:
    del mapper, connection, target
    raise AppendOnlyLearningEvidenceError("learning evidence is immutable")


for _evidence_class in _APPEND_ONLY_CLASSES:
    event.listen(_evidence_class, "before_update", reject_learning_evidence_update)
    event.listen(_evidence_class, "before_delete", reject_learning_evidence_delete)


_TIMER_PROVENANCE_ATTRIBUTES = (
    "owner_id",
    "activity_instance_id",
    "idempotency_key",
    "started_at",
)


def _reject_timer_provenance_change(
    target: ActivityTimerSession,
    value: object,
    old_value: object,
    initiator: object,
) -> object:
    del initiator
    if _is_persisted_change(target, value, old_value):
        raise TimerWorkflowError("timer provenance is immutable")
    return value


for _attribute_name in _TIMER_PROVENANCE_ATTRIBUTES:
    event.listen(
        getattr(ActivityTimerSession, _attribute_name),
        "set",
        _reject_timer_provenance_change,
        retval=True,
        active_history=True,
    )


def validate_timer_workflow(
    mapper: Mapper[ActivityTimerSession] | None,
    connection: Connection | None,
    target: ActivityTimerSession,
) -> None:
    del mapper
    state = inspect(target)
    if state.transient:
        return

    timer_snapshot = _load_timer_snapshot(connection, target)
    if timer_snapshot is None:
        raise TimerWorkflowError("persisted timer state is unavailable")
    (
        old_owner_id,
        old_activity_id,
        old_idempotency_key,
        old_started_at,
        old_last_heartbeat_at,
        old_paused_at,
        old_ended_at,
        old_counted_seconds,
        old_client_sequence,
    ) = timer_snapshot

    if old_ended_at is not None:
        raise TimerWorkflowError("ended timer is immutable")
    if (
        target.owner_id,
        target.activity_instance_id,
        target.idempotency_key,
        target.started_at,
    ) != (
        old_owner_id,
        old_activity_id,
        old_idempotency_key,
        old_started_at,
    ):
        raise TimerWorkflowError("timer provenance is immutable")
    if target.last_heartbeat_at < old_last_heartbeat_at:
        raise TimerWorkflowError("timer heartbeat cannot move backward")
    if target.counted_seconds < old_counted_seconds:
        raise TimerWorkflowError("counted seconds cannot decrease")
    if target.last_client_sequence < old_client_sequence:
        raise TimerWorkflowError("timer client sequence cannot decrease")
    if old_paused_at is not None and target.paused_at != old_paused_at:
        raise TimerWorkflowError("paused_at is write-once")


TimerSnapshot = tuple[
    int,
    int,
    str,
    datetime,
    datetime,
    datetime | None,
    datetime | None,
    int,
    int,
]


def _previous_timer_value(target: ActivityTimerSession, attribute_name: str) -> object:
    attribute = inspect(target).attrs[attribute_name]
    history = attribute.history
    if history.deleted:
        return history.deleted[0]
    if history.unchanged:
        return history.unchanged[0]
    return getattr(target, attribute_name)


def _load_timer_snapshot(
    connection: Connection | None,
    target: ActivityTimerSession,
) -> TimerSnapshot | None:
    if connection is not None:
        table = ActivityTimerSession.__table__
        row = connection.execute(
            select(
                table.c.owner_id,
                table.c.activity_instance_id,
                table.c.idempotency_key,
                table.c.started_at,
                table.c.last_heartbeat_at,
                table.c.paused_at,
                table.c.ended_at,
                table.c.counted_seconds,
                table.c.last_client_sequence,
            ).where(table.c.id == target.id)
        ).one_or_none()
        return None if row is None else cast(TimerSnapshot, tuple(row))

    return cast(
        TimerSnapshot,
        (
            _previous_timer_value(target, "owner_id"),
            _previous_timer_value(target, "activity_instance_id"),
            _previous_timer_value(target, "idempotency_key"),
            _previous_timer_value(target, "started_at"),
            _previous_timer_value(target, "last_heartbeat_at"),
            _previous_timer_value(target, "paused_at"),
            _previous_timer_value(target, "ended_at"),
            _previous_timer_value(target, "counted_seconds"),
            _previous_timer_value(target, "last_client_sequence"),
        ),
    )


event.listen(ActivityTimerSession, "before_update", validate_timer_workflow)


__all__ = [
    "ActivityArtifactLink",
    "ActivityInstance",
    "ActivityTimerSession",
    "AdaptiveChange",
    "AppendOnlyLearningEvidenceError",
    "Artifact",
    "Attempt",
    "AttemptWorkflowError",
    "DailyClose",
    "LearnerSetting",
    "SelfReview",
    "StudyDay",
    "StudyDayWorkflowError",
    "reject_learning_evidence_delete",
    "validate_attempt_workflow",
]

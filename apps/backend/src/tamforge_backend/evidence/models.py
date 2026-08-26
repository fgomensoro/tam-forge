"""Versioned scoring configuration and reproducible evidence-ledger models."""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

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
    Numeric,
    Text,
    UniqueConstraint,
    and_,
    event,
    func,
    inspect,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Mapped, Mapper, mapped_column
from sqlalchemy.orm.base import LoaderCallableStatus

from ..learning.models import ActivityInstance, Attempt
from ..models.base import Base, utc_now
from ..roadmaps.models import TaskDefinition


class AppendOnlyEvidenceError(ValueError):
    """Raised when versioned configuration or evidence history is mutated."""


class EvidenceContractError(ValueError):
    """Raised when an evidence row violates an application-boundary contract."""


EVIDENCE_MODES = frozenset(
    {
        "exposure_only",
        "guided_practice",
        "independent_practice",
        "timed_assessment",
        "mock_interview",
        "real_interview",
        "pipeline_only",
    }
)
QUALIFYING_MODES = frozenset(
    {"independent_practice", "timed_assessment", "mock_interview", "real_interview"}
)
ASSISTANCE_CODES = frozenset(
    {
        "no_ai",
        "ai_after_committed_attempt",
        "ai_interviewer_only",
        "ai_hints_during_attempt",
        "ai_co_created",
        "ai_generated",
    }
)
QUALIFYING_ASSISTANCE_CODES = frozenset(
    {"no_ai", "ai_after_committed_attempt", "ai_interviewer_only"}
)
EVALUATOR_KINDS = frozenset(
    {
        "self",
        "ai_rubric_reviewer",
        "peer",
        "human_coach",
        "explicit_interviewer_feedback",
    }
)
DIFFICULTY_CODES = frozenset({"introductory", "standard", "advanced"})
CONDITION_CODES = frozenset(
    {
        "always",
        "spoken_or_written_english",
        "explained_aloud_in_english",
        "reviewed_dynamic_impact",
    }
)
QUALIFICATION_REASON_CODES = frozenset(
    {
        "qualifies",
        "nonqualifying_mode",
        "assisted_during_attempt",
        "attempt_b",
        "missing_committed_attempt",
        "mapping_condition_not_met",
        "excluded_by_formula",
    }
)


class ConfigSeedVersion(Base):
    """Content-addressed immutable scoring-configuration release."""

    __tablename__ = "config_seed_versions"
    __table_args__ = (
        UniqueConstraint("owner_id", "id", name="uq_config_seed_versions_owner_id_id"),
        UniqueConstraint(
            "owner_id", "version_key", name="uq_config_seed_versions_owner_version_key"
        ),
        CheckConstraint(
            "version_key ~ '^[a-z0-9][a-z0-9._-]{0,63}$'",
            name="version_key_safe",
        ),
        CheckConstraint("schema_version > 0", name="schema_version_positive"),
        CheckConstraint("octet_length(content_hash) = 32", name="content_hash_length"),
        Index("ix_config_seed_versions_owner_id", "owner_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "owners.id", name="fk_config_seed_versions_owner_id_owners", ondelete="RESTRICT"
        ),
        nullable=False,
    )
    version_key: Mapped[str] = mapped_column(Text, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )


class Competency(Base):
    """A canonical skill and its targets in one immutable configuration release."""

    __tablename__ = "competencies"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "config_seed_version_id"],
            ["config_seed_versions.owner_id", "config_seed_versions.id"],
            name="fk_competencies_owner_config_config_seed_versions",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("owner_id", "id", name="uq_competencies_owner_id_id"),
        UniqueConstraint(
            "owner_id",
            "config_seed_version_id",
            "id",
            name="uq_competencies_owner_config_id_id",
        ),
        UniqueConstraint(
            "owner_id",
            "config_seed_version_id",
            "slug",
            name="uq_competencies_owner_config_slug",
        ),
        CheckConstraint("slug ~ '^[a-z][a-z0-9_]{0,63}$'", name="slug_safe"),
        CheckConstraint(
            "btrim(name) <> '' AND octet_length(name) <= 128", name="name_bounded"
        ),
        CheckConstraint(
            "baseline_level BETWEEN 0 AND 4 AND month_one_target BETWEEN 0 AND 4 "
            "AND final_target BETWEEN 0 AND 4",
            name="targets_bounded",
        ),
        Index("ix_competencies_owner_config", "owner_id", "config_seed_version_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    config_seed_version_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    baseline_level: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    month_one_target: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    final_target: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )


class ExerciseTypeVersion(Base):
    """Immutable exercise classification and evidence-mode mapping version."""

    __tablename__ = "exercise_type_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "config_seed_version_id"],
            ["config_seed_versions.owner_id", "config_seed_versions.id"],
            name="fk_exercise_type_versions_owner_config_config_seed_versions",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("owner_id", "id", name="uq_exercise_type_versions_owner_id_id"),
        UniqueConstraint(
            "owner_id",
            "config_seed_version_id",
            "id",
            name="uq_exercise_type_versions_owner_config_id_id",
        ),
        UniqueConstraint(
            "owner_id",
            "exercise_type",
            "mapping_version",
            name="uq_exercise_type_versions_owner_type_mapping",
        ),
        CheckConstraint(
            "exercise_type ~ '^[a-z][a-z0-9_]{0,63}$'", name="exercise_type_safe"
        ),
        CheckConstraint(
            "mapping_version ~ '^[a-z0-9][a-z0-9._-]{0,63}$'", name="mapping_version_safe"
        ),
        CheckConstraint(
            "evidence_mode IN ('exposure_only', 'guided_practice', 'independent_practice', "
            "'timed_assessment', 'mock_interview', 'real_interview', 'pipeline_only')",
            name="evidence_mode_allowed",
        ),
        CheckConstraint(
            "condition_code IN ('always', 'spoken_or_written_english', "
            "'explained_aloud_in_english', 'reviewed_dynamic_impact')",
            name="condition_code_allowed",
        ),
        CheckConstraint(
            "tamforge_validate_tags_v1(tags)",
            name="tags_valid",
        ),
        Index(
            "ix_exercise_type_versions_owner_config", "owner_id", "config_seed_version_id"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    config_seed_version_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    exercise_type: Mapped[str] = mapped_column(Text, nullable=False)
    mapping_version: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_mode: Mapped[str] = mapped_column(Text, nullable=False)
    condition_code: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )


class ExerciseSkillMapping(Base):
    """One explicit skill impact for an immutable exercise-type version."""

    __tablename__ = "exercise_skill_mappings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "config_seed_version_id"],
            ["config_seed_versions.owner_id", "config_seed_versions.id"],
            name="fk_exercise_skill_mappings_owner_config_config_seed_versions",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["owner_id", "config_seed_version_id", "exercise_type_version_id"],
            [
                "exercise_type_versions.owner_id",
                "exercise_type_versions.config_seed_version_id",
                "exercise_type_versions.id",
            ],
            name="fk_exercise_mapping_config_exercise_type",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["owner_id", "config_seed_version_id", "competency_id"],
            [
                "competencies.owner_id",
                "competencies.config_seed_version_id",
                "competencies.id",
            ],
            name="fk_exercise_skill_mappings_owner_config_competency_competencies",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "owner_id",
            "exercise_type_version_id",
            "competency_id",
            name="uq_exercise_skill_mappings_owner_exercise_competency",
        ),
        CheckConstraint("impact > 0 AND impact <= 1", name="impact_bounded"),
        CheckConstraint(
            "condition_code IN ('always', 'spoken_or_written_english', "
            "'explained_aloud_in_english', 'reviewed_dynamic_impact')",
            name="condition_code_allowed",
        ),
        Index(
            "ix_exercise_skill_mappings_owner_config_exercise",
            "owner_id",
            "config_seed_version_id",
            "exercise_type_version_id",
        ),
        Index(
            "ix_exercise_skill_mappings_owner_config_competency",
            "owner_id",
            "config_seed_version_id",
            "competency_id",
        ),
        Index(
            "ix_exercise_skill_mappings_owner_config",
            "owner_id",
            "config_seed_version_id",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    config_seed_version_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    exercise_type_version_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    competency_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    impact: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False)
    condition_code: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )


class RubricVersion(Base):
    """Immutable rubric contract metadata."""

    __tablename__ = "rubric_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "config_seed_version_id"],
            ["config_seed_versions.owner_id", "config_seed_versions.id"],
            name="fk_rubric_versions_owner_config_config_seed_versions",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("owner_id", "id", name="uq_rubric_versions_owner_id_id"),
        UniqueConstraint(
            "owner_id",
            "config_seed_version_id",
            "id",
            name="uq_rubric_versions_owner_config_id_id",
        ),
        UniqueConstraint(
            "owner_id",
            "rubric_key",
            "version_key",
            name="uq_rubric_versions_owner_key_version",
        ),
        CheckConstraint(
            "rubric_key ~ '^[a-z][a-z0-9._-]{0,63}$' "
            "AND version_key ~ '^[a-z0-9][a-z0-9._-]{0,63}$'",
            name="keys_safe",
        ),
        CheckConstraint(
            "btrim(name) <> '' AND octet_length(name) <= 128", name="name_bounded"
        ),
        CheckConstraint(
            "scope_code IN ('tam', 'english', 'portfolio', 'exercise')",
            name="scope_code_allowed",
        ),
        CheckConstraint(
            "scale_min >= 0 AND scale_max <= 20 AND scale_max > scale_min",
            name="scale_coherent",
        ),
        Index("ix_rubric_versions_owner_config", "owner_id", "config_seed_version_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    config_seed_version_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rubric_key: Mapped[str] = mapped_column(Text, nullable=False)
    version_key: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    scope_code: Mapped[str] = mapped_column(Text, nullable=False)
    scale_min: Mapped[Decimal] = mapped_column(Numeric(5, 3), nullable=False)
    scale_max: Mapped[Decimal] = mapped_column(Numeric(5, 3), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )


class RubricDimension(Base):
    """One immutable dimension within a rubric version."""

    __tablename__ = "rubric_dimensions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "config_seed_version_id", "rubric_version_id"],
            [
                "rubric_versions.owner_id",
                "rubric_versions.config_seed_version_id",
                "rubric_versions.id",
            ],
            name="fk_rubric_dimensions_owner_config_rubric_rubric_versions",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "owner_id",
            "config_seed_version_id",
            "rubric_version_id",
            "id",
            name="uq_rubric_dimensions_owner_config_rubric_id",
        ),
        UniqueConstraint(
            "owner_id",
            "rubric_version_id",
            "dimension_key",
            name="uq_rubric_dimensions_owner_rubric_key",
        ),
        CheckConstraint(
            "dimension_key ~ '^[a-z][a-z0-9_]{0,63}$'", name="dimension_key_safe"
        ),
        CheckConstraint(
            "btrim(name) <> '' AND octet_length(name) <= 128", name="name_bounded"
        ),
        CheckConstraint("weight > 0 AND weight <= 1", name="weight_positive"),
        CheckConstraint("max_score > 0 AND max_score <= 20", name="max_score_bounded"),
        CheckConstraint("ordinal >= 0", name="ordinal_nonnegative"),
        CheckConstraint(
            "availability_rule_code IN ('always', 'monologue_not_applicable', "
            "'requires_audio', 'requires_interaction')",
            name="availability_rule_allowed",
        ),
        Index(
            "ix_rubric_dimensions_owner_config_rubric",
            "owner_id",
            "config_seed_version_id",
            "rubric_version_id",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    config_seed_version_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rubric_version_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    dimension_key: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    weight: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False)
    max_score: Mapped[Decimal] = mapped_column(Numeric(5, 3), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    availability_rule_code: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )


class RubricEvaluation(Base):
    """Immutable evaluation header tied to exact activity, attempt, and rubric versions."""

    __tablename__ = "rubric_evaluations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "activity_instance_id"],
            ["activity_instances.owner_id", "activity_instances.id"],
            name="fk_rubric_evaluations_owner_activity_activity_instances",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["owner_id", "activity_instance_id", "attempt_id"],
            ["attempts.owner_id", "attempts.activity_instance_id", "attempts.id"],
            name="fk_rubric_evaluations_owner_activity_attempt_attempts",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["owner_id", "config_seed_version_id", "rubric_version_id"],
            [
                "rubric_versions.owner_id",
                "rubric_versions.config_seed_version_id",
                "rubric_versions.id",
            ],
            name="fk_rubric_evaluations_owner_config_rubric_rubric_versions",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "owner_id",
            "config_seed_version_id",
            "rubric_version_id",
            "id",
            name="uq_rubric_evaluations_owner_config_rubric_id",
        ),
        UniqueConstraint(
            "owner_id",
            "config_seed_version_id",
            "activity_instance_id",
            "attempt_id",
            "rubric_version_id",
            "id",
            name="uq_rubric_evaluations_owner_config_activity_attempt_rubric_id",
        ),
        CheckConstraint(
            "evaluator_kind IN ('self', 'ai_rubric_reviewer', 'peer', 'human_coach', "
            "'explicit_interviewer_feedback')",
            name="evaluator_kind_allowed",
        ),
        CheckConstraint(
            "evaluation_schema_version > 0", name="evaluation_schema_version_positive"
        ),
        CheckConstraint(
            "tamforge_validate_reference_manifest_v1(input_manifest)",
            name="input_manifest_valid",
        ),
        CheckConstraint("created_at >= evaluated_at", name="created_after_evaluation"),
        Index(
            "ix_rubric_evaluations_owner_activity", "owner_id", "activity_instance_id"
        ),
        Index(
            "ix_rubric_evaluations_owner_activity_attempt",
            "owner_id",
            "activity_instance_id",
            "attempt_id",
        ),
        Index(
            "ix_rubric_evaluations_owner_config_rubric",
            "owner_id",
            "config_seed_version_id",
            "rubric_version_id",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    config_seed_version_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    activity_instance_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    attempt_id: Mapped[int | None] = mapped_column(BigInteger)
    rubric_version_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    evaluator_kind: Mapped[str] = mapped_column(Text, nullable=False)
    evaluation_schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    input_manifest: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )


class RubricDimensionScore(Base):
    """Independent score or explicit unavailability for one rubric dimension."""

    __tablename__ = "rubric_dimension_scores"
    __table_args__ = (
        ForeignKeyConstraint(
            [
                "owner_id",
                "config_seed_version_id",
                "rubric_version_id",
                "rubric_evaluation_id",
            ],
            [
                "rubric_evaluations.owner_id",
                "rubric_evaluations.config_seed_version_id",
                "rubric_evaluations.rubric_version_id",
                "rubric_evaluations.id",
            ],
            name="fk_dimension_score_config_rubric_evaluation",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "owner_id",
                "config_seed_version_id",
                "rubric_version_id",
                "rubric_dimension_id",
            ],
            [
                "rubric_dimensions.owner_id",
                "rubric_dimensions.config_seed_version_id",
                "rubric_dimensions.rubric_version_id",
                "rubric_dimensions.id",
            ],
            name="fk_dimension_score_config_rubric_dimension",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "owner_id",
            "rubric_evaluation_id",
            "rubric_dimension_id",
            name="uq_rubric_dimension_scores_owner_evaluation_dimension",
        ),
        CheckConstraint(
            "availability IN ('scored', 'not_applicable', 'unavailable')",
            name="availability_allowed",
        ),
        CheckConstraint(
            "(availability = 'scored' AND score IS NOT NULL AND score BETWEEN 0 AND 20 "
            "AND weight_used IS NOT NULL AND weight_used > 0 AND weight_used <= 1) OR "
            "(availability <> 'scored' AND score IS NULL AND weight_used IS NULL)",
            name="availability_score_coherent",
        ),
        CheckConstraint(
            "weight_used IS NULL OR weight_used > 0 AND weight_used <= 1",
            name="weight_used_bounded",
        ),
        CheckConstraint(
            "tamforge_validate_reference_manifest_v1(evidence_manifest)",
            name="evidence_manifest_valid",
        ),
        Index(
            "ix_rubric_dimension_scores_owner_config_rubric_evaluation",
            "owner_id",
            "config_seed_version_id",
            "rubric_version_id",
            "rubric_evaluation_id",
        ),
        Index(
            "ix_rubric_dimension_scores_owner_config_rubric_dimension",
            "owner_id",
            "config_seed_version_id",
            "rubric_version_id",
            "rubric_dimension_id",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    config_seed_version_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rubric_evaluation_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rubric_version_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rubric_dimension_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    availability: Mapped[str] = mapped_column(Text, nullable=False)
    score: Mapped[Decimal | None] = mapped_column(Numeric(5, 3))
    weight_used: Mapped[Decimal | None] = mapped_column(Numeric(7, 6))
    evidence_manifest: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )


class SkillEvidenceEvent(Base):
    """One inspectable score event for exactly one competency."""

    __tablename__ = "skill_evidence_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "activity_instance_id"],
            ["activity_instances.owner_id", "activity_instances.id"],
            name="fk_skill_evidence_events_owner_activity_activity_instances",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["owner_id", "activity_instance_id", "attempt_id"],
            ["attempts.owner_id", "attempts.activity_instance_id", "attempts.id"],
            name="fk_skill_evidence_events_owner_activity_attempt_attempts",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "owner_id",
                "config_seed_version_id",
                "activity_instance_id",
                "attempt_id",
                "rubric_version_id",
                "rubric_evaluation_id",
            ],
            [
                "rubric_evaluations.owner_id",
                "rubric_evaluations.config_seed_version_id",
                "rubric_evaluations.activity_instance_id",
                "rubric_evaluations.attempt_id",
                "rubric_evaluations.rubric_version_id",
                "rubric_evaluations.id",
            ],
            name="fk_skill_event_config_activity_attempt_evaluation",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["owner_id", "config_seed_version_id", "exercise_type_version_id"],
            [
                "exercise_type_versions.owner_id",
                "exercise_type_versions.config_seed_version_id",
                "exercise_type_versions.id",
            ],
            name="fk_skill_event_config_exercise_type",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["owner_id", "config_seed_version_id", "competency_id"],
            [
                "competencies.owner_id",
                "competencies.config_seed_version_id",
                "competencies.id",
            ],
            name="fk_skill_evidence_events_owner_config_competency_competencies",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "owner_id",
            "rubric_evaluation_id",
            "competency_id",
            "formula_version",
            name="uq_skill_evidence_events_owner_evaluation_competency_formula",
        ),
        CheckConstraint(
            "formula_version ~ '^[a-z0-9][a-z0-9._-]{0,63}$'", name="formula_version_safe"
        ),
        CheckConstraint(
            "practice_mode IN ('exposure_only', 'guided_practice', 'independent_practice', "
            "'timed_assessment', 'mock_interview', 'real_interview', 'pipeline_only')",
            name="practice_mode_allowed",
        ),
        CheckConstraint(
            "assistance_code IN ('no_ai', 'ai_after_committed_attempt', "
            "'ai_interviewer_only', 'ai_hints_during_attempt', 'ai_co_created', "
            "'ai_generated')",
            name="assistance_code_allowed",
        ),
        CheckConstraint(
            "evaluator_kind IN ('self', 'ai_rubric_reviewer', 'peer', 'human_coach', "
            "'explicit_interviewer_feedback')",
            name="evaluator_kind_allowed",
        ),
        CheckConstraint(
            "difficulty_code IN ('introductory', 'standard', 'advanced')",
            name="difficulty_code_allowed",
        ),
        CheckConstraint(
            "tamforge_validate_score_manifest_v1(raw_dimension_scores)",
            name="raw_dimension_scores_valid",
        ),
        CheckConstraint(
            "raw_score_numerator >= 0 AND raw_score_denominator > 0 "
            "AND performance_score BETWEEN 0 AND 4 "
            "AND performance_score = round(raw_score_numerator / raw_score_denominator, 3)",
            name="raw_score_terms_coherent",
        ),
        CheckConstraint(
            "exercise_skill_impact > 0 AND exercise_skill_impact <= 1 "
            "AND practice_mode_factor BETWEEN 0 AND 1 "
            "AND ai_independence_factor BETWEEN 0 AND 1 "
            "AND evaluator_confidence_factor BETWEEN 0 AND 1 "
            "AND difficulty_factor > 0 AND difficulty_factor <= 1.5 "
            "AND effective_weight BETWEEN 0 AND 1.5",
            name="factor_ranges",
        ),
        CheckConstraint(
            "effective_weight = round(exercise_skill_impact * practice_mode_factor * "
            "ai_independence_factor * evaluator_confidence_factor * difficulty_factor, 6)",
            name="effective_weight_reproducible",
        ),
        CheckConstraint(
            "qualification_reason_code IN ('qualifies', 'nonqualifying_mode', "
            "'assisted_during_attempt', 'attempt_b', 'missing_committed_attempt', "
            "'mapping_condition_not_met', 'excluded_by_formula')",
            name="qualification_reason_allowed",
        ),
        CheckConstraint(
            "(qualifying_for_level AND qualification_reason_code = 'qualifies' "
            "AND attempt_id IS NOT NULL "
            "AND practice_mode IN ('independent_practice', 'timed_assessment', "
            "'mock_interview', 'real_interview') "
            "AND assistance_code IN ('no_ai', 'ai_after_committed_attempt', "
            "'ai_interviewer_only')) OR "
            "(NOT qualifying_for_level AND qualification_reason_code <> 'qualifies')",
            name="qualification_coherent",
        ),
        CheckConstraint(
            "tamforge_validate_explanation_v1(explanation)", name="explanation_valid"
        ),
        CheckConstraint("created_at >= occurred_at", name="created_after_occurrence"),
        Index(
            "ix_skill_evidence_events_owner_activity", "owner_id", "activity_instance_id"
        ),
        Index(
            "ix_skill_evidence_events_owner_activity_attempt",
            "owner_id",
            "activity_instance_id",
            "attempt_id",
        ),
        Index(
            "ix_skill_evidence_events_owner_config_rubric_evaluation",
            "owner_id",
            "config_seed_version_id",
            "rubric_version_id",
            "rubric_evaluation_id",
        ),
        Index(
            "ix_skill_events_owner_config_activity_attempt_rubric_evaluation",
            "owner_id",
            "config_seed_version_id",
            "activity_instance_id",
            "attempt_id",
            "rubric_version_id",
            "rubric_evaluation_id",
        ),
        Index(
            "ix_skill_evidence_events_owner_config_exercise",
            "owner_id",
            "config_seed_version_id",
            "exercise_type_version_id",
        ),
        Index(
            "ix_skill_evidence_events_owner_config_competency",
            "owner_id",
            "config_seed_version_id",
            "competency_id",
        ),
        Index(
            "ix_skill_evidence_events_owner_competency_occurred",
            "owner_id",
            "competency_id",
            "occurred_at",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    config_seed_version_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    activity_instance_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    attempt_id: Mapped[int | None] = mapped_column(BigInteger)
    rubric_evaluation_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rubric_version_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    exercise_type_version_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    competency_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    formula_version: Mapped[str] = mapped_column(Text, nullable=False)
    practice_mode: Mapped[str] = mapped_column(Text, nullable=False)
    assistance_code: Mapped[str] = mapped_column(Text, nullable=False)
    evaluator_kind: Mapped[str] = mapped_column(Text, nullable=False)
    difficulty_code: Mapped[str] = mapped_column(Text, nullable=False)
    raw_dimension_scores: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    raw_score_numerator: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    raw_score_denominator: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    performance_score: Mapped[Decimal] = mapped_column(Numeric(5, 3), nullable=False)
    exercise_skill_impact: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False)
    practice_mode_factor: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False)
    ai_independence_factor: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False)
    evaluator_confidence_factor: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False)
    difficulty_factor: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False)
    effective_weight: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    qualifying_for_level: Mapped[bool] = mapped_column(Boolean, nullable=False)
    qualification_reason_code: Mapped[str] = mapped_column(Text, nullable=False)
    explanation: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )


class SkillSnapshot(Base):
    """Append-only, reproducible point-in-time estimate for one competency."""

    __tablename__ = "skill_snapshots"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "config_seed_version_id", "competency_id"],
            [
                "competencies.owner_id",
                "competencies.config_seed_version_id",
                "competencies.id",
            ],
            name="fk_skill_snapshots_owner_config_competency_competencies",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "owner_id",
            "competency_id",
            "formula_version",
            "snapshot_date",
            "snapshot_sequence",
            name="uq_skill_snapshots_owner_competency_formula_date_sequence",
        ),
        CheckConstraint(
            "formula_version ~ '^[a-z0-9][a-z0-9._-]{0,63}$'", name="formula_version_safe"
        ),
        CheckConstraint("snapshot_sequence > 0", name="snapshot_sequence_positive"),
        CheckConstraint("estimated_level BETWEEN 0 AND 4", name="estimated_level_bounded"),
        CheckConstraint(
            "confidence_code IN ('low', 'medium', 'high')", name="confidence_code_allowed"
        ),
        CheckConstraint(
            "trend_code IN ('improving', 'stable', 'declining', 'insufficient_evidence')",
            name="trend_code_allowed",
        ),
        CheckConstraint(
            "recency_code IN ('fresh', 'aging', 'stale', 'no_qualifying_evidence')",
            name="recency_code_allowed",
        ),
        CheckConstraint(
            "baseline_target_gap BETWEEN -4 AND 4 "
            "AND month_one_target_gap BETWEEN -4 AND 4 "
            "AND final_target_gap BETWEEN -4 AND 4",
            name="target_gaps_bounded",
        ),
        CheckConstraint(
            "total_effective_weight >= 0 AND qualifying_event_count >= 0 "
            "AND exercise_type_count >= 0",
            name="basis_counts_nonnegative",
        ),
        CheckConstraint(
            "tamforge_validate_snapshot_manifest_v1(contributing_event_manifest)",
            name="contributing_event_manifest_valid",
        ),
        CheckConstraint(
            "tamforge_validate_basis_v1(confidence_basis)", name="confidence_basis_valid"
        ),
        CheckConstraint("tamforge_validate_basis_v1(trend_basis)", name="trend_basis_valid"),
        Index(
            "ix_skill_snapshots_owner_config_competency",
            "owner_id",
            "config_seed_version_id",
            "competency_id",
        ),
        Index(
            "ix_skill_snapshots_owner_competency_date",
            "owner_id",
            "competency_id",
            "snapshot_date",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    config_seed_version_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    competency_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    formula_version: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    snapshot_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_level: Mapped[Decimal] = mapped_column(Numeric(5, 3), nullable=False)
    confidence_code: Mapped[str] = mapped_column(Text, nullable=False)
    trend_code: Mapped[str] = mapped_column(Text, nullable=False)
    recency_code: Mapped[str] = mapped_column(Text, nullable=False)
    baseline_target_gap: Mapped[Decimal] = mapped_column(Numeric(5, 3), nullable=False)
    month_one_target_gap: Mapped[Decimal] = mapped_column(Numeric(5, 3), nullable=False)
    final_target_gap: Mapped[Decimal] = mapped_column(Numeric(5, 3), nullable=False)
    total_effective_weight: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    qualifying_event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    exercise_type_count: Mapped[int] = mapped_column(Integer, nullable=False)
    last_strong_evidence_date: Mapped[date | None] = mapped_column(Date)
    contributing_event_manifest: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    confidence_basis: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    trend_basis: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )


class PortfolioJudgmentScore(Base):
    """Immutable 0-20 Portfolio Judgment composite with seven raw components."""

    __tablename__ = "portfolio_judgment_scores"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "activity_instance_id", "attempt_id"],
            ["attempts.owner_id", "attempts.activity_instance_id", "attempts.id"],
            name="fk_portfolio_judgment_scores_owner_activity_attempt_attempts",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "owner_id",
                "config_seed_version_id",
                "activity_instance_id",
                "attempt_id",
                "rubric_version_id",
                "rubric_evaluation_id",
            ],
            [
                "rubric_evaluations.owner_id",
                "rubric_evaluations.config_seed_version_id",
                "rubric_evaluations.activity_instance_id",
                "rubric_evaluations.attempt_id",
                "rubric_evaluations.rubric_version_id",
                "rubric_evaluations.id",
            ],
            name="fk_portfolio_config_activity_attempt_evaluation",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "owner_id",
            "rubric_evaluation_id",
            "formula_version",
            name="uq_portfolio_judgment_scores_owner_evaluation_formula",
        ),
        CheckConstraint(
            "formula_version ~ '^[a-z0-9][a-z0-9._-]{0,63}$'", name="formula_version_safe"
        ),
        CheckConstraint(
            "impact_risk_assessment BETWEEN 0 AND 4 "
            "AND explicit_prioritization BETWEEN 0 AND 3 "
            "AND delegation_ownership BETWEEN 0 AND 3 "
            "AND communication_control BETWEEN 0 AND 3 "
            "AND proactive_work_protection BETWEEN 0 AND 2 "
            "AND evidence_based_reprioritization BETWEEN 0 AND 3 "
            "AND english_clarity BETWEEN 0 AND 2",
            name="components_bounded",
        ),
        CheckConstraint("total_score BETWEEN 0 AND 20", name="total_bounded"),
        CheckConstraint(
            "total_score = impact_risk_assessment + explicit_prioritization + "
            "delegation_ownership + communication_control + proactive_work_protection + "
            "evidence_based_reprioritization + english_clarity",
            name="total_reproducible",
        ),
        CheckConstraint("tamforge_validate_basis_v1(trend_basis)", name="trend_basis_valid"),
        CheckConstraint("created_at >= scored_at", name="created_after_score"),
        Index(
            "ix_portfolio_scores_owner_activity_attempt",
            "owner_id",
            "activity_instance_id",
            "attempt_id",
        ),
        Index(
            "ix_portfolio_scores_owner_config_rubric_evaluation",
            "owner_id",
            "config_seed_version_id",
            "rubric_version_id",
            "rubric_evaluation_id",
        ),
        Index(
            "ix_portfolio_owner_config_activity_attempt_rubric_evaluation",
            "owner_id",
            "config_seed_version_id",
            "activity_instance_id",
            "attempt_id",
            "rubric_version_id",
            "rubric_evaluation_id",
        ),
        Index("ix_portfolio_scores_owner_scored", "owner_id", "scored_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    config_seed_version_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    activity_instance_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    attempt_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rubric_evaluation_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rubric_version_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    formula_version: Mapped[str] = mapped_column(Text, nullable=False)
    impact_risk_assessment: Mapped[Decimal] = mapped_column(Numeric(5, 3), nullable=False)
    explicit_prioritization: Mapped[Decimal] = mapped_column(Numeric(5, 3), nullable=False)
    delegation_ownership: Mapped[Decimal] = mapped_column(Numeric(5, 3), nullable=False)
    communication_control: Mapped[Decimal] = mapped_column(Numeric(5, 3), nullable=False)
    proactive_work_protection: Mapped[Decimal] = mapped_column(Numeric(5, 3), nullable=False)
    evidence_based_reprioritization: Mapped[Decimal] = mapped_column(
        Numeric(5, 3), nullable=False
    )
    english_clarity: Mapped[Decimal] = mapped_column(Numeric(5, 3), nullable=False)
    total_score: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False)
    trend_basis: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    scored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )


_IMMUTABLE_CLASSES: tuple[type[Base], ...] = (
    ConfigSeedVersion,
    Competency,
    ExerciseTypeVersion,
    ExerciseSkillMapping,
    RubricVersion,
    RubricDimension,
    RubricEvaluation,
    RubricDimensionScore,
    SkillEvidenceEvent,
    SkillSnapshot,
    PortfolioJudgmentScore,
)


def _is_persisted_change(target: Base, value: object, old_value: object) -> bool:
    state = inspect(target)
    return (
        (state.persistent or state.detached)
        and old_value is not LoaderCallableStatus.NO_VALUE
        and value != old_value
    )


def _reject_evidence_attribute_change(
    target: Base,
    value: object,
    old_value: object,
    initiator: object,
) -> object:
    del initiator
    if _is_persisted_change(target, value, old_value):
        raise AppendOnlyEvidenceError("evidence and configuration history is immutable")
    return value


for _immutable_class in _IMMUTABLE_CLASSES:
    for _mapped_attribute in inspect(_immutable_class).column_attrs:
        event.listen(
            getattr(_immutable_class, _mapped_attribute.key),
            "set",
            _reject_evidence_attribute_change,
            retval=True,
            active_history=True,
        )


def reject_evidence_update(
    mapper: Mapper[Base] | None,
    connection: Connection | None,
    target: Base,
) -> None:
    del mapper, connection, target
    raise AppendOnlyEvidenceError("evidence and configuration history is immutable")


def reject_evidence_delete(
    mapper: Mapper[Base] | None,
    connection: Connection | None,
    target: Base,
) -> None:
    del mapper, connection, target
    raise AppendOnlyEvidenceError("evidence and configuration history is immutable")


for _immutable_class in _IMMUTABLE_CLASSES:
    event.listen(_immutable_class, "before_update", reject_evidence_update)
    event.listen(_immutable_class, "before_delete", reject_evidence_delete)


def _json_size(value: object) -> int:
    try:
        return len(json.dumps(value, separators=(",", ":"), sort_keys=True).encode())
    except (TypeError, ValueError) as error:
        raise EvidenceContractError("structured evidence must be JSON serializable") from error


def _is_positive_id(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _as_decimal(value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise EvidenceContractError("structured evidence numeric value is invalid")
    return Decimal(str(value))


def _validate_reference_manifest(value: object) -> bool:
    if not isinstance(value, dict) or set(value) - {
        "schema_version",
        "artifact_ids",
        "observation_ids",
    }:
        return False
    if value.get("schema_version") != 1:
        return False
    for key in ("artifact_ids", "observation_ids"):
        items = value.get(key, [])
        if not isinstance(items, list) or len(items) > 64 or not all(map(_is_positive_id, items)):
            return False
    return True


def _validate_score_manifest(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != {"schema_version", "scores"}:
        return False
    scores = value.get("scores")
    if (
        value.get("schema_version") != 1
        or not isinstance(scores, list)
        or not 1 <= len(scores) <= 64
    ):
        return False
    for score in scores:
        if not isinstance(score, dict) or set(score) != {
            "dimension_score_id",
            "score",
            "weight",
        }:
            return False
        if not _is_positive_id(score["dimension_score_id"]):
            return False
        try:
            score_value = _as_decimal(score["score"])
            weight_value = _as_decimal(score["weight"])
        except EvidenceContractError:
            return False
        if not Decimal("0") <= score_value <= Decimal("20"):
            return False
        if not Decimal("0") < weight_value <= Decimal("1"):
            return False
    return True


def _validate_explanation(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "summary_code",
        "dimension_score_ids",
        "discount_codes",
    }:
        return False
    ids = value.get("dimension_score_ids")
    discounts = value.get("discount_codes")
    return (
        value.get("schema_version") == 1
        and value.get("summary_code")
        in {
            "independent_scored_evidence",
            "preparation_evidence",
            "assessment_evidence",
            "mock_evidence",
            "real_interview_evidence",
            "excluded_evidence",
        }
        and isinstance(ids, list)
        and len(ids) <= 64
        and all(map(_is_positive_id, ids))
        and isinstance(discounts, list)
        and len(discounts) <= 16
        and all(
            item
            in {
                "same_day_repetition",
                "low_diversity",
                "outlier_cap",
                "mapping_condition_not_met",
            }
            for item in discounts
        )
    )


def _validate_snapshot_manifest(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != {"schema_version", "events"}:
        return False
    events = value.get("events")
    if value.get("schema_version") != 1 or not isinstance(events, list) or len(events) > 24:
        return False
    for item in events:
        if not isinstance(item, dict) or set(item) != {
            "event_id",
            "effective_weight",
            "inclusion_code",
        }:
            return False
        if not _is_positive_id(item["event_id"]):
            return False
        try:
            weight = _as_decimal(item["effective_weight"])
        except EvidenceContractError:
            return False
        if not Decimal("0") <= weight <= Decimal("1.5") or item["inclusion_code"] not in {
            "included",
            "discounted_same_day",
            "excluded_nonqualifying",
            "excluded_outside_window",
        }:
            return False
    return True


def _validate_basis(value: object) -> bool:
    if not isinstance(value, dict) or set(value) - {
        "schema_version",
        "basis_code",
        "event_ids",
    }:
        return False
    event_ids = value.get("event_ids", [])
    return (
        value.get("schema_version") == 1
        and value.get("basis_code")
        in {
            "low_weight",
            "medium_weight_diversity",
            "high_weight_diversity_recency",
            "too_few_events",
            "improving",
            "stable",
            "declining",
            "first_score",
            "no_qualifying_evidence",
        }
        and isinstance(event_ids, list)
        and len(event_ids) <= 24
        and all(map(_is_positive_id, event_ids))
        and len(event_ids) == len(set(event_ids))
    )


def _validate_qualification_reason(
    target: SkillEvidenceEvent,
    attempt_kind: str | None,
    mapping_condition_code: str,
) -> None:
    """Require one exact, reproducible explanation for evidence eligibility."""

    if target.attempt_id is None:
        expected_reason = "missing_committed_attempt"
    elif attempt_kind is None:
        raise EvidenceContractError("skill evidence attempt provenance is invalid")
    elif attempt_kind == "attempt_b":
        expected_reason = "attempt_b"
    elif target.practice_mode not in QUALIFYING_MODES:
        expected_reason = "nonqualifying_mode"
    elif target.assistance_code not in QUALIFYING_ASSISTANCE_CODES:
        expected_reason = "assisted_during_attempt"
    elif target.qualifying_for_level:
        expected_reason = "qualifies"
    elif (
        target.qualification_reason_code == "mapping_condition_not_met"
        and mapping_condition_code != "always"
    ):
        expected_reason = "mapping_condition_not_met"
    else:
        expected_reason = "excluded_by_formula"

    if (
        target.qualification_reason_code != expected_reason
        or target.qualifying_for_level != (expected_reason == "qualifies")
    ):
        raise EvidenceContractError("qualification reason does not match stored evidence")
    if (
        expected_reason == "qualifies"
        and target.practice_mode == "independent_practice"
        and attempt_kind != "attempt_a"
    ):
        raise EvidenceContractError(
            "qualifying independent practice requires committed Attempt A"
        )


def _validate_structured_payloads(
    mapper: Mapper[Base] | None,
    connection: Connection | None,
    target: Base,
) -> None:
    del mapper, connection
    validators: dict[tuple[type[Base], str], object] = {
        (ExerciseTypeVersion, "tags"): lambda value: isinstance(value, list)
        and len(value) <= 32
        and all(
            isinstance(item, str)
            and item
            in {
                "observability",
                "oauth_api_security",
                "webhooks",
                "idempotency",
                "retries_backoff",
                "payment_operations",
                "ledger_reconciliation",
                "customer_expectation_management",
                "qbr_health_review",
                "behavioral_interview",
                "launch_readiness",
                "data_quality",
                "portfolio_prioritization",
            }
            for item in value
        ),
        (RubricEvaluation, "input_manifest"): _validate_reference_manifest,
        (RubricDimensionScore, "evidence_manifest"): _validate_reference_manifest,
        (SkillEvidenceEvent, "raw_dimension_scores"): _validate_score_manifest,
        (SkillEvidenceEvent, "explanation"): _validate_explanation,
        (SkillSnapshot, "contributing_event_manifest"): _validate_snapshot_manifest,
        (SkillSnapshot, "confidence_basis"): _validate_basis,
        (SkillSnapshot, "trend_basis"): _validate_basis,
        (PortfolioJudgmentScore, "trend_basis"): _validate_basis,
    }
    for attribute in inspect(target).mapper.column_attrs:
        column = attribute.columns[0]
        if isinstance(column.type, JSONB):
            value = getattr(target, attribute.key)
            validator = validators.get((type(target), attribute.key))
            if (
                value is None
                or _json_size(value) > 65536
                or validator is None
                or not validator(value)  # type: ignore[operator]
            ):
                raise EvidenceContractError("structured evidence payload is invalid or too large")


def validate_skill_evidence_event(
    mapper: Mapper[SkillEvidenceEvent] | None,
    connection: Connection | None,
    target: SkillEvidenceEvent,
) -> None:
    del mapper
    _validate_structured_payloads(None, connection, target)
    if target.practice_mode not in EVIDENCE_MODES:
        raise EvidenceContractError("invalid evidence mode")
    if target.assistance_code not in ASSISTANCE_CODES:
        raise EvidenceContractError("invalid assistance code")
    if target.evaluator_kind not in EVALUATOR_KINDS:
        raise EvidenceContractError("invalid evaluator kind")
    if target.difficulty_code not in DIFFICULTY_CODES:
        raise EvidenceContractError("invalid difficulty code")
    if target.qualification_reason_code not in QUALIFICATION_REASON_CODES:
        raise EvidenceContractError("invalid qualification reason code")
    try:
        manifest_numerator = Decimal("0")
        manifest_denominator = Decimal("0")
        seen_dimension_score_ids: set[int] = set()
        for score_item in target.raw_dimension_scores["scores"]:
            dimension_score_id = int(score_item["dimension_score_id"])
            if dimension_score_id in seen_dimension_score_ids:
                raise EvidenceContractError("raw score terms must reference unique dimensions")
            seen_dimension_score_ids.add(dimension_score_id)
            score_value = _as_decimal(score_item["score"])
            weight_value = _as_decimal(score_item["weight"])
            manifest_numerator += score_value * weight_value
            manifest_denominator += weight_value
        expected_weight = (
            target.exercise_skill_impact
            * target.practice_mode_factor
            * target.ai_independence_factor
            * target.evaluator_confidence_factor
            * target.difficulty_factor
        ).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
        expected_performance = (target.raw_score_numerator / target.raw_score_denominator).quantize(
            Decimal("0.001"), rounding=ROUND_HALF_UP
        )
    except (ArithmeticError, AttributeError) as error:
        raise EvidenceContractError("numeric evidence factors are invalid") from error
    if (
        target.raw_score_numerator != manifest_numerator
        or target.raw_score_denominator != manifest_denominator
    ):
        raise EvidenceContractError("raw score terms are not reproducible")
    if target.effective_weight != expected_weight:
        raise EvidenceContractError("effective evidence weight is not reproducible")
    if target.performance_score != expected_performance:
        raise EvidenceContractError("performance score is not reproducible")

    mapping_condition_code = "always"
    if connection is not None:
        exercise = ExerciseTypeVersion.__table__
        mapping = ExerciseSkillMapping.__table__
        activity = ActivityInstance.__table__
        task = TaskDefinition.__table__
        lineage = connection.execute(
            select(
                exercise.c.evidence_mode,
                exercise.c.exercise_type,
                exercise.c.mapping_version,
                task.c.exercise_type,
                task.c.mapping_version,
                mapping.c.impact,
                mapping.c.condition_code,
            )
            .select_from(
                exercise.join(
                    mapping,
                    and_(
                        mapping.c.owner_id == exercise.c.owner_id,
                        mapping.c.config_seed_version_id == exercise.c.config_seed_version_id,
                        mapping.c.exercise_type_version_id == exercise.c.id,
                    ),
                )
                .join(activity, activity.c.owner_id == exercise.c.owner_id)
                .join(
                    task,
                    and_(
                        task.c.owner_id == activity.c.owner_id,
                        task.c.roadmap_version_id == activity.c.roadmap_version_id,
                        task.c.id == activity.c.task_definition_id,
                    ),
                )
            )
            .where(
                exercise.c.owner_id == target.owner_id,
                exercise.c.config_seed_version_id == target.config_seed_version_id,
                exercise.c.id == target.exercise_type_version_id,
                mapping.c.competency_id == target.competency_id,
                activity.c.id == target.activity_instance_id,
            )
        ).one_or_none()
        if lineage is None:
            raise EvidenceContractError("skill evidence exercise provenance is invalid")
        (
            configured_mode,
            configured_exercise_type,
            configured_mapping_version,
            task_exercise_type,
            task_mapping_version,
            configured_impact,
            mapping_condition_code,
        ) = lineage
        if target.practice_mode != configured_mode:
            raise EvidenceContractError("practice mode must match configured exercise mode")
        if (
            configured_exercise_type != task_exercise_type
            or configured_mapping_version != task_mapping_version
        ):
            raise EvidenceContractError("exercise version must match activity task mapping")
        if target.exercise_skill_impact != configured_impact:
            raise EvidenceContractError("evidence impact must match configured skill mapping")
        attempt_kind = (
            connection.execute(
                select(Attempt.__table__.c.attempt_kind).where(
                    Attempt.__table__.c.owner_id == target.owner_id,
                    Attempt.__table__.c.activity_instance_id == target.activity_instance_id,
                    Attempt.__table__.c.id == target.attempt_id,
                )
            ).scalar_one_or_none()
            if target.attempt_id is not None
            else None
        )
    else:
        attempt_kind = "attempt_a" if target.attempt_id is not None else None
    _validate_qualification_reason(target, attempt_kind, mapping_condition_code)


def validate_rubric_dimension_score(
    mapper: Mapper[RubricDimensionScore] | None,
    connection: Connection | None,
    target: RubricDimensionScore,
) -> None:
    del mapper
    _validate_structured_payloads(None, connection, target)
    if target.availability == "scored":
        if target.score is None or target.weight_used is None:
            raise EvidenceContractError("scored dimension requires score and weight")
    elif target.availability in {"not_applicable", "unavailable"}:
        if target.score is not None or target.weight_used is not None:
            raise EvidenceContractError("unavailable dimension cannot carry a score")
    else:
        raise EvidenceContractError("invalid dimension score availability")
    if connection is None:
        return
    maximum = connection.execute(
        select(RubricDimension.__table__.c.max_score).where(
            RubricDimension.__table__.c.owner_id == target.owner_id,
            RubricDimension.__table__.c.config_seed_version_id
            == target.config_seed_version_id,
            RubricDimension.__table__.c.rubric_version_id == target.rubric_version_id,
            RubricDimension.__table__.c.id == target.rubric_dimension_id,
        )
    ).scalar_one_or_none()
    if maximum is None:
        raise EvidenceContractError("rubric dimension provenance is invalid")
    if target.score is not None and target.score > maximum:
        raise EvidenceContractError("score exceeds rubric dimension maximum")


def validate_skill_snapshot(
    mapper: Mapper[SkillSnapshot] | None,
    connection: Connection | None,
    target: SkillSnapshot,
) -> None:
    del mapper
    _validate_structured_payloads(None, connection, target)
    manifest_ids = {
        int(item["event_id"]) for item in target.contributing_event_manifest["events"]
    }
    for basis in (target.confidence_basis, target.trend_basis):
        if not set(basis.get("event_ids", [])).issubset(manifest_ids):
            raise EvidenceContractError("snapshot basis event ids must be contributing events")

    confidence_codes = {
        "low": {"low_weight", "no_qualifying_evidence"},
        "medium": {"medium_weight_diversity"},
        "high": {"high_weight_diversity_recency"},
    }
    trend_codes = {
        "insufficient_evidence": {"too_few_events", "no_qualifying_evidence"},
        "improving": {"improving"},
        "stable": {"stable"},
        "declining": {"declining"},
    }
    if target.confidence_basis["basis_code"] not in confidence_codes.get(
        target.confidence_code, set()
    ):
        raise EvidenceContractError("confidence basis code does not match snapshot confidence")
    if target.trend_basis["basis_code"] not in trend_codes.get(target.trend_code, set()):
        raise EvidenceContractError("trend basis code does not match snapshot trend")
    if connection is None:
        return

    competency_targets = connection.execute(
        select(
            Competency.__table__.c.baseline_level,
            Competency.__table__.c.month_one_target,
            Competency.__table__.c.final_target,
        ).where(
            Competency.__table__.c.owner_id == target.owner_id,
            Competency.__table__.c.config_seed_version_id
            == target.config_seed_version_id,
            Competency.__table__.c.id == target.competency_id,
        )
    ).one_or_none()
    if competency_targets is None:
        raise EvidenceContractError("snapshot competency provenance is invalid")
    baseline, month_target, final_target = map(_as_decimal, competency_targets)

    reconstructed_weight = Decimal("0")
    reconstructed_weighted_sum = Decimal("0")
    reconstructed_event_count = 0
    exercise_type_ids: set[int] = set()
    for item in target.contributing_event_manifest["events"]:
        stored_event = connection.execute(
            select(
                SkillEvidenceEvent.__table__.c.effective_weight,
                SkillEvidenceEvent.__table__.c.performance_score,
                SkillEvidenceEvent.__table__.c.exercise_type_version_id,
                SkillEvidenceEvent.__table__.c.qualifying_for_level,
            ).where(
                SkillEvidenceEvent.__table__.c.owner_id == target.owner_id,
                SkillEvidenceEvent.__table__.c.config_seed_version_id
                == target.config_seed_version_id,
                SkillEvidenceEvent.__table__.c.competency_id == target.competency_id,
                SkillEvidenceEvent.__table__.c.formula_version == target.formula_version,
                SkillEvidenceEvent.__table__.c.id == item["event_id"],
            )
        ).one_or_none()
        if stored_event is None:
            raise EvidenceContractError("snapshot event provenance is invalid")
        (
            stored_weight_value,
            performance_value,
            exercise_type_id,
            stored_qualifying,
        ) = stored_event
        stored_weight = _as_decimal(stored_weight_value)
        performance_score = _as_decimal(performance_value)
        manifest_weight = _as_decimal(item["effective_weight"])
        inclusion_code = item["inclusion_code"]
        if inclusion_code == "included" and (
            not stored_qualifying or manifest_weight != stored_weight
        ):
            raise EvidenceContractError("included snapshot event weight is invalid")
        if inclusion_code == "discounted_same_day" and (
            not stored_qualifying
            or manifest_weight <= 0
            or manifest_weight > stored_weight
        ):
            raise EvidenceContractError("discounted snapshot event weight is invalid")
        if (
            inclusion_code in {"excluded_nonqualifying", "excluded_outside_window"}
            and manifest_weight != 0
        ):
            raise EvidenceContractError("excluded snapshot event weight must be zero")
        if inclusion_code in {"included", "discounted_same_day"}:
            reconstructed_weight += manifest_weight
            reconstructed_weighted_sum += performance_score * manifest_weight
            reconstructed_event_count += 1
            exercise_type_ids.add(int(exercise_type_id))

    expected_estimate = (
        (baseline * Decimal("2") + reconstructed_weighted_sum)
        / (Decimal("2") + reconstructed_weight)
    ).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    expected_weight = reconstructed_weight.quantize(
        Decimal("0.000001"), rounding=ROUND_HALF_UP
    )
    expected_gaps = (
        (baseline - expected_estimate).quantize(
            Decimal("0.001"), rounding=ROUND_HALF_UP
        ),
        (month_target - expected_estimate).quantize(
            Decimal("0.001"), rounding=ROUND_HALF_UP
        ),
        (final_target - expected_estimate).quantize(
            Decimal("0.001"), rounding=ROUND_HALF_UP
        ),
    )
    if (
        target.total_effective_weight != expected_weight
        or target.qualifying_event_count != reconstructed_event_count
        or target.exercise_type_count != len(exercise_type_ids)
        or target.estimated_level != expected_estimate
        or (
            target.baseline_target_gap,
            target.month_one_target_gap,
            target.final_target_gap,
        )
        != expected_gaps
    ):
        raise EvidenceContractError("snapshot estimate is not reproducible")


def validate_portfolio_judgment_score(
    mapper: Mapper[PortfolioJudgmentScore] | None,
    connection: Connection | None,
    target: PortfolioJudgmentScore,
) -> None:
    del mapper
    _validate_structured_payloads(None, connection, target)
    basis_code = target.trend_basis["basis_code"]
    event_ids = target.trend_basis.get("event_ids", [])
    if basis_code == "first_score":
        if event_ids:
            raise EvidenceContractError("first portfolio score cannot have trend history")
        return
    if basis_code not in {"improving", "stable", "declining"} or not event_ids:
        raise EvidenceContractError("portfolio trend requires prior score history")
    if connection is None:
        return
    matching_history = connection.execute(
        select(func.count())
        .select_from(PortfolioJudgmentScore.__table__)
        .where(
            PortfolioJudgmentScore.__table__.c.id.in_(event_ids),
            PortfolioJudgmentScore.__table__.c.owner_id == target.owner_id,
            PortfolioJudgmentScore.__table__.c.config_seed_version_id
            == target.config_seed_version_id,
            PortfolioJudgmentScore.__table__.c.formula_version == target.formula_version,
            PortfolioJudgmentScore.__table__.c.scored_at <= target.scored_at,
        )
    ).scalar_one()
    if matching_history != len(event_ids):
        raise EvidenceContractError("portfolio trend history provenance is invalid")


for _structured_class in (
    ExerciseTypeVersion,
    RubricEvaluation,
):
    event.listen(_structured_class, "before_insert", _validate_structured_payloads)

event.listen(RubricDimensionScore, "before_insert", validate_rubric_dimension_score)
event.listen(SkillEvidenceEvent, "before_insert", validate_skill_evidence_event)
event.listen(SkillSnapshot, "before_insert", validate_skill_snapshot)
event.listen(PortfolioJudgmentScore, "before_insert", validate_portfolio_judgment_score)

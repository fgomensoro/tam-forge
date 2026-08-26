"""Add versioned scoring configuration and immutable evidence history.

Revision ID: 20260825_0004_evidence_scoring
Revises: 20260825_0003_study_activities
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260825_0004_evidence_scoring"
down_revision: str | None = "20260825_0003_study_activities"
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


def _numeric(name: str, precision: int, scale: int) -> sa.Column[object]:
    return sa.Column(name, sa.Numeric(precision=precision, scale=scale), nullable=False)


def _create_validation_functions() -> None:
    op.execute(
        """
        CREATE FUNCTION public.tamforge_validate_tags_v1(payload jsonb)
        RETURNS boolean
        LANGUAGE plpgsql
        IMMUTABLE
        PARALLEL SAFE
        SET search_path = pg_catalog
        AS $$
        DECLARE item jsonb;
        BEGIN
            IF payload IS NULL OR jsonb_typeof(payload) <> 'array'
                OR jsonb_array_length(payload) > 32
                OR octet_length(payload::text) > 4096 THEN
                RETURN false;
            END IF;
            FOR item IN SELECT value FROM jsonb_array_elements(payload) LOOP
                IF jsonb_typeof(item) <> 'string'
                    OR item #>> '{}' NOT IN (
                        'observability', 'oauth_api_security', 'webhooks',
                        'idempotency', 'retries_backoff', 'payment_operations',
                        'ledger_reconciliation', 'customer_expectation_management',
                        'qbr_health_review', 'behavioral_interview', 'launch_readiness',
                        'data_quality', 'portfolio_prioritization'
                    ) THEN
                    RETURN false;
                END IF;
            END LOOP;
            RETURN true;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION public.tamforge_validate_reference_manifest_v1(payload jsonb)
        RETURNS boolean
        LANGUAGE plpgsql
        IMMUTABLE
        PARALLEL SAFE
        SET search_path = pg_catalog
        AS $$
        DECLARE payload_key text;
        DECLARE array_key text;
        DECLARE item jsonb;
        BEGIN
            IF payload IS NULL OR jsonb_typeof(payload) <> 'object'
                OR octet_length(payload::text) > 16384
                OR NOT payload ? 'schema_version'
                OR jsonb_typeof(payload->'schema_version') <> 'number'
                OR payload->>'schema_version' <> '1' THEN
                RETURN false;
            END IF;
            FOR payload_key IN SELECT jsonb_object_keys(payload) LOOP
                IF payload_key <> ALL (ARRAY[
                    'schema_version', 'artifact_ids', 'observation_ids'
                ]) THEN
                    RETURN false;
                END IF;
            END LOOP;
            FOREACH array_key IN ARRAY ARRAY['artifact_ids', 'observation_ids'] LOOP
                IF payload ? array_key THEN
                    IF jsonb_typeof(payload->array_key) <> 'array'
                        OR jsonb_array_length(payload->array_key) > 64 THEN
                        RETURN false;
                    END IF;
                    FOR item IN SELECT value FROM jsonb_array_elements(payload->array_key) LOOP
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
    op.execute(
        """
        CREATE FUNCTION public.tamforge_validate_score_manifest_v1(payload jsonb)
        RETURNS boolean
        LANGUAGE plpgsql
        IMMUTABLE
        PARALLEL SAFE
        SET search_path = pg_catalog
        AS $$
        DECLARE payload_key text;
        DECLARE score_item jsonb;
        DECLARE item_key text;
        BEGIN
            IF payload IS NULL OR jsonb_typeof(payload) <> 'object'
                OR octet_length(payload::text) > 32768
                OR NOT payload ?& ARRAY['schema_version', 'scores']
                OR jsonb_typeof(payload->'schema_version') <> 'number'
                OR payload->>'schema_version' <> '1'
                OR jsonb_typeof(payload->'scores') <> 'array'
                OR jsonb_array_length(payload->'scores') NOT BETWEEN 1 AND 64 THEN
                RETURN false;
            END IF;
            FOR payload_key IN SELECT jsonb_object_keys(payload) LOOP
                IF payload_key <> ALL (ARRAY['schema_version', 'scores']) THEN
                    RETURN false;
                END IF;
            END LOOP;
            FOR score_item IN SELECT value FROM jsonb_array_elements(payload->'scores') LOOP
                IF jsonb_typeof(score_item) <> 'object'
                    OR NOT score_item ?& ARRAY['dimension_score_id', 'score', 'weight'] THEN
                    RETURN false;
                END IF;
                FOR item_key IN SELECT jsonb_object_keys(score_item) LOOP
                    IF item_key <> ALL (ARRAY['dimension_score_id', 'score', 'weight']) THEN
                        RETURN false;
                    END IF;
                END LOOP;
                IF jsonb_typeof(score_item->'dimension_score_id') <> 'number'
                    OR score_item->>'dimension_score_id' !~ '^[1-9][0-9]{0,18}$'
                    OR jsonb_typeof(score_item->'score') <> 'number'
                    OR (score_item->>'score')::numeric NOT BETWEEN 0 AND 20
                    OR jsonb_typeof(score_item->'weight') <> 'number'
                    OR (score_item->>'weight')::numeric <= 0
                    OR (score_item->>'weight')::numeric > 1 THEN
                    RETURN false;
                END IF;
            END LOOP;
            RETURN true;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION public.tamforge_validate_explanation_v1(payload jsonb)
        RETURNS boolean
        LANGUAGE plpgsql
        IMMUTABLE
        PARALLEL SAFE
        SET search_path = pg_catalog
        AS $$
        DECLARE payload_key text;
        DECLARE item jsonb;
        BEGIN
            IF payload IS NULL OR jsonb_typeof(payload) <> 'object'
                OR octet_length(payload::text) > 8192
                OR NOT payload ?& ARRAY[
                    'schema_version', 'summary_code', 'dimension_score_ids', 'discount_codes'
                ]
                OR jsonb_typeof(payload->'schema_version') <> 'number'
                OR jsonb_typeof(payload->'summary_code') <> 'string'
                OR payload->>'schema_version' <> '1'
                OR payload->>'summary_code' NOT IN (
                    'independent_scored_evidence', 'preparation_evidence',
                    'assessment_evidence', 'mock_evidence', 'real_interview_evidence',
                    'excluded_evidence'
                )
                OR jsonb_typeof(payload->'dimension_score_ids') <> 'array'
                OR jsonb_array_length(payload->'dimension_score_ids') > 64
                OR jsonb_typeof(payload->'discount_codes') <> 'array'
                OR jsonb_array_length(payload->'discount_codes') > 16 THEN
                RETURN false;
            END IF;
            FOR payload_key IN SELECT jsonb_object_keys(payload) LOOP
                IF payload_key <> ALL (ARRAY[
                    'schema_version', 'summary_code', 'dimension_score_ids', 'discount_codes'
                ]) THEN
                    RETURN false;
                END IF;
            END LOOP;
            FOR item IN SELECT value FROM jsonb_array_elements(payload->'dimension_score_ids') LOOP
                IF jsonb_typeof(item) <> 'number'
                    OR item::text !~ '^[1-9][0-9]{0,18}$' THEN
                    RETURN false;
                END IF;
            END LOOP;
            FOR item IN SELECT value FROM jsonb_array_elements(payload->'discount_codes') LOOP
                IF jsonb_typeof(item) <> 'string'
                    OR item #>> '{}' NOT IN (
                        'same_day_repetition', 'low_diversity', 'outlier_cap',
                        'mapping_condition_not_met'
                    ) THEN
                    RETURN false;
                END IF;
            END LOOP;
            RETURN true;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION public.tamforge_validate_snapshot_manifest_v1(payload jsonb)
        RETURNS boolean
        LANGUAGE plpgsql
        IMMUTABLE
        PARALLEL SAFE
        SET search_path = pg_catalog
        AS $$
        DECLARE payload_key text;
        DECLARE event_item jsonb;
        DECLARE item_key text;
        BEGIN
            IF payload IS NULL OR jsonb_typeof(payload) <> 'object'
                OR octet_length(payload::text) > 32768
                OR NOT payload ?& ARRAY['schema_version', 'events']
                OR jsonb_typeof(payload->'schema_version') <> 'number'
                OR payload->>'schema_version' <> '1'
                OR jsonb_typeof(payload->'events') <> 'array'
                OR jsonb_array_length(payload->'events') > 24 THEN
                RETURN false;
            END IF;
            FOR payload_key IN SELECT jsonb_object_keys(payload) LOOP
                IF payload_key <> ALL (ARRAY['schema_version', 'events']) THEN
                    RETURN false;
                END IF;
            END LOOP;
            FOR event_item IN SELECT value FROM jsonb_array_elements(payload->'events') LOOP
                IF jsonb_typeof(event_item) <> 'object'
                    OR NOT event_item ?& ARRAY['event_id', 'effective_weight', 'inclusion_code']
                    OR jsonb_typeof(event_item->'event_id') <> 'number'
                    OR event_item->>'event_id' !~ '^[1-9][0-9]{0,18}$'
                    OR jsonb_typeof(event_item->'effective_weight') <> 'number'
                    OR (event_item->>'effective_weight')::numeric NOT BETWEEN 0 AND 1.5
                    OR jsonb_typeof(event_item->'inclusion_code') <> 'string'
                    OR event_item->>'inclusion_code' NOT IN (
                        'included', 'discounted_same_day', 'excluded_nonqualifying',
                        'excluded_outside_window'
                    ) THEN
                    RETURN false;
                END IF;
                FOR item_key IN SELECT jsonb_object_keys(event_item) LOOP
                    IF item_key <> ALL (ARRAY[
                        'event_id', 'effective_weight', 'inclusion_code'
                    ]) THEN
                        RETURN false;
                    END IF;
                END LOOP;
            END LOOP;
            RETURN true;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION public.tamforge_validate_basis_v1(payload jsonb)
        RETURNS boolean
        LANGUAGE plpgsql
        IMMUTABLE
        PARALLEL SAFE
        SET search_path = pg_catalog
        AS $$
        DECLARE payload_key text;
        DECLARE item jsonb;
        DECLARE seen_ids bigint[] := ARRAY[]::bigint[];
        BEGIN
            IF payload IS NULL OR jsonb_typeof(payload) <> 'object'
                OR octet_length(payload::text) > 8192
                OR NOT payload ?& ARRAY['schema_version', 'basis_code']
                OR jsonb_typeof(payload->'schema_version') <> 'number'
                OR jsonb_typeof(payload->'basis_code') <> 'string'
                OR payload->>'schema_version' <> '1'
                OR payload->>'basis_code' NOT IN (
                    'low_weight', 'medium_weight_diversity', 'high_weight_diversity_recency',
                    'too_few_events', 'improving', 'stable', 'declining',
                    'first_score', 'no_qualifying_evidence'
                ) THEN
                RETURN false;
            END IF;
            FOR payload_key IN SELECT jsonb_object_keys(payload) LOOP
                IF payload_key <> ALL (ARRAY['schema_version', 'basis_code', 'event_ids']) THEN
                    RETURN false;
                END IF;
            END LOOP;
            IF payload ? 'event_ids' THEN
                IF jsonb_typeof(payload->'event_ids') <> 'array'
                    OR jsonb_array_length(payload->'event_ids') > 24 THEN
                    RETURN false;
                END IF;
                FOR item IN SELECT value FROM jsonb_array_elements(payload->'event_ids') LOOP
                    IF jsonb_typeof(item) <> 'number'
                        OR item::text !~ '^[1-9][0-9]{0,18}$' THEN
                        RETURN false;
                    END IF;
                    IF item::text::bigint = ANY(seen_ids) THEN
                        RETURN false;
                    END IF;
                    seen_ids := array_append(seen_ids, item::text::bigint);
                END LOOP;
            END IF;
            RETURN true;
        END;
        $$
        """
    )


def upgrade() -> None:
    _create_validation_functions()

    op.create_table(
        "config_seed_versions",
        _id(),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("version_key", sa.Text(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.LargeBinary(length=32), nullable=False),
        _created(),
        sa.CheckConstraint(
            "version_key ~ '^[a-z0-9][a-z0-9._-]{0,63}$'", name="version_key_safe"
        ),
        sa.CheckConstraint("schema_version > 0", name="schema_version_positive"),
        sa.CheckConstraint("octet_length(content_hash) = 32", name="content_hash_length"),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name="fk_config_seed_versions_owner_id_owners",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_config_seed_versions"),
        sa.UniqueConstraint("owner_id", "id", name="uq_config_seed_versions_owner_id_id"),
        sa.UniqueConstraint(
            "owner_id", "version_key", name="uq_config_seed_versions_owner_version_key"
        ),
    )
    op.create_index(
        "ix_config_seed_versions_owner_id", "config_seed_versions", ["owner_id"]
    )

    op.create_table(
        "competencies",
        _id(),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("config_seed_version_id", sa.BigInteger(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        _numeric("baseline_level", 4, 3),
        _numeric("month_one_target", 4, 3),
        _numeric("final_target", 4, 3),
        _created(),
        sa.CheckConstraint("slug ~ '^[a-z][a-z0-9_]{0,63}$'", name="slug_safe"),
        sa.CheckConstraint(
            "btrim(name) <> '' AND octet_length(name) <= 128", name="name_bounded"
        ),
        sa.CheckConstraint(
            "baseline_level BETWEEN 0 AND 4 AND month_one_target BETWEEN 0 AND 4 "
            "AND final_target BETWEEN 0 AND 4",
            name="targets_bounded",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "config_seed_version_id"],
            ["config_seed_versions.owner_id", "config_seed_versions.id"],
            name="fk_competencies_owner_config_config_seed_versions",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_competencies"),
        sa.UniqueConstraint("owner_id", "id", name="uq_competencies_owner_id_id"),
        sa.UniqueConstraint(
            "owner_id",
            "config_seed_version_id",
            "id",
            name="uq_competencies_owner_config_id_id",
        ),
        sa.UniqueConstraint(
            "owner_id",
            "config_seed_version_id",
            "slug",
            name="uq_competencies_owner_config_slug",
        ),
    )
    op.create_index(
        "ix_competencies_owner_config", "competencies", ["owner_id", "config_seed_version_id"]
    )

    op.create_table(
        "exercise_type_versions",
        _id(),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("config_seed_version_id", sa.BigInteger(), nullable=False),
        sa.Column("exercise_type", sa.Text(), nullable=False),
        sa.Column("mapping_version", sa.Text(), nullable=False),
        sa.Column("evidence_mode", sa.Text(), nullable=False),
        sa.Column("condition_code", sa.Text(), nullable=False),
        _jsonb("tags"),
        _created(),
        sa.CheckConstraint(
            "exercise_type ~ '^[a-z][a-z0-9_]{0,63}$'", name="exercise_type_safe"
        ),
        sa.CheckConstraint(
            "mapping_version ~ '^[a-z0-9][a-z0-9._-]{0,63}$'", name="mapping_version_safe"
        ),
        sa.CheckConstraint(
            "evidence_mode IN ('exposure_only', 'guided_practice', 'independent_practice', "
            "'timed_assessment', 'mock_interview', 'real_interview', 'pipeline_only')",
            name="evidence_mode_allowed",
        ),
        sa.CheckConstraint(
            "condition_code IN ('always', 'spoken_or_written_english', "
            "'explained_aloud_in_english', 'reviewed_dynamic_impact')",
            name="condition_code_allowed",
        ),
        sa.CheckConstraint("tamforge_validate_tags_v1(tags)", name="tags_valid"),
        sa.ForeignKeyConstraint(
            ["owner_id", "config_seed_version_id"],
            ["config_seed_versions.owner_id", "config_seed_versions.id"],
            name="fk_exercise_type_versions_owner_config_config_seed_versions",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_exercise_type_versions"),
        sa.UniqueConstraint("owner_id", "id", name="uq_exercise_type_versions_owner_id_id"),
        sa.UniqueConstraint(
            "owner_id",
            "config_seed_version_id",
            "id",
            name="uq_exercise_type_versions_owner_config_id_id",
        ),
        sa.UniqueConstraint(
            "owner_id",
            "exercise_type",
            "mapping_version",
            name="uq_exercise_type_versions_owner_type_mapping",
        ),
    )
    op.create_index(
        "ix_exercise_type_versions_owner_config",
        "exercise_type_versions",
        ["owner_id", "config_seed_version_id"],
    )

    op.create_table(
        "exercise_skill_mappings",
        _id(),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("config_seed_version_id", sa.BigInteger(), nullable=False),
        sa.Column("exercise_type_version_id", sa.BigInteger(), nullable=False),
        sa.Column("competency_id", sa.BigInteger(), nullable=False),
        _numeric("impact", 7, 6),
        sa.Column("condition_code", sa.Text(), nullable=False),
        _created(),
        sa.CheckConstraint("impact > 0 AND impact <= 1", name="impact_bounded"),
        sa.CheckConstraint(
            "condition_code IN ('always', 'spoken_or_written_english', "
            "'explained_aloud_in_english', 'reviewed_dynamic_impact')",
            name="condition_code_allowed",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "config_seed_version_id"],
            ["config_seed_versions.owner_id", "config_seed_versions.id"],
            name="fk_exercise_skill_mappings_owner_config_config_seed_versions",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "config_seed_version_id", "exercise_type_version_id"],
            [
                "exercise_type_versions.owner_id",
                "exercise_type_versions.config_seed_version_id",
                "exercise_type_versions.id",
            ],
            name="fk_exercise_mapping_config_exercise_type",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "config_seed_version_id", "competency_id"],
            [
                "competencies.owner_id",
                "competencies.config_seed_version_id",
                "competencies.id",
            ],
            name="fk_exercise_skill_mappings_owner_config_competency_competencies",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_exercise_skill_mappings"),
        sa.UniqueConstraint(
            "owner_id",
            "exercise_type_version_id",
            "competency_id",
            name="uq_exercise_skill_mappings_owner_exercise_competency",
        ),
    )
    op.create_index(
        "ix_exercise_skill_mappings_owner_config_exercise",
        "exercise_skill_mappings",
        ["owner_id", "config_seed_version_id", "exercise_type_version_id"],
    )
    op.create_index(
        "ix_exercise_skill_mappings_owner_config_competency",
        "exercise_skill_mappings",
        ["owner_id", "config_seed_version_id", "competency_id"],
    )
    op.create_index(
        "ix_exercise_skill_mappings_owner_config",
        "exercise_skill_mappings",
        ["owner_id", "config_seed_version_id"],
    )

    op.create_table(
        "rubric_versions",
        _id(),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("config_seed_version_id", sa.BigInteger(), nullable=False),
        sa.Column("rubric_key", sa.Text(), nullable=False),
        sa.Column("version_key", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("scope_code", sa.Text(), nullable=False),
        _numeric("scale_min", 5, 3),
        _numeric("scale_max", 5, 3),
        _created(),
        sa.CheckConstraint(
            "rubric_key ~ '^[a-z][a-z0-9._-]{0,63}$' "
            "AND version_key ~ '^[a-z0-9][a-z0-9._-]{0,63}$'",
            name="keys_safe",
        ),
        sa.CheckConstraint(
            "btrim(name) <> '' AND octet_length(name) <= 128", name="name_bounded"
        ),
        sa.CheckConstraint(
            "scope_code IN ('tam', 'english', 'portfolio', 'exercise')",
            name="scope_code_allowed",
        ),
        sa.CheckConstraint(
            "scale_min >= 0 AND scale_max <= 20 AND scale_max > scale_min",
            name="scale_coherent",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "config_seed_version_id"],
            ["config_seed_versions.owner_id", "config_seed_versions.id"],
            name="fk_rubric_versions_owner_config_config_seed_versions",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_rubric_versions"),
        sa.UniqueConstraint("owner_id", "id", name="uq_rubric_versions_owner_id_id"),
        sa.UniqueConstraint(
            "owner_id",
            "config_seed_version_id",
            "id",
            name="uq_rubric_versions_owner_config_id_id",
        ),
        sa.UniqueConstraint(
            "owner_id",
            "rubric_key",
            "version_key",
            name="uq_rubric_versions_owner_key_version",
        ),
    )
    op.create_index(
        "ix_rubric_versions_owner_config",
        "rubric_versions",
        ["owner_id", "config_seed_version_id"],
    )

    op.create_table(
        "rubric_dimensions",
        _id(),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("config_seed_version_id", sa.BigInteger(), nullable=False),
        sa.Column("rubric_version_id", sa.BigInteger(), nullable=False),
        sa.Column("dimension_key", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        _numeric("weight", 7, 6),
        _numeric("max_score", 5, 3),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("availability_rule_code", sa.Text(), nullable=False),
        _created(),
        sa.CheckConstraint(
            "dimension_key ~ '^[a-z][a-z0-9_]{0,63}$'", name="dimension_key_safe"
        ),
        sa.CheckConstraint(
            "btrim(name) <> '' AND octet_length(name) <= 128", name="name_bounded"
        ),
        sa.CheckConstraint("weight > 0 AND weight <= 1", name="weight_positive"),
        sa.CheckConstraint("max_score > 0 AND max_score <= 20", name="max_score_bounded"),
        sa.CheckConstraint("ordinal >= 0", name="ordinal_nonnegative"),
        sa.CheckConstraint(
            "availability_rule_code IN ('always', 'monologue_not_applicable', "
            "'requires_audio', 'requires_interaction')",
            name="availability_rule_allowed",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "config_seed_version_id", "rubric_version_id"],
            [
                "rubric_versions.owner_id",
                "rubric_versions.config_seed_version_id",
                "rubric_versions.id",
            ],
            name="fk_rubric_dimensions_owner_config_rubric_rubric_versions",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_rubric_dimensions"),
        sa.UniqueConstraint(
            "owner_id",
            "config_seed_version_id",
            "rubric_version_id",
            "id",
            name="uq_rubric_dimensions_owner_config_rubric_id",
        ),
        sa.UniqueConstraint(
            "owner_id",
            "rubric_version_id",
            "dimension_key",
            name="uq_rubric_dimensions_owner_rubric_key",
        ),
    )
    op.create_index(
        "ix_rubric_dimensions_owner_config_rubric",
        "rubric_dimensions",
        ["owner_id", "config_seed_version_id", "rubric_version_id"],
    )

    op.create_table(
        "rubric_evaluations",
        _id(),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("config_seed_version_id", sa.BigInteger(), nullable=False),
        sa.Column("activity_instance_id", sa.BigInteger(), nullable=False),
        sa.Column("attempt_id", sa.BigInteger(), nullable=True),
        sa.Column("rubric_version_id", sa.BigInteger(), nullable=False),
        sa.Column("evaluator_kind", sa.Text(), nullable=False),
        sa.Column("evaluation_schema_version", sa.Integer(), nullable=False),
        _jsonb("input_manifest"),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        _created(),
        sa.CheckConstraint(
            "evaluator_kind IN ('self', 'ai_rubric_reviewer', 'peer', 'human_coach', "
            "'explicit_interviewer_feedback')",
            name="evaluator_kind_allowed",
        ),
        sa.CheckConstraint(
            "evaluation_schema_version > 0", name="evaluation_schema_version_positive"
        ),
        sa.CheckConstraint(
            "tamforge_validate_reference_manifest_v1(input_manifest)",
            name="input_manifest_valid",
        ),
        sa.CheckConstraint("created_at >= evaluated_at", name="created_after_evaluation"),
        sa.ForeignKeyConstraint(
            ["owner_id", "activity_instance_id"],
            ["activity_instances.owner_id", "activity_instances.id"],
            name="fk_rubric_evaluations_owner_activity_activity_instances",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "activity_instance_id", "attempt_id"],
            ["attempts.owner_id", "attempts.activity_instance_id", "attempts.id"],
            name="fk_rubric_evaluations_owner_activity_attempt_attempts",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "config_seed_version_id", "rubric_version_id"],
            [
                "rubric_versions.owner_id",
                "rubric_versions.config_seed_version_id",
                "rubric_versions.id",
            ],
            name="fk_rubric_evaluations_owner_config_rubric_rubric_versions",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_rubric_evaluations"),
        sa.UniqueConstraint(
            "owner_id",
            "config_seed_version_id",
            "rubric_version_id",
            "id",
            name="uq_rubric_evaluations_owner_config_rubric_id",
        ),
        sa.UniqueConstraint(
            "owner_id",
            "config_seed_version_id",
            "activity_instance_id",
            "attempt_id",
            "rubric_version_id",
            "id",
            name="uq_rubric_evaluations_owner_config_activity_attempt_rubric_id",
        ),
    )
    op.create_index(
        "ix_rubric_evaluations_owner_activity",
        "rubric_evaluations",
        ["owner_id", "activity_instance_id"],
    )
    op.create_index(
        "ix_rubric_evaluations_owner_activity_attempt",
        "rubric_evaluations",
        ["owner_id", "activity_instance_id", "attempt_id"],
    )
    op.create_index(
        "ix_rubric_evaluations_owner_config_rubric",
        "rubric_evaluations",
        ["owner_id", "config_seed_version_id", "rubric_version_id"],
    )

    op.create_table(
        "rubric_dimension_scores",
        _id(),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("config_seed_version_id", sa.BigInteger(), nullable=False),
        sa.Column("rubric_evaluation_id", sa.BigInteger(), nullable=False),
        sa.Column("rubric_version_id", sa.BigInteger(), nullable=False),
        sa.Column("rubric_dimension_id", sa.BigInteger(), nullable=False),
        sa.Column("availability", sa.Text(), nullable=False),
        sa.Column("score", sa.Numeric(precision=5, scale=3), nullable=True),
        sa.Column("weight_used", sa.Numeric(precision=7, scale=6), nullable=True),
        _jsonb("evidence_manifest"),
        _created(),
        sa.CheckConstraint(
            "availability IN ('scored', 'not_applicable', 'unavailable')",
            name="availability_allowed",
        ),
        sa.CheckConstraint(
            "(availability = 'scored' AND score IS NOT NULL AND score BETWEEN 0 AND 20 "
            "AND weight_used IS NOT NULL AND weight_used > 0 AND weight_used <= 1) OR "
            "(availability <> 'scored' AND score IS NULL AND weight_used IS NULL)",
            name="availability_score_coherent",
        ),
        sa.CheckConstraint(
            "weight_used IS NULL OR weight_used > 0 AND weight_used <= 1",
            name="weight_used_bounded",
        ),
        sa.CheckConstraint(
            "tamforge_validate_reference_manifest_v1(evidence_manifest)",
            name="evidence_manifest_valid",
        ),
        sa.ForeignKeyConstraint(
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
        sa.ForeignKeyConstraint(
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
        sa.PrimaryKeyConstraint("id", name="pk_rubric_dimension_scores"),
        sa.UniqueConstraint(
            "owner_id",
            "rubric_evaluation_id",
            "rubric_dimension_id",
            name="uq_rubric_dimension_scores_owner_evaluation_dimension",
        ),
    )
    op.create_index(
        "ix_rubric_dimension_scores_owner_config_rubric_evaluation",
        "rubric_dimension_scores",
        ["owner_id", "config_seed_version_id", "rubric_version_id", "rubric_evaluation_id"],
    )
    op.create_index(
        "ix_rubric_dimension_scores_owner_config_rubric_dimension",
        "rubric_dimension_scores",
        ["owner_id", "config_seed_version_id", "rubric_version_id", "rubric_dimension_id"],
    )

    op.create_table(
        "skill_evidence_events",
        _id(),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("config_seed_version_id", sa.BigInteger(), nullable=False),
        sa.Column("activity_instance_id", sa.BigInteger(), nullable=False),
        sa.Column("attempt_id", sa.BigInteger(), nullable=True),
        sa.Column("rubric_evaluation_id", sa.BigInteger(), nullable=False),
        sa.Column("rubric_version_id", sa.BigInteger(), nullable=False),
        sa.Column("exercise_type_version_id", sa.BigInteger(), nullable=False),
        sa.Column("competency_id", sa.BigInteger(), nullable=False),
        sa.Column("formula_version", sa.Text(), nullable=False),
        sa.Column("practice_mode", sa.Text(), nullable=False),
        sa.Column("assistance_code", sa.Text(), nullable=False),
        sa.Column("evaluator_kind", sa.Text(), nullable=False),
        sa.Column("difficulty_code", sa.Text(), nullable=False),
        _jsonb("raw_dimension_scores"),
        _numeric("raw_score_numerator", 12, 6),
        _numeric("raw_score_denominator", 12, 6),
        _numeric("performance_score", 5, 3),
        _numeric("exercise_skill_impact", 7, 6),
        _numeric("practice_mode_factor", 7, 6),
        _numeric("ai_independence_factor", 7, 6),
        _numeric("evaluator_confidence_factor", 7, 6),
        _numeric("difficulty_factor", 7, 6),
        _numeric("effective_weight", 8, 6),
        sa.Column("qualifying_for_level", sa.Boolean(), nullable=False),
        sa.Column("qualification_reason_code", sa.Text(), nullable=False),
        _jsonb("explanation"),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        _created(),
        sa.CheckConstraint(
            "formula_version ~ '^[a-z0-9][a-z0-9._-]{0,63}$'", name="formula_version_safe"
        ),
        sa.CheckConstraint(
            "practice_mode IN ('exposure_only', 'guided_practice', 'independent_practice', "
            "'timed_assessment', 'mock_interview', 'real_interview', 'pipeline_only')",
            name="practice_mode_allowed",
        ),
        sa.CheckConstraint(
            "assistance_code IN ('no_ai', 'ai_after_committed_attempt', "
            "'ai_interviewer_only', 'ai_hints_during_attempt', 'ai_co_created', "
            "'ai_generated')",
            name="assistance_code_allowed",
        ),
        sa.CheckConstraint(
            "evaluator_kind IN ('self', 'ai_rubric_reviewer', 'peer', 'human_coach', "
            "'explicit_interviewer_feedback')",
            name="evaluator_kind_allowed",
        ),
        sa.CheckConstraint(
            "difficulty_code IN ('introductory', 'standard', 'advanced')",
            name="difficulty_code_allowed",
        ),
        sa.CheckConstraint(
            "tamforge_validate_score_manifest_v1(raw_dimension_scores)",
            name="raw_dimension_scores_valid",
        ),
        sa.CheckConstraint(
            "raw_score_numerator >= 0 AND raw_score_denominator > 0 "
            "AND performance_score BETWEEN 0 AND 4 "
            "AND performance_score = round(raw_score_numerator / raw_score_denominator, 3)",
            name="raw_score_terms_coherent",
        ),
        sa.CheckConstraint(
            "exercise_skill_impact > 0 AND exercise_skill_impact <= 1 "
            "AND practice_mode_factor BETWEEN 0 AND 1 "
            "AND ai_independence_factor BETWEEN 0 AND 1 "
            "AND evaluator_confidence_factor BETWEEN 0 AND 1 "
            "AND difficulty_factor > 0 AND difficulty_factor <= 1.5 "
            "AND effective_weight BETWEEN 0 AND 1.5",
            name="factor_ranges",
        ),
        sa.CheckConstraint(
            "effective_weight = round(exercise_skill_impact * practice_mode_factor * "
            "ai_independence_factor * evaluator_confidence_factor * difficulty_factor, 6)",
            name="effective_weight_reproducible",
        ),
        sa.CheckConstraint(
            "qualification_reason_code IN ('qualifies', 'nonqualifying_mode', "
            "'assisted_during_attempt', 'attempt_b', 'missing_committed_attempt', "
            "'mapping_condition_not_met', 'excluded_by_formula')",
            name="qualification_reason_allowed",
        ),
        sa.CheckConstraint(
            "(qualifying_for_level AND qualification_reason_code = 'qualifies' "
            "AND attempt_id IS NOT NULL "
            "AND practice_mode IN ('independent_practice', 'timed_assessment', "
            "'mock_interview', 'real_interview') "
            "AND assistance_code IN ('no_ai', 'ai_after_committed_attempt', "
            "'ai_interviewer_only')) OR "
            "(NOT qualifying_for_level AND qualification_reason_code <> 'qualifies')",
            name="qualification_coherent",
        ),
        sa.CheckConstraint(
            "tamforge_validate_explanation_v1(explanation)", name="explanation_valid"
        ),
        sa.CheckConstraint("created_at >= occurred_at", name="created_after_occurrence"),
        sa.ForeignKeyConstraint(
            ["owner_id", "activity_instance_id"],
            ["activity_instances.owner_id", "activity_instances.id"],
            name="fk_skill_evidence_events_owner_activity_activity_instances",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "activity_instance_id", "attempt_id"],
            ["attempts.owner_id", "attempts.activity_instance_id", "attempts.id"],
            name="fk_skill_evidence_events_owner_activity_attempt_attempts",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
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
        sa.ForeignKeyConstraint(
            ["owner_id", "config_seed_version_id", "exercise_type_version_id"],
            [
                "exercise_type_versions.owner_id",
                "exercise_type_versions.config_seed_version_id",
                "exercise_type_versions.id",
            ],
            name="fk_skill_event_config_exercise_type",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "config_seed_version_id", "competency_id"],
            [
                "competencies.owner_id",
                "competencies.config_seed_version_id",
                "competencies.id",
            ],
            name="fk_skill_evidence_events_owner_config_competency_competencies",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_skill_evidence_events"),
        sa.UniqueConstraint(
            "owner_id",
            "rubric_evaluation_id",
            "competency_id",
            "formula_version",
            name="uq_skill_evidence_events_owner_evaluation_competency_formula",
        ),
    )
    op.create_index(
        "ix_skill_evidence_events_owner_activity",
        "skill_evidence_events",
        ["owner_id", "activity_instance_id"],
    )
    op.create_index(
        "ix_skill_evidence_events_owner_activity_attempt",
        "skill_evidence_events",
        ["owner_id", "activity_instance_id", "attempt_id"],
    )
    op.create_index(
        "ix_skill_evidence_events_owner_config_rubric_evaluation",
        "skill_evidence_events",
        ["owner_id", "config_seed_version_id", "rubric_version_id", "rubric_evaluation_id"],
    )
    op.create_index(
        "ix_skill_events_owner_config_activity_attempt_rubric_evaluation",
        "skill_evidence_events",
        [
            "owner_id",
            "config_seed_version_id",
            "activity_instance_id",
            "attempt_id",
            "rubric_version_id",
            "rubric_evaluation_id",
        ],
    )
    op.create_index(
        "ix_skill_evidence_events_owner_config_exercise",
        "skill_evidence_events",
        ["owner_id", "config_seed_version_id", "exercise_type_version_id"],
    )
    op.create_index(
        "ix_skill_evidence_events_owner_config_competency",
        "skill_evidence_events",
        ["owner_id", "config_seed_version_id", "competency_id"],
    )
    op.create_index(
        "ix_skill_evidence_events_owner_competency_occurred",
        "skill_evidence_events",
        ["owner_id", "competency_id", "occurred_at"],
    )

    op.create_table(
        "skill_snapshots",
        _id(),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("config_seed_version_id", sa.BigInteger(), nullable=False),
        sa.Column("competency_id", sa.BigInteger(), nullable=False),
        sa.Column("formula_version", sa.Text(), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("snapshot_sequence", sa.Integer(), nullable=False),
        _numeric("estimated_level", 5, 3),
        sa.Column("confidence_code", sa.Text(), nullable=False),
        sa.Column("trend_code", sa.Text(), nullable=False),
        sa.Column("recency_code", sa.Text(), nullable=False),
        _numeric("baseline_target_gap", 5, 3),
        _numeric("month_one_target_gap", 5, 3),
        _numeric("final_target_gap", 5, 3),
        _numeric("total_effective_weight", 12, 6),
        sa.Column("qualifying_event_count", sa.Integer(), nullable=False),
        sa.Column("exercise_type_count", sa.Integer(), nullable=False),
        sa.Column("last_strong_evidence_date", sa.Date(), nullable=True),
        _jsonb("contributing_event_manifest"),
        _jsonb("confidence_basis"),
        _jsonb("trend_basis"),
        _created(),
        sa.CheckConstraint(
            "formula_version ~ '^[a-z0-9][a-z0-9._-]{0,63}$'", name="formula_version_safe"
        ),
        sa.CheckConstraint("snapshot_sequence > 0", name="snapshot_sequence_positive"),
        sa.CheckConstraint("estimated_level BETWEEN 0 AND 4", name="estimated_level_bounded"),
        sa.CheckConstraint(
            "confidence_code IN ('low', 'medium', 'high')", name="confidence_code_allowed"
        ),
        sa.CheckConstraint(
            "trend_code IN ('improving', 'stable', 'declining', 'insufficient_evidence')",
            name="trend_code_allowed",
        ),
        sa.CheckConstraint(
            "recency_code IN ('fresh', 'aging', 'stale', 'no_qualifying_evidence')",
            name="recency_code_allowed",
        ),
        sa.CheckConstraint(
            "baseline_target_gap BETWEEN -4 AND 4 "
            "AND month_one_target_gap BETWEEN -4 AND 4 "
            "AND final_target_gap BETWEEN -4 AND 4",
            name="target_gaps_bounded",
        ),
        sa.CheckConstraint(
            "total_effective_weight >= 0 AND qualifying_event_count >= 0 "
            "AND exercise_type_count >= 0",
            name="basis_counts_nonnegative",
        ),
        sa.CheckConstraint(
            "tamforge_validate_snapshot_manifest_v1(contributing_event_manifest)",
            name="contributing_event_manifest_valid",
        ),
        sa.CheckConstraint(
            "tamforge_validate_basis_v1(confidence_basis)", name="confidence_basis_valid"
        ),
        sa.CheckConstraint("tamforge_validate_basis_v1(trend_basis)", name="trend_basis_valid"),
        sa.ForeignKeyConstraint(
            ["owner_id", "config_seed_version_id", "competency_id"],
            [
                "competencies.owner_id",
                "competencies.config_seed_version_id",
                "competencies.id",
            ],
            name="fk_skill_snapshots_owner_config_competency_competencies",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_skill_snapshots"),
        sa.UniqueConstraint(
            "owner_id",
            "competency_id",
            "formula_version",
            "snapshot_date",
            "snapshot_sequence",
            name="uq_skill_snapshots_owner_competency_formula_date_sequence",
        ),
    )
    op.create_index(
        "ix_skill_snapshots_owner_config_competency",
        "skill_snapshots",
        ["owner_id", "config_seed_version_id", "competency_id"],
    )
    op.create_index(
        "ix_skill_snapshots_owner_competency_date",
        "skill_snapshots",
        ["owner_id", "competency_id", "snapshot_date"],
    )

    op.create_table(
        "portfolio_judgment_scores",
        _id(),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("config_seed_version_id", sa.BigInteger(), nullable=False),
        sa.Column("activity_instance_id", sa.BigInteger(), nullable=False),
        sa.Column("attempt_id", sa.BigInteger(), nullable=False),
        sa.Column("rubric_evaluation_id", sa.BigInteger(), nullable=False),
        sa.Column("rubric_version_id", sa.BigInteger(), nullable=False),
        sa.Column("formula_version", sa.Text(), nullable=False),
        _numeric("impact_risk_assessment", 5, 3),
        _numeric("explicit_prioritization", 5, 3),
        _numeric("delegation_ownership", 5, 3),
        _numeric("communication_control", 5, 3),
        _numeric("proactive_work_protection", 5, 3),
        _numeric("evidence_based_reprioritization", 5, 3),
        _numeric("english_clarity", 5, 3),
        _numeric("total_score", 6, 3),
        _jsonb("trend_basis"),
        sa.Column("scored_at", sa.DateTime(timezone=True), nullable=False),
        _created(),
        sa.CheckConstraint(
            "formula_version ~ '^[a-z0-9][a-z0-9._-]{0,63}$'", name="formula_version_safe"
        ),
        sa.CheckConstraint(
            "impact_risk_assessment BETWEEN 0 AND 4 "
            "AND explicit_prioritization BETWEEN 0 AND 3 "
            "AND delegation_ownership BETWEEN 0 AND 3 "
            "AND communication_control BETWEEN 0 AND 3 "
            "AND proactive_work_protection BETWEEN 0 AND 2 "
            "AND evidence_based_reprioritization BETWEEN 0 AND 3 "
            "AND english_clarity BETWEEN 0 AND 2",
            name="components_bounded",
        ),
        sa.CheckConstraint("total_score BETWEEN 0 AND 20", name="total_bounded"),
        sa.CheckConstraint(
            "total_score = impact_risk_assessment + explicit_prioritization + "
            "delegation_ownership + communication_control + proactive_work_protection + "
            "evidence_based_reprioritization + english_clarity",
            name="total_reproducible",
        ),
        sa.CheckConstraint("tamforge_validate_basis_v1(trend_basis)", name="trend_basis_valid"),
        sa.CheckConstraint("created_at >= scored_at", name="created_after_score"),
        sa.ForeignKeyConstraint(
            ["owner_id", "activity_instance_id", "attempt_id"],
            ["attempts.owner_id", "attempts.activity_instance_id", "attempts.id"],
            name="fk_portfolio_judgment_scores_owner_activity_attempt_attempts",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
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
        sa.PrimaryKeyConstraint("id", name="pk_portfolio_judgment_scores"),
        sa.UniqueConstraint(
            "owner_id",
            "rubric_evaluation_id",
            "formula_version",
            name="uq_portfolio_judgment_scores_owner_evaluation_formula",
        ),
    )
    op.create_index(
        "ix_portfolio_scores_owner_activity_attempt",
        "portfolio_judgment_scores",
        ["owner_id", "activity_instance_id", "attempt_id"],
    )
    op.create_index(
        "ix_portfolio_scores_owner_config_rubric_evaluation",
        "portfolio_judgment_scores",
        ["owner_id", "config_seed_version_id", "rubric_version_id", "rubric_evaluation_id"],
    )
    op.create_index(
        "ix_portfolio_owner_config_activity_attempt_rubric_evaluation",
        "portfolio_judgment_scores",
        [
            "owner_id",
            "config_seed_version_id",
            "activity_instance_id",
            "attempt_id",
            "rubric_version_id",
            "rubric_evaluation_id",
        ],
    )
    op.create_index(
        "ix_portfolio_scores_owner_scored",
        "portfolio_judgment_scores",
        ["owner_id", "scored_at"],
    )

    op.execute(
        """
        CREATE FUNCTION public.tamforge_guard_dimension_score_insert()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        DECLARE configured_maximum numeric;
        BEGIN
            SELECT max_score INTO configured_maximum
            FROM public.rubric_dimensions
            WHERE owner_id = NEW.owner_id
                AND config_seed_version_id = NEW.config_seed_version_id
                AND rubric_version_id = NEW.rubric_version_id
                AND id = NEW.rubric_dimension_id;
            IF configured_maximum IS NULL THEN
                RAISE EXCEPTION 'rubric dimension provenance is invalid';
            END IF;
            IF NEW.availability = 'scored' AND NEW.score > configured_maximum THEN
                RAISE EXCEPTION 'score exceeds rubric dimension maximum';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_rubric_dimension_scores_guard_insert
        BEFORE INSERT ON rubric_dimension_scores
        FOR EACH ROW EXECUTE FUNCTION public.tamforge_guard_dimension_score_insert()
        """
    )

    op.execute(
        """
        CREATE FUNCTION public.tamforge_guard_skill_evidence_insert()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        DECLARE stored_attempt_kind text;
        DECLARE stored_mapping_impact numeric;
        DECLARE stored_mapping_condition text;
        DECLARE stored_evidence_mode text;
        DECLARE stored_exercise_type text;
        DECLARE stored_mapping_version text;
        DECLARE task_exercise_type text;
        DECLARE task_mapping_version text;
        DECLARE stored_evaluator_kind text;
        DECLARE score_item jsonb;
        DECLARE stored_dimension_score numeric;
        DECLARE stored_dimension_weight numeric;
        DECLARE stored_score_numerator numeric := 0;
        DECLARE stored_score_denominator numeric := 0;
        DECLARE seen_score_ids bigint[] := ARRAY[]::bigint[];
        DECLARE expected_qualification_reason text;
        BEGIN
            SELECT attempt_kind INTO stored_attempt_kind
            FROM public.attempts
            WHERE owner_id = NEW.owner_id
                AND activity_instance_id = NEW.activity_instance_id
                AND id = NEW.attempt_id;

            SELECT etv.evidence_mode, etv.exercise_type, etv.mapping_version,
                mapping.impact, mapping.condition_code,
                task.exercise_type, task.mapping_version
            INTO stored_evidence_mode, stored_exercise_type, stored_mapping_version,
                stored_mapping_impact, stored_mapping_condition,
                task_exercise_type, task_mapping_version
            FROM public.exercise_type_versions AS etv
            JOIN public.exercise_skill_mappings AS mapping
                ON mapping.owner_id = etv.owner_id
                AND mapping.config_seed_version_id = etv.config_seed_version_id
                AND mapping.exercise_type_version_id = etv.id
            JOIN public.activity_instances AS activity
                ON activity.owner_id = etv.owner_id
                AND activity.id = NEW.activity_instance_id
            JOIN public.task_definitions AS task
                ON task.owner_id = activity.owner_id
                AND task.roadmap_version_id = activity.roadmap_version_id
                AND task.id = activity.task_definition_id
            WHERE etv.owner_id = NEW.owner_id
                AND etv.config_seed_version_id = NEW.config_seed_version_id
                AND etv.id = NEW.exercise_type_version_id
                AND mapping.competency_id = NEW.competency_id;
            IF stored_mapping_impact IS NULL
                OR stored_mapping_impact IS DISTINCT FROM NEW.exercise_skill_impact THEN
                RAISE EXCEPTION 'skill evidence must use the immutable configured mapping';
            END IF;
            IF NEW.practice_mode IS DISTINCT FROM stored_evidence_mode THEN
                RAISE EXCEPTION 'practice mode must match configured exercise mode';
            END IF;
            IF stored_exercise_type IS DISTINCT FROM task_exercise_type
                OR stored_mapping_version IS DISTINCT FROM task_mapping_version THEN
                RAISE EXCEPTION 'exercise version must match activity task mapping';
            END IF;

            SELECT evaluator_kind INTO stored_evaluator_kind
            FROM public.rubric_evaluations
            WHERE owner_id = NEW.owner_id
                AND config_seed_version_id = NEW.config_seed_version_id
                AND activity_instance_id = NEW.activity_instance_id
                AND attempt_id IS NOT DISTINCT FROM NEW.attempt_id
                AND rubric_version_id = NEW.rubric_version_id
                AND id = NEW.rubric_evaluation_id;
            IF stored_evaluator_kind IS DISTINCT FROM NEW.evaluator_kind THEN
                RAISE EXCEPTION 'skill evidence evaluator must match its evaluation';
            END IF;

            FOR score_item IN
                SELECT value FROM jsonb_array_elements(NEW.raw_dimension_scores->'scores')
            LOOP
                IF (score_item->>'dimension_score_id')::bigint = ANY(seen_score_ids) THEN
                    RAISE EXCEPTION 'skill evidence dimension scores must be unique';
                END IF;
                seen_score_ids := array_append(
                    seen_score_ids,
                    (score_item->>'dimension_score_id')::bigint
                );
                SELECT score, weight_used
                INTO stored_dimension_score, stored_dimension_weight
                FROM public.rubric_dimension_scores
                WHERE owner_id = NEW.owner_id
                    AND config_seed_version_id = NEW.config_seed_version_id
                    AND rubric_version_id = NEW.rubric_version_id
                    AND rubric_evaluation_id = NEW.rubric_evaluation_id
                    AND id = (score_item->>'dimension_score_id')::bigint
                    AND availability = 'scored';
                IF stored_dimension_score IS NULL OR stored_dimension_weight IS NULL
                    OR stored_dimension_score IS DISTINCT FROM (score_item->>'score')::numeric
                    OR stored_dimension_weight IS DISTINCT FROM (score_item->>'weight')::numeric
                THEN
                    RAISE EXCEPTION 'skill evidence raw scores must match immutable dimensions';
                END IF;
                stored_score_numerator := stored_score_numerator
                    + stored_dimension_score * stored_dimension_weight;
                stored_score_denominator := stored_score_denominator + stored_dimension_weight;
            END LOOP;
            IF stored_score_numerator IS DISTINCT FROM NEW.raw_score_numerator
                OR stored_score_denominator IS DISTINCT FROM NEW.raw_score_denominator THEN
                RAISE EXCEPTION 'skill evidence score terms are not reproducible';
            END IF;

            IF NEW.attempt_id IS NULL THEN
                expected_qualification_reason := 'missing_committed_attempt';
            ELSIF stored_attempt_kind IS NULL THEN
                RAISE EXCEPTION 'skill evidence attempt provenance is invalid';
            ELSIF stored_attempt_kind = 'attempt_b' THEN
                expected_qualification_reason := 'attempt_b';
            ELSIF NEW.practice_mode NOT IN (
                'independent_practice', 'timed_assessment', 'mock_interview', 'real_interview'
            ) THEN
                expected_qualification_reason := 'nonqualifying_mode';
            ELSIF NEW.assistance_code NOT IN (
                'no_ai', 'ai_after_committed_attempt', 'ai_interviewer_only'
            ) THEN
                expected_qualification_reason := 'assisted_during_attempt';
            ELSIF NEW.qualifying_for_level THEN
                expected_qualification_reason := 'qualifies';
            ELSIF NEW.qualification_reason_code = 'mapping_condition_not_met'
                AND stored_mapping_condition <> 'always' THEN
                expected_qualification_reason := 'mapping_condition_not_met';
            ELSE
                expected_qualification_reason := 'excluded_by_formula';
            END IF;
            IF NEW.qualification_reason_code IS DISTINCT FROM expected_qualification_reason
                OR NEW.qualifying_for_level IS DISTINCT FROM (
                    expected_qualification_reason = 'qualifies'
                ) THEN
                RAISE EXCEPTION 'qualification reason does not match stored evidence';
            END IF;
            IF expected_qualification_reason = 'qualifies'
                AND NEW.practice_mode = 'independent_practice'
                AND stored_attempt_kind IS DISTINCT FROM 'attempt_a' THEN
                RAISE EXCEPTION 'qualifying independent practice requires Attempt A';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_skill_evidence_events_guard_insert
        BEFORE INSERT ON skill_evidence_events
        FOR EACH ROW EXECUTE FUNCTION public.tamforge_guard_skill_evidence_insert()
        """
    )
    op.execute(
        """
        CREATE FUNCTION public.tamforge_guard_skill_snapshot_insert()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        DECLARE event_item jsonb;
        DECLARE stored_event_weight numeric;
        DECLARE stored_performance_score numeric;
        DECLARE stored_exercise_type_id bigint;
        DECLARE stored_qualifying boolean;
        DECLARE stored_baseline numeric;
        DECLARE stored_month_target numeric;
        DECLARE stored_final_target numeric;
        DECLARE reconstructed_weight numeric := 0;
        DECLARE reconstructed_weighted_sum numeric := 0;
        DECLARE reconstructed_event_count integer := 0;
        DECLARE exercise_ids bigint[] := ARRAY[]::bigint[];
        DECLARE seen_event_ids bigint[] := ARRAY[]::bigint[];
        DECLARE inclusion_code text;
        DECLARE manifest_weight numeric;
        DECLARE expected_estimate numeric;
        DECLARE basis_event_id bigint;
        BEGIN
            SELECT baseline_level, month_one_target, final_target
            INTO stored_baseline, stored_month_target, stored_final_target
            FROM public.competencies
            WHERE owner_id = NEW.owner_id
                AND config_seed_version_id = NEW.config_seed_version_id
                AND id = NEW.competency_id;
            IF stored_baseline IS NULL THEN
                RAISE EXCEPTION 'snapshot competency configuration is missing';
            END IF;

            FOR event_item IN
                SELECT value FROM jsonb_array_elements(NEW.contributing_event_manifest->'events')
            LOOP
                IF (event_item->>'event_id')::bigint = ANY(seen_event_ids) THEN
                    RAISE EXCEPTION 'snapshot contributing events must be unique';
                END IF;
                seen_event_ids := array_append(
                    seen_event_ids,
                    (event_item->>'event_id')::bigint
                );
                SELECT effective_weight, performance_score, exercise_type_version_id,
                    qualifying_for_level
                INTO stored_event_weight, stored_performance_score, stored_exercise_type_id,
                    stored_qualifying
                FROM public.skill_evidence_events
                WHERE owner_id = NEW.owner_id
                    AND config_seed_version_id = NEW.config_seed_version_id
                    AND competency_id = NEW.competency_id
                    AND formula_version = NEW.formula_version
                    AND id = (event_item->>'event_id')::bigint;
                IF stored_event_weight IS NULL THEN
                    RAISE EXCEPTION 'snapshot event provenance is invalid';
                END IF;
                inclusion_code := event_item->>'inclusion_code';
                manifest_weight := (event_item->>'effective_weight')::numeric;
                IF inclusion_code = 'included'
                    AND (
                        NOT stored_qualifying
                        OR manifest_weight IS DISTINCT FROM stored_event_weight
                    ) THEN
                    RAISE EXCEPTION 'included snapshot event weight is invalid';
                ELSIF inclusion_code = 'discounted_same_day'
                    AND (
                        NOT stored_qualifying
                        OR manifest_weight <= 0
                        OR manifest_weight > stored_event_weight
                    ) THEN
                    RAISE EXCEPTION 'discounted snapshot event weight is invalid';
                ELSIF inclusion_code IN (
                    'excluded_nonqualifying', 'excluded_outside_window'
                ) AND manifest_weight <> 0 THEN
                    RAISE EXCEPTION 'excluded snapshot event weight must be zero';
                END IF;
                IF inclusion_code IN ('included', 'discounted_same_day') THEN
                    reconstructed_weight := reconstructed_weight + manifest_weight;
                    reconstructed_weighted_sum := reconstructed_weighted_sum
                        + stored_performance_score * manifest_weight;
                    reconstructed_event_count := reconstructed_event_count + 1;
                    IF NOT stored_exercise_type_id = ANY(exercise_ids) THEN
                        exercise_ids := array_append(exercise_ids, stored_exercise_type_id);
                    END IF;
                END IF;
            END LOOP;

            FOR basis_event_id IN
                SELECT value::text::bigint
                FROM jsonb_array_elements(
                    COALESCE(NEW.confidence_basis->'event_ids', '[]'::jsonb)
                )
                UNION ALL
                SELECT value::text::bigint
                FROM jsonb_array_elements(
                    COALESCE(NEW.trend_basis->'event_ids', '[]'::jsonb)
                )
            LOOP
                IF NOT basis_event_id = ANY(seen_event_ids) THEN
                    RAISE EXCEPTION 'snapshot basis event ids must be contributing events';
                END IF;
            END LOOP;
            IF (NEW.confidence_code = 'low' AND NEW.confidence_basis->>'basis_code' NOT IN (
                    'low_weight', 'no_qualifying_evidence'
                ))
                OR (NEW.confidence_code = 'medium'
                    AND NEW.confidence_basis->>'basis_code' <> 'medium_weight_diversity')
                OR (NEW.confidence_code = 'high'
                    AND NEW.confidence_basis->>'basis_code'
                        <> 'high_weight_diversity_recency') THEN
                RAISE EXCEPTION 'snapshot confidence basis code is invalid';
            END IF;
            IF (NEW.trend_code = 'insufficient_evidence'
                    AND NEW.trend_basis->>'basis_code' NOT IN (
                        'too_few_events', 'no_qualifying_evidence'
                    ))
                OR (NEW.trend_code = 'improving'
                    AND NEW.trend_basis->>'basis_code' <> 'improving')
                OR (NEW.trend_code = 'stable'
                    AND NEW.trend_basis->>'basis_code' <> 'stable')
                OR (NEW.trend_code = 'declining'
                    AND NEW.trend_basis->>'basis_code' <> 'declining') THEN
                RAISE EXCEPTION 'snapshot trend basis code is invalid';
            END IF;

            expected_estimate := round(
                (stored_baseline * 2 + reconstructed_weighted_sum)
                / (2 + reconstructed_weight),
                3
            );
            IF NEW.total_effective_weight IS DISTINCT FROM round(reconstructed_weight, 6)
                OR NEW.qualifying_event_count IS DISTINCT FROM reconstructed_event_count
                OR NEW.exercise_type_count IS DISTINCT FROM cardinality(exercise_ids)
                OR NEW.estimated_level IS DISTINCT FROM expected_estimate
                OR NEW.baseline_target_gap IS DISTINCT FROM round(
                    stored_baseline - expected_estimate, 3
                )
                OR NEW.month_one_target_gap IS DISTINCT FROM round(
                    stored_month_target - expected_estimate, 3
                )
                OR NEW.final_target_gap IS DISTINCT FROM round(
                    stored_final_target - expected_estimate, 3
                ) THEN
                RAISE EXCEPTION 'snapshot estimate is not reproducible';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_skill_snapshots_guard_insert
        BEFORE INSERT ON skill_snapshots
        FOR EACH ROW EXECUTE FUNCTION public.tamforge_guard_skill_snapshot_insert()
        """
    )
    op.execute(
        """
        CREATE FUNCTION public.tamforge_guard_portfolio_score_insert()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        DECLARE basis_code text := NEW.trend_basis->>'basis_code';
        DECLARE basis_event_id bigint;
        DECLARE valid_history_count integer := 0;
        DECLARE requested_history_count integer := jsonb_array_length(
            COALESCE(NEW.trend_basis->'event_ids', '[]'::jsonb)
        );
        BEGIN
            IF basis_code = 'first_score' THEN
                IF requested_history_count <> 0 THEN
                    RAISE EXCEPTION 'first portfolio score cannot have trend history';
                END IF;
                RETURN NEW;
            END IF;
            IF basis_code NOT IN ('improving', 'stable', 'declining')
                OR requested_history_count = 0 THEN
                RAISE EXCEPTION 'portfolio trend requires prior score history';
            END IF;

            FOR basis_event_id IN
                SELECT value::text::bigint
                FROM jsonb_array_elements(NEW.trend_basis->'event_ids')
            LOOP
                IF EXISTS (
                    SELECT 1
                    FROM public.portfolio_judgment_scores AS prior
                    WHERE prior.id = basis_event_id
                        AND prior.owner_id = NEW.owner_id
                        AND prior.config_seed_version_id = NEW.config_seed_version_id
                        AND prior.formula_version = NEW.formula_version
                        AND prior.scored_at <= NEW.scored_at
                ) THEN
                    valid_history_count := valid_history_count + 1;
                END IF;
            END LOOP;
            IF valid_history_count <> requested_history_count THEN
                RAISE EXCEPTION 'portfolio trend history provenance is invalid';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_portfolio_judgment_scores_guard_insert
        BEFORE INSERT ON portfolio_judgment_scores
        FOR EACH ROW EXECUTE FUNCTION public.tamforge_guard_portfolio_score_insert()
        """
    )
    op.execute(
        """
        CREATE FUNCTION public.tamforge_reject_evidence_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            RAISE EXCEPTION 'evidence and configuration history is immutable';
        END;
        $$
        """
    )
    for table_name in (
        "config_seed_versions",
        "competencies",
        "exercise_type_versions",
        "exercise_skill_mappings",
        "rubric_versions",
        "rubric_dimensions",
        "rubric_evaluations",
        "rubric_dimension_scores",
        "skill_evidence_events",
        "skill_snapshots",
        "portfolio_judgment_scores",
    ):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table_name}_immutable
            BEFORE UPDATE OR DELETE OR TRUNCATE ON {table_name}
            FOR EACH STATEMENT
            EXECUTE FUNCTION public.tamforge_reject_evidence_mutation()
            """
        )


def downgrade() -> None:
    immutable_tables = (
        "portfolio_judgment_scores",
        "skill_snapshots",
        "skill_evidence_events",
        "rubric_dimension_scores",
        "rubric_evaluations",
        "rubric_dimensions",
        "rubric_versions",
        "exercise_skill_mappings",
        "exercise_type_versions",
        "competencies",
        "config_seed_versions",
    )
    for table_name in immutable_tables:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table_name}_immutable ON {table_name}")
    op.execute("DROP FUNCTION IF EXISTS public.tamforge_reject_evidence_mutation()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_portfolio_judgment_scores_guard_insert "
        "ON portfolio_judgment_scores"
    )
    op.execute("DROP FUNCTION IF EXISTS public.tamforge_guard_portfolio_score_insert()")
    op.execute("DROP TRIGGER IF EXISTS trg_skill_snapshots_guard_insert ON skill_snapshots")
    op.execute("DROP FUNCTION IF EXISTS public.tamforge_guard_skill_snapshot_insert()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_skill_evidence_events_guard_insert "
        "ON skill_evidence_events"
    )
    op.execute("DROP FUNCTION IF EXISTS public.tamforge_guard_skill_evidence_insert()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_rubric_dimension_scores_guard_insert "
        "ON rubric_dimension_scores"
    )
    op.execute("DROP FUNCTION IF EXISTS public.tamforge_guard_dimension_score_insert()")

    for table_name in immutable_tables:
        op.drop_table(table_name)

    for function_name in (
        "tamforge_validate_basis_v1",
        "tamforge_validate_snapshot_manifest_v1",
        "tamforge_validate_explanation_v1",
        "tamforge_validate_score_manifest_v1",
        "tamforge_validate_reference_manifest_v1",
        "tamforge_validate_tags_v1",
    ):
        op.execute(f"DROP FUNCTION IF EXISTS public.{function_name}(jsonb)")

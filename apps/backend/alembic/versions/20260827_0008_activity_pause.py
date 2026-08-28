"""Add paused activity state and monotonic heartbeat sequencing.

Revision ID: 20260827_0008_activity_pause
Revises: 20260826_0007_task_refs
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260827_0008_activity_pause"
down_revision: str | None = "20260826_0007_task_refs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_STRICT_ACTIVITY_GUARD = """
CREATE OR REPLACE FUNCTION public.tamforge_guard_activity_mutation()
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
        NEW.attempt_kind, NEW.assistance_mode, NEW.timebox_minutes,
        NEW.source_hidden, NEW.replacement_version,
        NEW.replaces_activity_id, NEW.created_at
    ) IS DISTINCT FROM ROW(
        OLD.owner_id, OLD.study_day_id, OLD.roadmap_version_id,
        OLD.task_definition_id, OLD.task_stable_id_snapshot,
        OLD.task_mapping_version_snapshot, OLD.task_objective_snapshot,
        OLD.task_timebox_minutes_snapshot, OLD.roadmap_version_key_snapshot,
        OLD.attempt_kind, OLD.assistance_mode, OLD.timebox_minutes,
        OLD.source_hidden, OLD.replacement_version,
        OLD.replaces_activity_id, OLD.created_at
    ) THEN
        RAISE EXCEPTION 'activity provenance is immutable';
    END IF;
    IF NEW.optimistic_version <> OLD.optimistic_version + 1 THEN
        RAISE EXCEPTION 'optimistic version must increase by one';
    END IF;
    IF (
        NEW.classification IS DISTINCT FROM OLD.classification
        OR NEW.stronger_evidence_activity_id
            IS DISTINCT FROM OLD.stronger_evidence_activity_id
    )
        AND NOT (OLD.state IN ('active', 'paused') AND NEW.state = 'incomplete') THEN
        RAISE EXCEPTION 'incomplete classification can change only for incomplete work';
    END IF;
    IF (NEW.classification = 'superseded')
        IS DISTINCT FROM (NEW.stronger_evidence_activity_id IS NOT NULL)
        OR NEW.stronger_evidence_activity_id = NEW.id THEN
        RAISE EXCEPTION 'superseded work must link different stronger evidence';
    END IF;
    IF NOT (
        (OLD.state = 'ready' AND NEW.state = 'active')
        OR (OLD.state = 'active'
            AND NEW.state IN ('paused', 'output_committed', 'incomplete'))
        OR (OLD.state = 'paused' AND NEW.state IN ('active', 'incomplete'))
        OR (OLD.state = 'output_committed' AND NEW.state = 'self_review_complete')
        OR (OLD.state = 'self_review_complete' AND NEW.state = 'ai_processing')
        OR (OLD.state = 'ai_processing' AND NEW.state = 'feedback_ready')
        OR (OLD.state = 'feedback_ready' AND NEW.state = 'correction_due')
        OR (OLD.state = 'correction_due'
            AND NEW.state IN ('demonstrated', 'needs_work'))
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
    IF NEW.state IN ('active', 'paused') AND (
        NEW.started_at IS NULL OR NEW.output_committed_at IS NOT NULL
        OR NEW.completed_at IS NOT NULL
    ) OR NEW.state = 'incomplete' AND (
        NEW.started_at IS NULL OR NEW.completed_at IS NULL
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

_STRICT_TIMER_GUARD = """
CREATE OR REPLACE FUNCTION public.tamforge_guard_timer_mutation()
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
        OR NEW.last_client_sequence < OLD.last_client_sequence
        OR NEW.last_heartbeat_at < OLD.last_heartbeat_at
        OR OLD.paused_at IS NOT NULL AND NEW.paused_at IS DISTINCT FROM OLD.paused_at THEN
        RAISE EXCEPTION 'timer progress must be monotonic';
    END IF;
    RETURN NEW;
END;
$$
"""

_LEGACY_ACTIVITY_GUARD = """
CREATE OR REPLACE FUNCTION public.tamforge_guard_activity_mutation()
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
        OR (OLD.state = 'correction_due'
            AND NEW.state IN ('demonstrated', 'needs_work'))
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

_LEGACY_TIMER_GUARD = """
CREATE OR REPLACE FUNCTION public.tamforge_guard_timer_mutation()
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


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_activity_instances_state_allowed"),
        "activity_instances",
        type_="check",
    )
    op.create_check_constraint(
        "state_allowed",
        "activity_instances",
        "state IN ('ready', 'active', 'paused', 'output_committed', "
        "'self_review_complete', 'ai_processing', 'feedback_ready', "
        "'correction_due', 'demonstrated', 'needs_work', 'incomplete', 'superseded')",
    )
    op.add_column(
        "activity_instances",
        sa.Column("stronger_evidence_activity_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_activity_instances_owner_stronger_activity",
        "activity_instances",
        "activity_instances",
        ["owner_id", "stronger_evidence_activity_id"],
        ["owner_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "stronger_evidence_classification_coherent",
        "activity_instances",
        "(classification = 'superseded') = (stronger_evidence_activity_id IS NOT NULL)",
    )
    op.create_check_constraint(
        "stronger_evidence_not_self",
        "activity_instances",
        "stronger_evidence_activity_id IS NULL OR stronger_evidence_activity_id <> id",
    )
    op.create_index(
        "ix_activity_instances_owner_stronger_evidence",
        "activity_instances",
        ["owner_id", "stronger_evidence_activity_id"],
    )
    op.add_column(
        "activity_timer_sessions",
        sa.Column(
            "last_client_sequence",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.create_check_constraint(
        "last_client_sequence_nonnegative",
        "activity_timer_sessions",
        "last_client_sequence >= 0",
    )
    op.execute(_STRICT_ACTIVITY_GUARD)
    op.execute(_STRICT_TIMER_GUARD)


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM public.activity_instances WHERE state = 'paused') THEN
                RAISE EXCEPTION 'cannot downgrade while paused activities exist';
            END IF;
            IF EXISTS (
                SELECT 1 FROM public.activity_instances
                WHERE stronger_evidence_activity_id IS NOT NULL
            ) THEN
                RAISE EXCEPTION 'cannot downgrade while stronger evidence links exist';
            END IF;
            IF EXISTS (
                SELECT 1 FROM public.activity_timer_sessions
                WHERE last_client_sequence <> 0
            ) THEN
                RAISE EXCEPTION 'cannot downgrade after sequenced timer progress exists';
            END IF;
        END;
        $$
        """
    )
    op.execute(_LEGACY_ACTIVITY_GUARD)
    op.execute(_LEGACY_TIMER_GUARD)
    op.drop_constraint(
        op.f("ck_activity_instances_stronger_evidence_not_self"),
        "activity_instances",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_activity_instances_stronger_evidence_classification_coherent"),
        "activity_instances",
        type_="check",
    )
    op.drop_constraint(
        "fk_activity_instances_owner_stronger_activity",
        "activity_instances",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_activity_instances_owner_stronger_evidence",
        table_name="activity_instances",
    )
    op.drop_column("activity_instances", "stronger_evidence_activity_id")
    op.drop_constraint(
        op.f("ck_activity_timer_sessions_last_client_sequence_nonnegative"),
        "activity_timer_sessions",
        type_="check",
    )
    op.drop_column("activity_timer_sessions", "last_client_sequence")
    op.drop_constraint(
        op.f("ck_activity_instances_state_allowed"),
        "activity_instances",
        type_="check",
    )
    op.create_check_constraint(
        "state_allowed",
        "activity_instances",
        "state IN ('ready', 'active', 'output_committed', 'self_review_complete', "
        "'ai_processing', 'feedback_ready', 'correction_due', 'demonstrated', "
        "'needs_work', 'incomplete', 'superseded')",
    )

"""Allow pre-commit source visibility and atomic attempt-kind selection.

Revision ID: 20260828_0009_output_commit
Revises: 20260827_0008_activity_pause
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260828_0009_output_commit"
down_revision: str | None = "20260827_0008_activity_pause"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_OUTPUT_ACTIVITY_GUARD = """
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
        NEW.assistance_mode, NEW.timebox_minutes, NEW.replacement_version,
        NEW.replaces_activity_id, NEW.created_at
    ) IS DISTINCT FROM ROW(
        OLD.owner_id, OLD.study_day_id, OLD.roadmap_version_id,
        OLD.task_definition_id, OLD.task_stable_id_snapshot,
        OLD.task_mapping_version_snapshot, OLD.task_objective_snapshot,
        OLD.task_timebox_minutes_snapshot, OLD.roadmap_version_key_snapshot,
        OLD.assistance_mode, OLD.timebox_minutes, OLD.replacement_version,
        OLD.replaces_activity_id, OLD.created_at
    ) THEN
        RAISE EXCEPTION 'activity provenance is immutable';
    END IF;
    IF NEW.optimistic_version <> OLD.optimistic_version + 1 THEN
        RAISE EXCEPTION 'optimistic version must increase by one';
    END IF;
    IF NEW.state = OLD.state THEN
        IF NEW.state NOT IN ('ready', 'active', 'paused')
            OR NEW.source_hidden IS NOT DISTINCT FROM OLD.source_hidden
            OR NEW.attempt_kind IS DISTINCT FROM OLD.attempt_kind
            OR NEW.classification IS DISTINCT FROM OLD.classification
            OR NEW.stronger_evidence_activity_id
                IS DISTINCT FROM OLD.stronger_evidence_activity_id
            OR NEW.started_at IS DISTINCT FROM OLD.started_at
            OR NEW.output_committed_at IS DISTINCT FROM OLD.output_committed_at
            OR NEW.completed_at IS DISTINCT FROM OLD.completed_at THEN
            RAISE EXCEPTION 'invalid source visibility mutation';
        END IF;
        RETURN NEW;
    END IF;
    IF NEW.source_hidden IS DISTINCT FROM OLD.source_hidden THEN
        RAISE EXCEPTION 'source visibility must change separately';
    END IF;
    IF (
        NEW.classification IS DISTINCT FROM OLD.classification
        OR NEW.stronger_evidence_activity_id
            IS DISTINCT FROM OLD.stronger_evidence_activity_id
    ) AND NOT (OLD.state IN ('active', 'paused') AND NEW.state = 'incomplete') THEN
        RAISE EXCEPTION 'incomplete classification can change only for incomplete work';
    END IF;
    IF (NEW.classification = 'superseded')
        IS DISTINCT FROM (NEW.stronger_evidence_activity_id IS NOT NULL)
        OR NEW.stronger_evidence_activity_id = NEW.id THEN
        RAISE EXCEPTION 'superseded work must link different stronger evidence';
    END IF;
    IF NEW.attempt_kind IS DISTINCT FROM OLD.attempt_kind AND NOT (
        OLD.attempt_kind = 'none'
        AND NEW.attempt_kind IN ('attempt_a', 'attempt_b')
        AND OLD.state = 'active'
        AND NEW.state = 'output_committed'
    ) THEN
        RAISE EXCEPTION 'attempt kind can change only during output commitment';
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
    ) AND NOT (OLD.state IN ('active', 'paused') AND NEW.state = 'incomplete') THEN
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


def upgrade() -> None:
    op.execute(_OUTPUT_ACTIVITY_GUARD)


def downgrade() -> None:
    op.execute(_STRICT_ACTIVITY_GUARD)

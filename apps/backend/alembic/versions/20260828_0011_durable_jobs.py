"""Add cancellable jobs and voluntary bounded RetryWait transitions.

Revision ID: 20260828_0011_durable_jobs
Revises: 20260828_0010_evidence_ledger
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260828_0011_durable_jobs"
down_revision: str | None = "20260828_0010_evidence_ledger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UP_GUARD = """
CREATE OR REPLACE FUNCTION public.tamforge_guard_background_job_mutation()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    IF OLD.state IN ('succeeded', 'failed', 'canceled') THEN
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
        (OLD.state = 'queued' AND NEW.state IN ('running', 'canceled')) OR
        (OLD.state = 'running'
            AND NEW.state IN ('queued', 'succeeded', 'failed', 'canceled'))
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
        AND (OLD.lease_expires_at IS NULL OR OLD.lease_expires_at > CURRENT_TIMESTAMP)
        AND NOT (
            NEW.last_error_category IN ('transient_dependency', 'resource_exhausted')
            AND NEW.last_error_details IS NOT NULL
            AND NEW.available_at >= NEW.updated_at
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


_DOWN_GUARD = """
CREATE OR REPLACE FUNCTION public.tamforge_guard_background_job_mutation()
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
        AND (OLD.lease_expires_at IS NULL OR OLD.lease_expires_at > CURRENT_TIMESTAMP) THEN
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


def upgrade() -> None:
    op.drop_constraint(
        "state_allowed", "background_jobs", type_="check"
    )
    op.drop_constraint(
        "lifecycle_coherent", "background_jobs", type_="check"
    )
    op.create_check_constraint(
        "state_allowed",
        "background_jobs",
        "state IN ('queued', 'running', 'succeeded', 'failed', 'canceled')",
    )
    op.create_check_constraint(
        "lifecycle_coherent",
        "background_jobs",
        "(state = 'queued' AND lease_owner IS NULL AND lease_expires_at IS NULL "
        "AND completed_at IS NULL) OR "
        "(state = 'running' AND attempt_count > 0 AND lease_owner IS NOT NULL "
        "AND lease_expires_at IS NOT NULL AND started_at IS NOT NULL "
        "AND completed_at IS NULL) OR "
        "(state IN ('succeeded', 'failed') AND attempt_count > 0 "
        "AND lease_owner IS NULL AND lease_expires_at IS NULL "
        "AND started_at IS NOT NULL AND completed_at IS NOT NULL) OR "
        "(state = 'canceled' AND lease_owner IS NULL "
        "AND lease_expires_at IS NULL AND completed_at IS NOT NULL)",
    )
    op.create_check_constraint(
        "cancellation_without_error",
        "background_jobs",
        "state <> 'canceled' OR last_error_category IS NULL",
    )
    op.execute(_UP_GUARD)


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM public.background_jobs WHERE state = 'canceled') THEN
                RAISE EXCEPTION 'cannot downgrade while canceled jobs exist';
            END IF;
        END;
        $$
        """
    )
    op.execute(_DOWN_GUARD)
    op.drop_constraint(
        "cancellation_without_error",
        "background_jobs",
        type_="check",
    )
    op.drop_constraint(
        "lifecycle_coherent", "background_jobs", type_="check"
    )
    op.drop_constraint(
        "state_allowed", "background_jobs", type_="check"
    )
    op.create_check_constraint(
        "state_allowed",
        "background_jobs",
        "state IN ('queued', 'running', 'succeeded', 'failed')",
    )
    op.create_check_constraint(
        "lifecycle_coherent",
        "background_jobs",
        "(state = 'queued' AND lease_owner IS NULL AND lease_expires_at IS NULL "
        "AND completed_at IS NULL) OR "
        "(state = 'running' AND attempt_count > 0 AND lease_owner IS NOT NULL "
        "AND lease_expires_at IS NOT NULL AND started_at IS NOT NULL "
        "AND completed_at IS NULL) OR "
        "(state IN ('succeeded', 'failed') AND attempt_count > 0 "
        "AND lease_owner IS NULL AND lease_expires_at IS NULL "
        "AND started_at IS NOT NULL AND completed_at IS NOT NULL)",
    )

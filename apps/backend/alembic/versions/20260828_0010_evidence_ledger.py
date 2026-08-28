"""Allow honest early-history portfolio trend snapshots.

Revision ID: 20260828_0010_evidence_ledger
Revises: 20260828_0009_output_commit
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260828_0010_evidence_ledger"
down_revision: str | None = "20260828_0009_output_commit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _portfolio_guard(allowed_basis_codes: str) -> str:
    return f"""
    CREATE OR REPLACE FUNCTION public.tamforge_guard_portfolio_score_insert()
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
        IF basis_code NOT IN ({allowed_basis_codes})
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


def upgrade() -> None:
    op.execute(
        _portfolio_guard("'too_few_events', 'improving', 'stable', 'declining'")
    )


def downgrade() -> None:
    op.execute(_portfolio_guard("'improving', 'stable', 'declining'"))

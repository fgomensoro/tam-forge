"""Append-only storage for analyses that passed the self-review release gate."""

from alembic import op

revision = "20260908_0016_publications"
down_revision = "20260905_0015_model_provenance"
branch_labels = None
depends_on = None

TABLE = r"""
CREATE TABLE analysis_publications (
    analysis_kind TEXT GENERATED ALWAYS AS (canonical_json::jsonb->'analysis'->>'analysis_kind')
        STORED NOT NULL,
    run_id BIGINT NOT NULL,
    id BIGINT GENERATED ALWAYS AS IDENTITY,
    owner_id BIGINT NOT NULL,
    canonical_json TEXT NOT NULL,
    content_hash BYTEA NOT NULL,
    hash_format INTEGER DEFAULT '1' NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_analysis_publications PRIMARY KEY (id),
    CONSTRAINT uq_analysis_publications_owner_id_id UNIQUE (owner_id, id),
    CONSTRAINT ck_analysis_publications_id_positive CHECK (id > 0),
    CONSTRAINT ck_analysis_publications_owner_positive CHECK (owner_id > 0),
    CONSTRAINT ck_analysis_publications_hash_format_v1 CHECK (hash_format = 1),
    CONSTRAINT ck_analysis_publications_content_bounded CHECK (octet_length(canonical_json)
        BETWEEN 1 AND 1048576),
    CONSTRAINT ck_analysis_publications_hash_matches CHECK (content_hash =
        public.digest(convert_to(canonical_json, 'UTF8'), 'sha256')),
    CONSTRAINT ck_analysis_publications_canonical_bytes CHECK (canonical_json =
        public.tamforge_provenance_canonical(canonical_json::jsonb)),
    CONSTRAINT ck_analysis_publications_analysis_kind_allowed CHECK (analysis_kind IN
        ('english_analysis', 'tam_analysis')),
    CONSTRAINT uq_analysis_publications_run_kind UNIQUE (run_id, analysis_kind),
    CONSTRAINT fk_analysis_publications_owner_id_model_runs FOREIGN KEY(owner_id, run_id)
        REFERENCES model_runs (owner_id, id),
    CONSTRAINT fk_analysis_publications_owner_id_owners FOREIGN KEY(owner_id) REFERENCES owners (id)
)
"""


def upgrade() -> None:
    op.execute(TABLE)
    op.execute(
        "CREATE TRIGGER trg_analysis_publications_immutable "
        "BEFORE UPDATE OR DELETE OR TRUNCATE ON public.analysis_publications "
        "FOR EACH STATEMENT EXECUTE FUNCTION public.tamforge_provenance_immutable()"
    )


def downgrade() -> None:
    op.drop_table("analysis_publications")

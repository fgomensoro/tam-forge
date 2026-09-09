"""The learner's own record that model improvement is off for a policy version."""

from alembic import op

revision = "20260909_0017_attestations"
down_revision = "20260908_0016_publications"
branch_labels = None
depends_on = None

TABLE = r"""
CREATE TABLE privacy_attestations (
    policy_version TEXT GENERATED ALWAYS AS (canonical_json::jsonb->>'policy_version')
        STORED NOT NULL,
    id BIGINT GENERATED ALWAYS AS IDENTITY,
    owner_id BIGINT NOT NULL,
    canonical_json TEXT NOT NULL,
    content_hash BYTEA NOT NULL,
    hash_format INTEGER DEFAULT '1' NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_privacy_attestations PRIMARY KEY (id),
    CONSTRAINT uq_privacy_attestations_owner_id_id UNIQUE (owner_id, id),
    CONSTRAINT ck_privacy_attestations_id_positive CHECK (id > 0),
    CONSTRAINT ck_privacy_attestations_owner_positive CHECK (owner_id > 0),
    CONSTRAINT ck_privacy_attestations_hash_format_v1 CHECK (hash_format = 1),
    CONSTRAINT ck_privacy_attestations_content_bounded CHECK (octet_length(canonical_json)
        BETWEEN 1 AND 16384),
    CONSTRAINT ck_privacy_attestations_hash_matches CHECK (content_hash =
        public.digest(convert_to(canonical_json, 'UTF8'), 'sha256')),
    CONSTRAINT ck_privacy_attestations_canonical_bytes CHECK (canonical_json =
        public.tamforge_provenance_canonical(canonical_json::jsonb)),
    CONSTRAINT uq_privacy_attestations_owner_policy UNIQUE (owner_id, policy_version),
    CONSTRAINT ck_privacy_attestations_policy_version_safe CHECK (policy_version ~
        '^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$'),
    CONSTRAINT fk_privacy_attestations_owner_id_owners FOREIGN KEY(owner_id) REFERENCES owners (id)
)
"""


def upgrade() -> None:
    op.execute(TABLE)
    op.execute(
        "CREATE TRIGGER trg_privacy_attestations_immutable "
        "BEFORE UPDATE OR DELETE OR TRUNCATE ON public.privacy_attestations "
        "FOR EACH STATEMENT EXECUTE FUNCTION public.tamforge_provenance_immutable()"
    )


def downgrade() -> None:
    op.drop_table("privacy_attestations")

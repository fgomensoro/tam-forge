"""Immutable local-transcript provenance and its append-only corrections."""

from alembic import op

revision = "20260909_0018_transcripts"
down_revision = "20260909_0017_attestations"
branch_labels = None
depends_on = None

TRANSCRIPTS_TABLE = r"""
CREATE TABLE speech_transcripts (
    recording_id BIGINT GENERATED ALWAYS AS ((canonical_json::jsonb->>'recording_id')::bigint)
        STORED NOT NULL,
    track TEXT GENERATED ALWAYS AS (canonical_json::jsonb->>'track') STORED NOT NULL,
    id BIGINT GENERATED ALWAYS AS IDENTITY,
    owner_id BIGINT NOT NULL,
    canonical_json TEXT NOT NULL,
    content_hash BYTEA NOT NULL,
    hash_format INTEGER DEFAULT '1' NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_speech_transcripts PRIMARY KEY (id),
    CONSTRAINT uq_speech_transcripts_owner_id_id UNIQUE (owner_id, id),
    CONSTRAINT ck_speech_transcripts_id_positive CHECK (id > 0),
    CONSTRAINT ck_speech_transcripts_owner_positive CHECK (owner_id > 0),
    CONSTRAINT ck_speech_transcripts_hash_format_v1 CHECK (hash_format = 1),
    CONSTRAINT ck_speech_transcripts_content_bounded CHECK (octet_length(canonical_json)
        BETWEEN 1 AND 4194304),
    CONSTRAINT ck_speech_transcripts_hash_matches CHECK (content_hash =
        public.digest(convert_to(canonical_json, 'UTF8'), 'sha256')),
    CONSTRAINT ck_speech_transcripts_canonical_bytes CHECK (canonical_json =
        public.tamforge_provenance_canonical(canonical_json::jsonb)),
    CONSTRAINT uq_speech_transcripts_recording_track UNIQUE (owner_id, recording_id, track),
    CONSTRAINT fk_speech_transcripts_recording FOREIGN KEY(owner_id, recording_id) REFERENCES
        recordings (owner_id, id) ON DELETE RESTRICT,
    CONSTRAINT ck_speech_transcripts_track_allowed CHECK (track IN
        ('microphone', 'system_audio')),
    CONSTRAINT fk_speech_transcripts_owner_id_owners FOREIGN KEY(owner_id) REFERENCES owners (id)
)
"""

CORRECTIONS_TABLE = r"""
CREATE TABLE speech_transcript_corrections (
    transcript_id BIGINT GENERATED ALWAYS AS ((canonical_json::jsonb->>'transcript_id')::bigint)
        STORED NOT NULL,
    id BIGINT GENERATED ALWAYS AS IDENTITY,
    owner_id BIGINT NOT NULL,
    canonical_json TEXT NOT NULL,
    content_hash BYTEA NOT NULL,
    hash_format INTEGER DEFAULT '1' NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_speech_transcript_corrections PRIMARY KEY (id),
    CONSTRAINT uq_speech_transcript_corrections_owner_id_id UNIQUE (owner_id, id),
    CONSTRAINT ck_speech_transcript_corrections_id_positive CHECK (id > 0),
    CONSTRAINT ck_speech_transcript_corrections_owner_positive CHECK (owner_id > 0),
    CONSTRAINT ck_speech_transcript_corrections_hash_format_v1 CHECK (hash_format = 1),
    CONSTRAINT ck_speech_transcript_corrections_content_bounded CHECK
        (octet_length(canonical_json) BETWEEN 1 AND 8192),
    CONSTRAINT ck_speech_transcript_corrections_hash_matches CHECK (content_hash =
        public.digest(convert_to(canonical_json, 'UTF8'), 'sha256')),
    CONSTRAINT ck_speech_transcript_corrections_canonical_bytes CHECK (canonical_json =
        public.tamforge_provenance_canonical(canonical_json::jsonb)),
    CONSTRAINT fk_speech_transcript_corrections_transcript FOREIGN KEY(owner_id, transcript_id)
        REFERENCES speech_transcripts (owner_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_speech_transcript_corrections_owner_id_owners FOREIGN KEY(owner_id) REFERENCES
        owners (id)
)
"""


def upgrade() -> None:
    op.execute(TRANSCRIPTS_TABLE)
    op.execute(
        "CREATE TRIGGER trg_speech_transcripts_immutable "
        "BEFORE UPDATE OR DELETE OR TRUNCATE ON public.speech_transcripts "
        "FOR EACH STATEMENT EXECUTE FUNCTION public.tamforge_provenance_immutable()"
    )
    op.execute(CORRECTIONS_TABLE)
    op.execute(
        "CREATE TRIGGER trg_speech_transcript_corrections_immutable "
        "BEFORE UPDATE OR DELETE OR TRUNCATE ON public.speech_transcript_corrections "
        "FOR EACH STATEMENT EXECUTE FUNCTION public.tamforge_provenance_immutable()"
    )


def downgrade() -> None:
    op.drop_table("speech_transcript_corrections")
    op.drop_table("speech_transcripts")

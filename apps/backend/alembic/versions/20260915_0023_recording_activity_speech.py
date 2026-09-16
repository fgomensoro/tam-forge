"""Link a recording to the activity it was made for; store the speech analysis per recording."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260915_0023_recording_activity"
down_revision = "20260912_0022_study_notes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("recordings", sa.Column("activity_instance_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "fk_recordings_owner_activity_activity_instances",
        "recordings",
        "activity_instances",
        ["owner_id", "activity_instance_id"],
        ["owner_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_recordings_owner_activity", "recordings", ["owner_id", "activity_instance_id"]
    )
    op.create_table(
        "speech_analyses",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("recording_id", sa.BigInteger(), nullable=False),
        sa.Column("microphone_transcript_id", sa.BigInteger(), nullable=False),
        sa.Column("system_audio_transcript_id", sa.BigInteger(), nullable=True),
        sa.Column("analysis_version", sa.Text(), nullable=False),
        sa.Column(
            "turns",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "metrics",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_speech_analyses"),
        sa.UniqueConstraint("owner_id", "id", name="uq_speech_analyses_owner_id_id"),
        sa.UniqueConstraint("owner_id", "recording_id", name="uq_speech_analyses_owner_recording"),
        sa.ForeignKeyConstraint(
            ["owner_id", "recording_id"],
            ["recordings.owner_id", "recordings.id"],
            name="fk_speech_analyses_owner_recording_recordings",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("jsonb_typeof(turns) = 'array'", name="turns_is_array"),
        sa.CheckConstraint("jsonb_typeof(metrics) = 'object'", name="metrics_is_object"),
        sa.CheckConstraint(
            "btrim(analysis_version) <> '' AND octet_length(analysis_version) <= 64",
            name="analysis_version_bounded",
        ),
    )


def downgrade() -> None:
    op.drop_table("speech_analyses")
    op.drop_index("ix_recordings_owner_activity", table_name="recordings")
    op.drop_constraint(
        "fk_recordings_owner_activity_activity_instances", "recordings", type_="foreignkey"
    )
    op.drop_column("recordings", "activity_instance_id")

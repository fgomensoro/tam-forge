"""Transcript-only interviews and imported reference material."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260916_0029_intv_transcript"
down_revision = "20260916_0028_coach_card_kind"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "interview_transcripts",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("interview_id", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False, server_default="transcript_only"),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("turns", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("analysis_version", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_interview_transcripts"),
        sa.UniqueConstraint("owner_id", "interview_id", name="uq_interview_transcripts_interview"),
        sa.ForeignKeyConstraint(
            ["owner_id", "interview_id"],
            ["interviews.owner_id", "interviews.id"],
            name="fk_interview_transcripts_interview",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("source = 'transcript_only'", name="source_allowed"),
        sa.CheckConstraint(
            "btrim(text) <> '' AND octet_length(text) <= 1048576", name="text_bounded"
        ),
        sa.CheckConstraint("jsonb_typeof(turns) = 'array'", name="turns_array"),
        sa.CheckConstraint("jsonb_typeof(metrics) = 'object'", name="metrics_object"),
    )
    op.create_table(
        "reference_materials",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("document_title", sa.Text(), nullable=False),
        sa.Column("heading", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("readiness_label", sa.Text(), nullable=False, server_default=""),
        sa.Column("readiness_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("content_hash", sa.LargeBinary(32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_reference_materials"),
        sa.UniqueConstraint("owner_id", "content_hash", name="uq_reference_materials_content"),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["owners.id"], name="fk_reference_materials_owner", ondelete="RESTRICT"
        ),
        sa.CheckConstraint("kind IN ('answer_bank', 'story_catalog')", name="kind_allowed"),
        sa.CheckConstraint(
            "btrim(heading) <> '' AND octet_length(heading) <= 512", name="heading_bounded"
        ),
        sa.CheckConstraint("octet_length(body) <= 65536", name="body_bounded"),
        sa.CheckConstraint("octet_length(content_hash) = 32", name="content_hash_length"),
    )
    op.create_index(
        "ix_reference_materials_owner_kind", "reference_materials", ["owner_id", "kind", "id"]
    )


def downgrade() -> None:
    op.drop_index("ix_reference_materials_owner_kind", table_name="reference_materials")
    op.drop_table("reference_materials")
    op.drop_table("interview_transcripts")

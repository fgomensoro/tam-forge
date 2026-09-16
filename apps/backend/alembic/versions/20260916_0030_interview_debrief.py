"""The reviewer's debrief of a real interview."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260916_0030_interview_debrief"
down_revision = "20260916_0029_intv_transcript"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "interview_debriefs",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("interview_id", sa.BigInteger(), nullable=False),
        sa.Column("transcript_source", sa.Text(), nullable=False),
        sa.Column("transcript_sha256", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("prompt_version", sa.Text(), nullable=False),
        sa.Column("outcome", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_interview_debriefs"),
        sa.UniqueConstraint("owner_id", "interview_id", name="uq_interview_debriefs_interview"),
        sa.ForeignKeyConstraint(
            ["owner_id", "interview_id"],
            ["interviews.owner_id", "interviews.id"],
            name="fk_interview_debriefs_interview",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "transcript_source IN ('recording', 'transcript_only')", name="source_allowed"
        ),
        sa.CheckConstraint("jsonb_typeof(outcome) = 'object'", name="outcome_object"),
    )


def downgrade() -> None:
    op.drop_table("interview_debriefs")

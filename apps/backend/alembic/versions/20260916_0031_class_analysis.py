"""The reviewer's analysis of an English class."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260916_0031_class_analysis"
down_revision = "20260916_0030_interview_debrief"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "class_analyses",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("english_class_id", sa.BigInteger(), nullable=False),
        sa.Column("transcript_sha256", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("prompt_version", sa.Text(), nullable=False),
        sa.Column("fluency_score", sa.Numeric(3, 1), nullable=False),
        sa.Column("vocabulary_score", sa.Numeric(3, 1), nullable=False),
        sa.Column("outcome", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_class_analyses"),
        sa.UniqueConstraint("owner_id", "english_class_id", name="uq_class_analyses_class"),
        sa.ForeignKeyConstraint(
            ["owner_id", "english_class_id"],
            ["english_classes.owner_id", "english_classes.id"],
            name="fk_class_analyses_class",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("jsonb_typeof(outcome) = 'object'", name="outcome_object"),
        sa.CheckConstraint(
            "fluency_score BETWEEN 0 AND 4 AND vocabulary_score BETWEEN 0 AND 4",
            name="scores_bounded",
        ),
    )


def downgrade() -> None:
    op.drop_table("class_analyses")

"""Free-practice interview answers and the review of each."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260918_0034_practice_answers"
down_revision = "20260916_0033_monthly_reports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "practice_answers",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("recording_id", sa.BigInteger(), nullable=False),
        sa.Column("reference_material_id", sa.BigInteger(), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("reference_answer", sa.Text(), server_default="", nullable=False),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("prompt_version", sa.Text(), nullable=True),
        sa.Column("outcome", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_practice_answers"),
        sa.UniqueConstraint("owner_id", "recording_id", name="uq_practice_answers_recording"),
        sa.ForeignKeyConstraint(
            ["owner_id", "recording_id"],
            ["recordings.owner_id", "recordings.id"],
            name="fk_practice_answers_recording",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reference_material_id"],
            ["reference_materials.id"],
            name="fk_practice_answers_reference",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "btrim(question) <> '' AND octet_length(question) <= 2048", name="question_bounded"
        ),
        sa.CheckConstraint("octet_length(reference_answer) <= 65536", name="reference_bounded"),
        sa.CheckConstraint(
            "outcome IS NULL OR jsonb_typeof(outcome) = 'object'", name="outcome_object"
        ),
        sa.CheckConstraint(
            "(outcome IS NULL) = (reviewed_at IS NULL) AND (outcome IS NULL) = (model IS NULL) "
            "AND (outcome IS NULL) = (prompt_version IS NULL)",
            name="review_complete_or_absent",
        ),
    )
    op.create_index(
        "ix_practice_answers_owner_created",
        "practice_answers",
        ["owner_id", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_practice_answers_owner_created", table_name="practice_answers")
    op.drop_table("practice_answers")

"""Weekly reports: composed by the analyst, stored, and delivered when a channel exists."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260916_0032_weekly_reports"
down_revision = "20260916_0031_class_analysis"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "weekly_reports",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("week_end", sa.Date(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("prompt_version", sa.Text(), nullable=False),
        sa.Column("inputs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("outcome", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("delivery_status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("delivery_detail", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_weekly_reports"),
        sa.UniqueConstraint("owner_id", "week_start", name="uq_weekly_reports_owner_week"),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["owners.id"], name="fk_weekly_reports_owner", ondelete="RESTRICT"
        ),
        sa.CheckConstraint("week_end >= week_start", name="week_ordered"),
        sa.CheckConstraint(
            "delivery_status IN ('pending', 'sent', 'failed', 'skipped')",
            name="delivery_status_allowed",
        ),
        sa.CheckConstraint("jsonb_typeof(inputs) = 'object'", name="inputs_object"),
        sa.CheckConstraint("jsonb_typeof(outcome) = 'object'", name="outcome_object"),
    )


def downgrade() -> None:
    op.drop_table("weekly_reports")

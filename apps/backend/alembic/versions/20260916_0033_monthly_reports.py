"""Monthly reports: each skill against its targets, composed by the analyst and stored."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260916_0033_monthly_reports"
down_revision = "20260916_0032_weekly_reports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "monthly_reports",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("month_start", sa.Date(), nullable=False),
        sa.Column("month_end", sa.Date(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name="pk_monthly_reports"),
        sa.UniqueConstraint("owner_id", "month_start", name="uq_monthly_reports_owner_month"),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["owners.id"], name="fk_monthly_reports_owner", ondelete="RESTRICT"
        ),
        sa.CheckConstraint("month_end >= month_start", name="month_ordered"),
        sa.CheckConstraint(
            "delivery_status IN ('pending', 'sent', 'failed', 'skipped')",
            name="delivery_status_allowed",
        ),
        sa.CheckConstraint("jsonb_typeof(inputs) = 'object'", name="inputs_object"),
        sa.CheckConstraint("jsonb_typeof(outcome) = 'object'", name="outcome_object"),
    )


def downgrade() -> None:
    op.drop_table("monthly_reports")

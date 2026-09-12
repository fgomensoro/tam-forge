"""One handoff per closed study day: outcomes, assistance, focused minutes, next action."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260912_0021_daily_handoffs"
down_revision = "20260912_0020_coach_threads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "daily_handoffs",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("study_day_id", sa.BigInteger(), nullable=False),
        sa.Column("daily_close_id", sa.BigInteger(), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("day_status", sa.Text(), nullable=False),
        sa.Column("focused_minutes", sa.Integer(), nullable=False),
        sa.Column("next_action", sa.Text(), nullable=False),
        sa.Column(
            "blocks",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "gaps",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_daily_handoffs"),
        sa.UniqueConstraint("owner_id", "id", name="uq_daily_handoffs_owner_id_id"),
        sa.UniqueConstraint(
            "owner_id", "study_day_id", name="uq_daily_handoffs_owner_study_day"
        ),
        sa.ForeignKeyConstraint(
            ["daily_close_id"],
            ["daily_closes.id"],
            name="fk_daily_handoffs_daily_close_daily_closes",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("day_status IN ('closed', 'incomplete')", name="day_status_allowed"),
        sa.CheckConstraint("focused_minutes >= 0", name="focused_minutes_nonnegative"),
        sa.CheckConstraint(
            "btrim(next_action) <> '' AND octet_length(next_action) <= 2048",
            name="next_action_bounded",
        ),
        sa.CheckConstraint("jsonb_typeof(blocks) = 'array'", name="blocks_is_array"),
        sa.CheckConstraint("jsonb_typeof(gaps) = 'array'", name="gaps_is_array"),
    )
    op.create_index(
        "ix_daily_handoffs_owner_local_date", "daily_handoffs", ["owner_id", "local_date"]
    )


def downgrade() -> None:
    op.drop_index("ix_daily_handoffs_owner_local_date", table_name="daily_handoffs")
    op.drop_table("daily_handoffs")

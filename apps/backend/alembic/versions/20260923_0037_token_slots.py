"""Claude token slots: which installed subscription token the worker uses."""

import sqlalchemy as sa
from alembic import op

revision = "20260923_0037_token_slots"
down_revision = "20260919_0036_shadowing_clips"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "claude_token_slots",
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("slot", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("owner_id", name="pk_claude_token_slots"),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name="fk_claude_token_slots_owner_id_owners",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("slot IN ('a', 'b')", name="ck_claude_token_slots_slot_allowed"),
    )


def downgrade() -> None:
    op.drop_table("claude_token_slots")

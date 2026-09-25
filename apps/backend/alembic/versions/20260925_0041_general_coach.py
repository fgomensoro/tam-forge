"""The owner's general Coach thread: a coach thread with no activity, one per owner."""

import sqlalchemy as sa
from alembic import op

revision = "20260925_0041_general_coach"
down_revision = "20260924_0040_import_restaging"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "coach_threads", "activity_instance_id", existing_type=sa.BigInteger(), nullable=True
    )
    op.create_index(
        "uq_coach_threads_owner_general",
        "coach_threads",
        ["owner_id"],
        unique=True,
        postgresql_where=sa.text("activity_instance_id IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_coach_threads_owner_general", table_name="coach_threads")
    general = "SELECT id FROM coach_threads WHERE activity_instance_id IS NULL"
    op.execute(f"DELETE FROM coach_evidence WHERE thread_id IN ({general})")
    op.execute(f"DELETE FROM coach_messages WHERE thread_id IN ({general})")
    op.execute("DELETE FROM coach_threads WHERE activity_instance_id IS NULL")
    op.alter_column(
        "coach_threads", "activity_instance_id", existing_type=sa.BigInteger(), nullable=False
    )

"""Link a recording to the real interview it captured."""

import sqlalchemy as sa
from alembic import op

revision = "20260916_0025_interview_link"
down_revision = "20260916_0024_activity_reviews"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("recordings", sa.Column("interview_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "fk_recordings_owner_interview_interviews",
        "recordings",
        "interviews",
        ["owner_id", "interview_id"],
        ["owner_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_recordings_owner_interview", "recordings", ["owner_id", "interview_id"])


def downgrade() -> None:
    op.drop_index("ix_recordings_owner_interview", table_name="recordings")
    op.drop_constraint("fk_recordings_owner_interview_interviews", "recordings", type_="foreignkey")
    op.drop_column("recordings", "interview_id")

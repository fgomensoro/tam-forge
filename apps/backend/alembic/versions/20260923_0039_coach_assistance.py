"""Coach threads record the assistance given before the commit."""

import sqlalchemy as sa
from alembic import op

revision = "20260923_0039_coach_assistance"
down_revision = "20260923_0038_version_starts_on"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "coach_threads",
        sa.Column("assistance_mode", sa.Text(), nullable=False, server_default="none"),
    )
    op.create_check_constraint(
        "ck_coach_threads_assistance_mode_allowed",
        "coach_threads",
        "assistance_mode IN ('none', 'coach_preparation', 'hint_ladder')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_coach_threads_assistance_mode_allowed", "coach_threads", type_="check"
    )
    op.drop_column("coach_threads", "assistance_mode")

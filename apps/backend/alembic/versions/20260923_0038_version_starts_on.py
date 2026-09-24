"""Roadmap version anchor: the learner-local date a re-activated version's day 1 lands on."""

import sqlalchemy as sa
from alembic import op

revision = "20260923_0038_version_starts_on"
down_revision = "20260923_0037_token_slots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("roadmap_versions", sa.Column("starts_on", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("roadmap_versions", "starts_on")

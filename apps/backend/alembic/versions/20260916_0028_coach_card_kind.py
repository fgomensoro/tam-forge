"""The Coach may propose a card; accepting one records that kind of evidence."""

from alembic import op

revision = "20260916_0028_coach_card_kind"
down_revision = "20260916_0027_cards"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("kind_allowed", "coach_evidence", type_="check")
    op.create_check_constraint(
        "kind_allowed", "coach_evidence", "kind IN ('note', 'correction', 'question', 'card')"
    )


def downgrade() -> None:
    op.execute("DELETE FROM coach_evidence WHERE kind = 'card'")
    op.drop_constraint("kind_allowed", "coach_evidence", type_="check")
    op.create_check_constraint(
        "kind_allowed", "coach_evidence", "kind IN ('note', 'correction', 'question')"
    )

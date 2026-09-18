"""A practice answer may respond to a follow-up on an earlier practice answer."""

import sqlalchemy as sa
from alembic import op

revision = "20260918_0035_follow_ups"
down_revision = "20260918_0034_practice_answers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("practice_answers", sa.Column("follow_up_of", sa.BigInteger(), nullable=True))
    op.add_column("practice_answers", sa.Column("follow_up_question", sa.Text(), nullable=True))
    op.create_foreign_key(
        "fk_practice_answers_follow_up_of",
        "practice_answers",
        "practice_answers",
        ["follow_up_of"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_check_constraint(
        "follow_up_paired",
        "practice_answers",
        "(follow_up_of IS NULL) = (follow_up_question IS NULL)",
    )
    op.create_check_constraint(
        "follow_up_question_bounded",
        "practice_answers",
        "follow_up_question IS NULL OR (btrim(follow_up_question) <> '' "
        "AND octet_length(follow_up_question) <= 2048)",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_practice_answers_follow_up_question_bounded"), "practice_answers", type_="check"
    )
    op.drop_constraint(
        op.f("ck_practice_answers_follow_up_paired"), "practice_answers", type_="check"
    )
    op.drop_constraint(
        "fk_practice_answers_follow_up_of", "practice_answers", type_="foreignkey"
    )
    op.drop_column("practice_answers", "follow_up_question")
    op.drop_column("practice_answers", "follow_up_of")

"""Flashcards and their reviews, scheduled with SM-2."""

import sqlalchemy as sa
from alembic import op

revision = "20260916_0027_cards"
down_revision = "20260916_0026_english_classes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cards",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.LargeBinary(32), nullable=False),
        sa.Column("source_kind", sa.Text(), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=False, server_default=""),
        sa.Column("skill_slug", sa.Text(), nullable=False),
        sa.Column("assistance", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("scheduler_version", sa.Text(), nullable=False),
        sa.Column("easiness", sa.Numeric(4, 2), nullable=False),
        sa.Column("interval_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("repetitions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("due_on", sa.Date(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_cards"),
        sa.UniqueConstraint("owner_id", "id", name="uq_cards_owner_id_id"),
        sa.UniqueConstraint("owner_id", "content_hash", name="uq_cards_owner_content_hash"),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["owners.id"], name="fk_cards_owner_id_owners", ondelete="RESTRICT"
        ),
        sa.CheckConstraint(
            "source_kind IN ('study_note', 'evidence', 'package', 'coach', 'manual')",
            name="source_kind_allowed",
        ),
        sa.CheckConstraint("assistance IN ('independent', 'coached')", name="assistance_allowed"),
        sa.CheckConstraint("status IN ('active', 'suspended')", name="status_allowed"),
        sa.CheckConstraint(
            "btrim(question) <> '' AND octet_length(question) <= 2048", name="question_bounded"
        ),
        sa.CheckConstraint(
            "btrim(answer) <> '' AND octet_length(answer) <= 4096", name="answer_bounded"
        ),
        sa.CheckConstraint("octet_length(content_hash) = 32", name="content_hash_length"),
        sa.CheckConstraint("easiness >= 1.3", name="easiness_floor"),
        sa.CheckConstraint("interval_days >= 0 AND repetitions >= 0", name="schedule_nonnegative"),
    )
    op.create_index("ix_cards_owner_due", "cards", ["owner_id", "status", "due_on"])
    op.create_index("ix_cards_owner_skill", "cards", ["owner_id", "skill_slug"])
    op.create_table(
        "card_reviews",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("card_id", sa.BigInteger(), nullable=False),
        sa.Column("grade", sa.Integer(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False, server_default="written"),
        sa.Column("reviewed_on", sa.Date(), nullable=False),
        sa.Column("interval_before", sa.Integer(), nullable=False),
        sa.Column("interval_after", sa.Integer(), nullable=False),
        sa.Column("easiness_after", sa.Numeric(4, 2), nullable=False),
        sa.Column("due_after", sa.Date(), nullable=False),
        sa.Column("recording_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_card_reviews"),
        sa.UniqueConstraint("owner_id", "id", name="uq_card_reviews_owner_id_id"),
        sa.ForeignKeyConstraint(
            ["owner_id", "card_id"],
            ["cards.owner_id", "cards.id"],
            name="fk_card_reviews_owner_card_cards",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("grade BETWEEN 0 AND 5", name="grade_bounded"),
        sa.CheckConstraint("mode IN ('written', 'spoken')", name="mode_allowed"),
    )
    op.create_index("ix_card_reviews_owner_card", "card_reviews", ["owner_id", "card_id", "id"])


def downgrade() -> None:
    op.drop_index("ix_card_reviews_owner_card", table_name="card_reviews")
    op.drop_table("card_reviews")
    op.drop_index("ix_cards_owner_skill", table_name="cards")
    op.drop_index("ix_cards_owner_due", table_name="cards")
    op.drop_table("cards")

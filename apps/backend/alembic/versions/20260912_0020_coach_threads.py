"""One coaching thread per activity, its messages, and the evidence the learner accepted."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260912_0020_coach_threads"
down_revision = "20260912_0019_worker_heartbeats"
branch_labels = None
depends_on = None


def _id() -> sa.Column[int]:
    return sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False)


def _created(name: str = "created_at") -> sa.Column[object]:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        server_default=sa.text("CURRENT_TIMESTAMP"),
        nullable=False,
    )


def upgrade() -> None:
    op.create_table(
        "coach_threads",
        _id(),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("activity_instance_id", sa.BigInteger(), nullable=False),
        _created(),
        _created("updated_at"),
        sa.PrimaryKeyConstraint("id", name="pk_coach_threads"),
        sa.UniqueConstraint("owner_id", "id", name="uq_coach_threads_owner_id_id"),
        sa.UniqueConstraint(
            "owner_id", "activity_instance_id", name="uq_coach_threads_owner_activity"
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "activity_instance_id"],
            ["activity_instances.owner_id", "activity_instances.id"],
            name="fk_coach_threads_owner_activity_activity_instances",
            ondelete="RESTRICT",
        ),
    )
    op.create_table(
        "coach_messages",
        _id(),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("thread_id", sa.BigInteger(), nullable=False),
        sa.Column("speaker", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("next_step", sa.Text(), nullable=True),
        sa.Column(
            "proposed_evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        _created(),
        sa.PrimaryKeyConstraint("id", name="pk_coach_messages"),
        sa.UniqueConstraint("owner_id", "id", name="uq_coach_messages_owner_id_id"),
        sa.ForeignKeyConstraint(
            ["owner_id", "thread_id"],
            ["coach_threads.owner_id", "coach_threads.id"],
            name="fk_coach_messages_owner_thread_coach_threads",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("speaker IN ('learner', 'coach')", name="speaker_allowed"),
        sa.CheckConstraint(
            "btrim(text) <> '' AND octet_length(text) <= 16384", name="text_bounded"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(proposed_evidence) = 'array'", name="proposed_evidence_is_array"
        ),
    )
    op.create_index(
        "ix_coach_messages_owner_thread_id", "coach_messages", ["owner_id", "thread_id", "id"]
    )
    op.create_table(
        "coach_evidence",
        _id(),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("thread_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("proposal_index", sa.Integer(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        _created("accepted_at"),
        sa.PrimaryKeyConstraint("id", name="pk_coach_evidence"),
        sa.UniqueConstraint("owner_id", "id", name="uq_coach_evidence_owner_id_id"),
        sa.UniqueConstraint(
            "owner_id", "message_id", "proposal_index", name="uq_coach_evidence_message_proposal"
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "thread_id"],
            ["coach_threads.owner_id", "coach_threads.id"],
            name="fk_coach_evidence_owner_thread_coach_threads",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "message_id"],
            ["coach_messages.owner_id", "coach_messages.id"],
            name="fk_coach_evidence_owner_message_coach_messages",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("kind IN ('note', 'correction', 'question')", name="kind_allowed"),
        sa.CheckConstraint("proposal_index >= 0", name="proposal_index_nonnegative"),
        sa.CheckConstraint("btrim(text) <> '' AND octet_length(text) <= 4096", name="text_bounded"),
    )


def downgrade() -> None:
    op.drop_table("coach_evidence")
    op.drop_index("ix_coach_messages_owner_thread_id", table_name="coach_messages")
    op.drop_table("coach_messages")
    op.drop_table("coach_threads")

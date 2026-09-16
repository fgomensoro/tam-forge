"""One AI review per activity: rubric scores, reasoning, and the evidence it recorded."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260916_0024_activity_reviews"
down_revision = "20260915_0023_recording_activity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "activity_reviews",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("activity_instance_id", sa.BigInteger(), nullable=False),
        sa.Column("attempt_id", sa.BigInteger(), nullable=False),
        sa.Column("rubric_slug", sa.Text(), nullable=False),
        sa.Column("rubric_version", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("prompt_version", sa.Text(), nullable=False),
        sa.Column("outcome", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("evidence_status", sa.Text(), nullable=False),
        sa.Column(
            "evidence_event_ids",
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
        sa.PrimaryKeyConstraint("id", name="pk_activity_reviews"),
        sa.UniqueConstraint("owner_id", "id", name="uq_activity_reviews_owner_id_id"),
        sa.UniqueConstraint(
            "owner_id", "activity_instance_id", name="uq_activity_reviews_owner_activity"
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "activity_instance_id"],
            ["activity_instances.owner_id", "activity_instances.id"],
            name="fk_activity_reviews_owner_activity_activity_instances",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("jsonb_typeof(outcome) = 'object'", name="outcome_is_object"),
        sa.CheckConstraint(
            "jsonb_typeof(evidence_event_ids) = 'array'", name="evidence_event_ids_array"
        ),
        sa.CheckConstraint(
            "btrim(evidence_status) <> '' AND octet_length(evidence_status) <= 256",
            name="evidence_status_bounded",
        ),
    )


def downgrade() -> None:
    op.drop_table("activity_reviews")

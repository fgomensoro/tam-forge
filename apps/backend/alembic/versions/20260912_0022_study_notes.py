"""One study note per activity: drafted, edited, and approved into an evidence artifact."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260912_0022_study_notes"
down_revision = "20260912_0021_daily_handoffs"
branch_labels = None
depends_on = None


def _jsonb_array(name: str) -> sa.Column[object]:
    return sa.Column(
        name,
        postgresql.JSONB(astext_type=sa.Text()),
        server_default=sa.text("'[]'::jsonb"),
        nullable=False,
    )


def _timestamp(name: str, *, nullable: bool = False) -> sa.Column[object]:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        server_default=None if nullable else sa.text("CURRENT_TIMESTAMP"),
        nullable=nullable,
    )


def upgrade() -> None:
    op.create_table(
        "study_notes",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("activity_instance_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("drafted_by", sa.Text(), nullable=False),
        sa.Column("assistance", sa.Text(), nullable=False),
        sa.Column("assessment_status", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("rule", sa.Text(), nullable=False, server_default=""),
        sa.Column("explanation", sa.Text(), nullable=False, server_default=""),
        sa.Column("example", sa.Text(), nullable=False, server_default=""),
        _jsonb_array("misconceptions"),
        _jsonb_array("validated_queries"),
        _jsonb_array("sources"),
        _jsonb_array("flashcards"),
        sa.Column("artifact_id", sa.BigInteger(), nullable=True),
        sa.Column("content_sha256", sa.Text(), nullable=True),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        _timestamp("approved_at", nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_study_notes"),
        sa.UniqueConstraint("owner_id", "id", name="uq_study_notes_owner_id_id"),
        sa.UniqueConstraint(
            "owner_id", "activity_instance_id", name="uq_study_notes_owner_activity"
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "activity_instance_id"],
            ["activity_instances.owner_id", "activity_instances.id"],
            name="fk_study_notes_owner_activity_activity_instances",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "artifact_id"],
            ["artifacts.owner_id", "artifacts.id"],
            name="fk_study_notes_owner_artifact_artifacts",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("status IN ('draft', 'approved')", name="status_allowed"),
        sa.CheckConstraint("assistance IN ('independent', 'coached')", name="assistance_allowed"),
        sa.CheckConstraint("drafted_by IN ('learner', 'coach')", name="drafted_by_allowed"),
        sa.CheckConstraint(
            "(status = 'approved') = (artifact_id IS NOT NULL)", name="approved_has_artifact"
        ),
        sa.CheckConstraint(
            "btrim(title) <> '' AND octet_length(title) <= 1024", name="title_bounded"
        ),
        sa.CheckConstraint("jsonb_typeof(misconceptions) = 'array'", name="misconceptions_array"),
        sa.CheckConstraint(
            "jsonb_typeof(validated_queries) = 'array'", name="validated_queries_array"
        ),
        sa.CheckConstraint("jsonb_typeof(sources) = 'array'", name="sources_array"),
        sa.CheckConstraint("jsonb_typeof(flashcards) = 'array'", name="flashcards_array"),
    )
    op.create_index(
        "ix_study_notes_owner_status_updated",
        "study_notes",
        ["owner_id", "status", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_study_notes_owner_status_updated", table_name="study_notes")
    op.drop_table("study_notes")

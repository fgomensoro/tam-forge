"""Shadowing clips: a short excerpt in the object store and its phrases."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260919_0036_shadowing_clips"
down_revision = "20260918_0035_follow_ups"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shadowing_clips",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("format", sa.Text(), nullable=False),
        sa.Column("skill_slug", sa.Text(), nullable=False),
        sa.Column("source_note", sa.Text(), server_default="", nullable=False),
        sa.Column("license_note", sa.Text(), server_default="", nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column(
            "phrases",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "annotations",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("preparation_state", sa.Text(), server_default="pending", nullable=False),
        sa.Column("excerpt_object_key", sa.Text(), nullable=True),
        sa.Column("excerpt_content_type", sa.Text(), nullable=True),
        sa.Column("excerpt_byte_length", sa.BigInteger(), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name="pk_shadowing_clips"),
        sa.UniqueConstraint("owner_id", "id", name="uq_shadowing_clips_owner_id_id"),
        sa.UniqueConstraint("excerpt_object_key", name="uq_shadowing_clips_excerpt_object_key"),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name="fk_shadowing_clips_owner_id_owners",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("format IN ('solo', 'dialogue')", name="format_allowed"),
        sa.CheckConstraint(
            "preparation_state IN ('pending', 'ready', 'failed')", name="preparation_state_allowed"
        ),
        sa.CheckConstraint(
            "btrim(title) <> '' AND octet_length(title) <= 800", name="title_bounded"
        ),
        sa.CheckConstraint(
            "octet_length(source_note) <= 2000 AND octet_length(license_note) <= 2000",
            name="notes_bounded",
        ),
        sa.CheckConstraint("duration_ms BETWEEN 1000 AND 120000", name="duration_bounded"),
        sa.CheckConstraint("jsonb_typeof(phrases) = 'array'", name="phrases_array"),
        sa.CheckConstraint("jsonb_typeof(annotations) = 'array'", name="annotations_array"),
        sa.CheckConstraint(
            "(excerpt_object_key IS NULL) = (excerpt_content_type IS NULL) "
            "AND (excerpt_object_key IS NULL) = (excerpt_byte_length IS NULL)",
            name="excerpt_complete_or_absent",
        ),
        sa.CheckConstraint(
            "excerpt_content_type IS NULL "
            "OR excerpt_content_type IN ('audio/mp4', 'video/mp4', 'video/quicktime')",
            name="excerpt_content_type_allowed",
        ),
        sa.CheckConstraint(
            "excerpt_byte_length IS NULL OR excerpt_byte_length BETWEEN 1 AND 104857600",
            name="excerpt_byte_length_bounded",
        ),
    )
    op.create_index(
        "ix_shadowing_clips_owner_created",
        "shadowing_clips",
        ["owner_id", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_shadowing_clips_owner_created", table_name="shadowing_clips")
    op.drop_table("shadowing_clips")

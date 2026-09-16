"""English class sessions, and the recording that captured one."""

import sqlalchemy as sa
from alembic import op

revision = "20260916_0026_english_classes"
down_revision = "20260916_0025_interview_link"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "english_classes",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("teacher", sa.Text(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expected_duration_minutes", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("skill_slug", sa.Text(), nullable=False, server_default="tam_english"),
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
        sa.PrimaryKeyConstraint("id", name="pk_english_classes"),
        sa.UniqueConstraint("owner_id", "id", name="uq_english_classes_owner_id_id"),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name="fk_english_classes_owner_id_owners",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "btrim(teacher) <> '' AND octet_length(teacher) <= 256", name="teacher_bounded"
        ),
        sa.CheckConstraint(
            "expected_duration_minutes BETWEEN 1 AND 480", name="expected_duration_bounded"
        ),
        sa.CheckConstraint("octet_length(notes) <= 16384", name="notes_bounded"),
        sa.CheckConstraint("skill_slug = 'tam_english'", name="skill_slug_tam_english"),
    )
    op.create_index("ix_english_classes_owner_starts", "english_classes", ["owner_id", "starts_at"])
    op.add_column("recordings", sa.Column("english_class_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "fk_recordings_owner_class_english_classes",
        "recordings",
        "english_classes",
        ["owner_id", "english_class_id"],
        ["owner_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_recordings_owner_class", "recordings", ["owner_id", "english_class_id"])


def downgrade() -> None:
    op.drop_index("ix_recordings_owner_class", table_name="recordings")
    op.drop_constraint(
        "fk_recordings_owner_class_english_classes", "recordings", type_="foreignkey"
    )
    op.drop_column("recordings", "english_class_id")
    op.drop_index("ix_english_classes_owner_starts", table_name="english_classes")
    op.drop_table("english_classes")

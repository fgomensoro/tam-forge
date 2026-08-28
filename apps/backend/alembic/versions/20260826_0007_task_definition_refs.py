"""Allow operational correction tasks to inherit exercise references.

Revision ID: 20260826_0007_task_refs
Revises: 20260826_0006_score_payload
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260826_0007_task_refs"
down_revision: str | None = "20260826_0006_score_payload"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EXERCISE_MAPPING_COHERENT = (
    "(block = 'correction_warmup' AND exercise_type IS NULL "
    "AND mapping_version IS NULL) OR "
    "(block <> 'correction_warmup' AND exercise_type IS NOT NULL "
    "AND mapping_version IS NOT NULL)"
)


def upgrade() -> None:
    op.alter_column(
        "task_definitions",
        "exercise_type",
        existing_type=sa.Text(),
        nullable=True,
    )
    op.alter_column(
        "task_definitions",
        "mapping_version",
        existing_type=sa.Text(),
        nullable=True,
    )
    op.create_check_constraint(
        "exercise_mapping_coherent",
        "task_definitions",
        _EXERCISE_MAPPING_COHERENT,
    )


def downgrade() -> None:
    # Existing correction warm-ups make the NOT NULL restoration fail closed;
    # downgrade never fabricates exercise references or mutates task history.
    op.drop_constraint(
        op.f("ck_task_definitions_exercise_mapping_coherent"),
        "task_definitions",
        type_="check",
    )
    op.alter_column(
        "task_definitions",
        "mapping_version",
        existing_type=sa.Text(),
        nullable=False,
    )
    op.alter_column(
        "task_definitions",
        "exercise_type",
        existing_type=sa.Text(),
        nullable=False,
    )

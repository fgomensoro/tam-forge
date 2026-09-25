"""Let an unchanged package be staged again once a parser change makes its import stale.

Folder uploads and scheme stagings build deterministic zips, so the same content
always has the same package hash. A second import with that hash is how a new
parse of unchanged files reaches review and approval instead of the stale row.
Once one exists, downgrade fails on the restored unique constraint.
"""

from alembic import op

revision = "20260924_0040_import_restaging"
down_revision = "20260923_0039_coach_assistance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("uq_roadmap_imports_source_package_hash", "roadmap_imports", type_="unique")
    op.create_index(
        "ix_roadmap_imports_source_id_package_hash",
        "roadmap_imports",
        ["source_id", "package_hash"],
    )


def downgrade() -> None:
    op.drop_index("ix_roadmap_imports_source_id_package_hash", table_name="roadmap_imports")
    op.create_unique_constraint(
        "uq_roadmap_imports_source_package_hash",
        "roadmap_imports",
        ["source_id", "package_hash"],
    )

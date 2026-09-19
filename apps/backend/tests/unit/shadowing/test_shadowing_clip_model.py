from __future__ import annotations

import importlib.util
from pathlib import Path

MIGRATION = Path("apps/backend/alembic/versions/20260919_0036_shadowing_clips.py")


def test_clip_table_has_the_agreed_columns_and_owner_scope() -> None:
    from tamforge_backend.shadowing.models import (
        EXCERPT_CONTENT_TYPES,
        PREPARATION_STATES,
        SHADOWING_FORMATS,
        ShadowingClip,
    )

    table = ShadowingClip.__table__
    assert table.name == "shadowing_clips"
    assert {column.name for column in table.columns} == {
        "id",
        "owner_id",
        "title",
        "format",
        "skill_slug",
        "source_note",
        "license_note",
        "duration_ms",
        "phrases",
        "annotations",
        "preparation_state",
        "excerpt_object_key",
        "excerpt_content_type",
        "excerpt_byte_length",
        "created_at",
        "updated_at",
    }
    assert [key.target_fullname for key in table.c.owner_id.foreign_keys] == ["owners.id"]
    assert table.c.excerpt_object_key.nullable
    assert not table.c.phrases.nullable and not table.c.annotations.nullable
    assert SHADOWING_FORMATS == ("solo", "dialogue")
    assert PREPARATION_STATES == ("pending", "ready", "failed")
    assert EXCERPT_CONTENT_TYPES == ("audio/mp4", "video/mp4", "video/quicktime")


def test_migration_id_fits_alembic_version_and_follows_the_current_head() -> None:
    spec = importlib.util.spec_from_file_location("shadowing_clips_migration", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.revision == "20260919_0036_shadowing_clips"
    assert len(module.revision) <= 32
    assert module.down_revision == "20260918_0035_follow_ups"

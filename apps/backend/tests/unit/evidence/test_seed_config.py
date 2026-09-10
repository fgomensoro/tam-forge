from __future__ import annotations

import asyncio
import importlib.util
import os
from pathlib import Path

from tamforge_backend.evidence.config_loader import load_config_bundle
from tamforge_backend.evidence.seed import seed_config

CONFIG_DIR = Path(__file__).parents[5] / "config"


def test_dry_run_reports_exact_validated_counts_without_database() -> None:
    bundle = load_config_bundle(CONFIG_DIR)
    result = asyncio.run(seed_config(bundle, owner_id=None, session=None, apply=False))
    assert result.status == "validated"
    assert result.config_versions == 1
    assert result.competencies == 14
    assert result.exercise_types == 34
    assert result.exercise_skill_mappings == sum(
        len(exercise.skill_impacts) + len(exercise.allowed_selected_competencies)
        for exercise in bundle.exercise_types
    )
    assert result.rubrics == 1
    assert result.rubric_dimensions == 7
    assert result.roadmap_tasks == 158


def test_config_seed_model_persists_complete_canonical_payload() -> None:
    from tamforge_backend.evidence.models import (
        ASSISTANCE_CODES,
        QUALIFYING_ASSISTANCE_CODES,
        ConfigSeedVersion,
    )

    assert "canonical_payload" in ConfigSeedVersion.__table__.c
    names = {
        constraint.name
        for constraint in ConfigSeedVersion.__table__.constraints
        if constraint.name is not None
    }
    assert "ck_config_seed_versions_canonical_payload_valid" in names
    assert "ai_interviewer_only" not in ASSISTANCE_CODES
    assert QUALIFYING_ASSISTANCE_CODES == {"no_ai", "ai_after_committed_attempt"}


def test_payload_migration_is_linear_and_does_not_rewrite_old_migrations() -> None:
    migration_path = Path(
        "apps/backend/alembic/versions/20260826_0006_scoring_config_payload.py"
    )
    assert migration_path.exists()
    spec = importlib.util.spec_from_file_location("scoring_config_payload", migration_path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.revision == "20260826_0006_score_payload"
    assert len(migration.revision) <= 32
    assert migration.down_revision == "20260825_0005_today_read_models"

    task_refs_path = Path(
        "apps/backend/alembic/versions/20260826_0007_task_definition_refs.py"
    )
    assert task_refs_path.exists()
    task_refs_spec = importlib.util.spec_from_file_location(
        "task_definition_refs", task_refs_path
    )
    assert task_refs_spec is not None and task_refs_spec.loader is not None
    task_refs = importlib.util.module_from_spec(task_refs_spec)
    task_refs_spec.loader.exec_module(task_refs)
    assert task_refs.revision == "20260826_0007_task_refs"
    assert len(task_refs.revision) <= 32
    assert task_refs.down_revision == "20260826_0006_score_payload"


def test_test_database_url_is_not_implicitly_required_for_dry_run(monkeypatch) -> None:
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    assert "TEST_DATABASE_URL" not in os.environ
    bundle = load_config_bundle(CONFIG_DIR)
    assert (
        asyncio.run(seed_config(bundle, owner_id=None, session=None, apply=False)).status
        == "validated"
    )

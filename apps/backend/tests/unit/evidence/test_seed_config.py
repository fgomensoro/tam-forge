from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from tamforge_backend.evidence.config_loader import load_config_bundle
from tamforge_backend.evidence.seed import seed_config

CONFIG_DIR = Path(__file__).parents[5] / "config"


@pytest.fixture
def test_database_url() -> str:
    from tamforge_backend.database import validate_test_database_url

    raw_url = os.getenv("TEST_DATABASE_URL")
    if raw_url is None:
        pytest.skip("TEST_DATABASE_URL is required; tests never autostart Docker")
    return validate_test_database_url(raw_url)


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
    assert result.roadmap_tasks == 138


@pytest.mark.integration
def test_seed_is_idempotent_and_changed_mapping_creates_new_version(
    test_database_url: str, tmp_path: Path
) -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import func, select
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from tamforge_backend.auth.models import Owner
    from tamforge_backend.evidence.models import (
        Competency,
        ConfigSeedVersion,
        ExerciseSkillMapping,
        ExerciseTypeVersion,
        RubricDimension,
        RubricVersion,
    )

    config = Config("apps/backend/alembic.ini")
    config.attributes["database_url"] = test_database_url
    command.downgrade(config, "base")
    command.upgrade(config, "head")

    async def exercise_seed() -> None:
        async_url = make_url(test_database_url).set(drivername="postgresql+asyncpg")
        engine = create_async_engine(async_url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with factory.begin() as session:
                owner = Owner(github_user_id=102269369, github_login="fgomensoro")
                session.add(owner)
                await session.flush()
                owner_id = owner.id

            bundle = load_config_bundle(CONFIG_DIR)
            async with factory.begin() as session:
                first = await seed_config(bundle, owner_id=owner_id, session=session, apply=True)
            async with factory.begin() as session:
                second = await seed_config(bundle, owner_id=owner_id, session=session, apply=True)

            assert first.status == "inserted"
            assert second.status == "unchanged"
            assert second.inserted_rows == 0

            fixture_dir = tmp_path / "config"
            fixture_dir.mkdir()
            for source in CONFIG_DIR.glob("*.yaml"):
                target = fixture_dir / source.name
                text = source.read_text(encoding="utf-8")
                text = text.replace("seed-v1", "seed-v2")
                target.write_text(text, encoding="utf-8")
            changed = load_config_bundle(fixture_dir)
            async with factory.begin() as session:
                third = await seed_config(changed, owner_id=owner_id, session=session, apply=True)

            assert third.status == "inserted"
            assert third.config_version_id != first.config_version_id
            async with factory() as session:
                assert (
                    await session.scalar(select(func.count()).select_from(ConfigSeedVersion))
                    == 2
                )
                assert (
                    await session.scalar(
                        select(func.count()).select_from(ExerciseTypeVersion).where(
                            ExerciseTypeVersion.mapping_version == "seed-v1"
                        )
                    )
                    == 34
                )
                assert await session.scalar(select(func.count()).select_from(Competency)) == 28
                assert (
                    await session.scalar(
                        select(func.count()).select_from(ExerciseSkillMapping)
                    )
                    == 338
                )
                assert (
                    await session.scalar(
                        select(func.count()).select_from(ExerciseSkillMapping).where(
                            ExerciseSkillMapping.condition_code == "reviewed_dynamic_impact"
                        )
                    )
                    == 42
                )
                assert await session.scalar(select(func.count()).select_from(RubricVersion)) == 2
                assert (
                    await session.scalar(select(func.count()).select_from(RubricDimension))
                    == 14
                )
                assert (
                    await session.scalar(
                        select(func.count()).select_from(ExerciseTypeVersion).where(
                            ExerciseTypeVersion.mapping_version == "seed-v2"
                        )
                    )
                    == 34
                )
        finally:
            await engine.dispose()

    try:
        asyncio.run(exercise_seed())
    finally:
        command.downgrade(config, "base")


def test_test_database_url_is_not_implicitly_required_for_dry_run(monkeypatch) -> None:
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    assert "TEST_DATABASE_URL" not in os.environ
    bundle = load_config_bundle(CONFIG_DIR)
    assert (
        asyncio.run(seed_config(bundle, owner_id=None, session=None, apply=False)).status
        == "validated"
    )

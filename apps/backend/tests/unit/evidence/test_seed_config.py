from __future__ import annotations

import asyncio
import importlib.util
import os
from pathlib import Path

import pytest
from tamforge_backend.evidence.config_loader import load_config_bundle, load_config_payload
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
                persisted = await session.scalar(
                    select(ConfigSeedVersion).where(ConfigSeedVersion.id == first.config_version_id)
                )
                assert persisted is not None
                reconstructed = load_config_payload(persisted.canonical_payload)
                assert reconstructed.content_hash == bundle.content_hash
                assert reconstructed.canonical_payload == bundle.canonical_payload
                assert reconstructed.roadmap_contracts == bundle.roadmap_contracts
                assert reconstructed.reconciliations == bundle.reconciliations
                assert reconstructed.exercise(
                    "portfolio_triage"
                ).composite_metric_weights == bundle.exercise(
                    "portfolio_triage"
                ).composite_metric_weights
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


@pytest.mark.integration
def test_concurrent_seed_calls_serialize_per_owner_and_insert_once(
    test_database_url: str,
) -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import func, select
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from tamforge_backend.auth.models import Owner
    from tamforge_backend.evidence.models import ConfigSeedVersion

    config = Config("apps/backend/alembic.ini")
    config.attributes["database_url"] = test_database_url
    command.downgrade(config, "base")
    command.upgrade(config, "head")

    async def exercise_concurrent_seed() -> None:
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
            start = asyncio.Event()

            async def run_seed():
                await start.wait()
                async with factory.begin() as session:
                    return await seed_config(
                        bundle,
                        owner_id=owner_id,
                        session=session,
                        apply=True,
                    )

            calls = [asyncio.create_task(run_seed()) for _ in range(2)]
            start.set()
            results = await asyncio.gather(*calls)
            assert sorted(result.status for result in results) == ["inserted", "unchanged"]
            async with factory() as session:
                assert (
                    await session.scalar(select(func.count()).select_from(ConfigSeedVersion))
                    == 1
                )
        finally:
            await engine.dispose()

    try:
        asyncio.run(exercise_concurrent_seed())
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

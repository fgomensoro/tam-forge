from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from tamforge_backend.evidence.config_loader import load_config_bundle, load_config_payload
from tamforge_backend.evidence.seed import seed_config

CONFIG_DIR = Path(__file__).parents[5] / "config"


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

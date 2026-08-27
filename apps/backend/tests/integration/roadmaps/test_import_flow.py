from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

ROOT = Path(__file__).parents[5]
FIXTURE = ROOT / "apps" / "backend" / "tests" / "fixtures" / "roadmaps" / "month-v1.zip"


def test_import_approval_and_activation_are_durable_and_separate(
    test_database_url: str,
) -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, func, select, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from tamforge_backend.database import database_url_to_sync
    from tamforge_backend.evidence.config_loader import load_config_bundle
    from tamforge_backend.notifications.models import OutboxEvent
    from tamforge_backend.roadmaps.models import (
        CurriculumNode,
        RoadmapImport,
        RoadmapVersion,
        TaskDefinition,
    )
    from tamforge_backend.roadmaps.package import inspect_zip_stream
    from tamforge_backend.roadmaps.repository import SqlAlchemyRoadmapRepository
    from tamforge_backend.roadmaps.service import RoadmapService
    from tamforge_backend.storage.fake import InMemoryObjectStore

    config = Config("apps/backend/alembic.ini")
    config.attributes["database_url"] = test_database_url
    sync_engine = create_engine(database_url_to_sync(test_database_url))
    try:
        command.downgrade(config, "base")
        command.upgrade(config, "head")
        with sync_engine.begin() as connection:
            owner_id = connection.execute(
                text(
                    "INSERT INTO owners (github_user_id, github_login) "
                    "VALUES (102269369, 'fgomensoro') RETURNING id"
                )
            ).scalar_one()

        async_url = make_url(test_database_url).set(drivername="postgresql+asyncpg")

        async def exercise() -> None:
            engine = create_async_engine(async_url)
            factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
            try:
                async with factory() as session:
                    repository = SqlAlchemyRoadmapRepository(session)
                    service = RoadmapService(
                        config=load_config_bundle(ROOT / "config"),
                        repository=repository,
                        object_store=InMemoryObjectStore(),
                        mirror=None,
                    )
                    with inspect_zip_stream((FIXTURE.read_bytes(),)) as package:
                        staged = await service.stage_package(
                            owner_id=owner_id,
                            source_key="obsidian-main",
                            source_name="TAM Roadmap",
                            source_kind="obsidian",
                            package_kind="zip",
                            idempotency_key="integration-import-1",
                            package=package,
                        )
                    assert staged.status == "validated"
                    approved = await service.approve_import(
                        owner_id=owner_id,
                        import_id=staged.id,
                    )
                    assert approved.state == "approved"
                    assert approved.mirror_status == "not_required"
                    assert (
                        await session.scalar(
                            select(func.count()).select_from(TaskDefinition)
                        )
                    ) == 158
                    assert (
                        await session.scalar(
                            select(func.count()).select_from(CurriculumNode)
                        )
                    ) > 158
                    await session.rollback()

                    activated = await service.activate_version(
                        owner_id=owner_id,
                        version_id=approved.id,
                    )
                    assert activated.state == "active"
                    persisted_import = await session.get(RoadmapImport, staged.id)
                    persisted_version = await session.get(RoadmapVersion, approved.id)
                    assert persisted_import is not None
                    assert persisted_import.status == "imported"
                    assert persisted_version is not None
                    assert persisted_version.state == "active"
                    assert (
                        await session.scalar(
                            select(func.count()).select_from(OutboxEvent)
                        )
                    ) == 2
                    await session.rollback()

                    first_collision = await repository.create_staged_import(
                        owner_id=owner_id,
                        source_key="obsidian-main",
                        source_name="TAM Roadmap",
                        source_kind="obsidian",
                        package_hash="2" * 64,
                        object_key="roadmap-source/1/collision-first/" + "2" * 64,
                        idempotency_key="collision-first",
                    )
                    key_collision = await repository.create_staged_import(
                        owner_id=owner_id,
                        source_key="obsidian-main",
                        source_name="TAM Roadmap",
                        source_kind="obsidian",
                        package_hash="3" * 64,
                        object_key="roadmap-source/1/collision-key/" + "3" * 64,
                        idempotency_key="collision-key",
                    )
                    selected = await repository.find_duplicate_import(
                        owner_id=owner_id,
                        source_key="obsidian-main",
                        idempotency_key="collision-key",
                        package_hash="2" * 64,
                    )
                    assert selected is not None
                    assert selected.id == key_collision.record.id
                    assert selected.id != first_collision.record.id
            finally:
                await engine.dispose()

        asyncio.run(exercise())
    finally:
        try:
            with sync_engine.begin() as connection:
                connection.execute(text("DROP SCHEMA public CASCADE"))
                connection.execute(text("CREATE SCHEMA public"))
        finally:
            sync_engine.dispose()

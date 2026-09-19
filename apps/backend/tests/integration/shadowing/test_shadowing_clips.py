"""Shadowing clips on Postgres: owner-scoped CRUD and the excerpt upload round trip."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import pytest

pytestmark = pytest.mark.integration

NOW = datetime(2026, 9, 19, 12, tzinfo=UTC)
LATER = datetime(2026, 9, 19, 13, tzinfo=UTC)


@contextmanager
def _two_owners(test_database_url: str) -> Iterator[tuple[int, int]]:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text
    from tamforge_backend.database import database_url_to_sync

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
            other_id = connection.execute(
                text(
                    "INSERT INTO owners (github_user_id, github_login) "
                    "VALUES (7, 'someone') RETURNING id"
                )
            ).scalar_one()
        yield owner_id, other_id
    finally:
        try:
            with sync_engine.begin() as connection:
                connection.execute(text("DROP SCHEMA public CASCADE"))
                connection.execute(text("CREATE SCHEMA public"))
        finally:
            sync_engine.dispose()


def _run(test_database_url: str, exercise: Callable[[Any], Awaitable[None]]) -> None:
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    async def main() -> None:
        async_url = make_url(test_database_url).set(drivername="postgresql+asyncpg")
        engine = create_async_engine(async_url)
        factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        try:
            await exercise(factory)
        finally:
            await engine.dispose()

    asyncio.run(main())


def _command(title: str = "QBR opening") -> Any:
    from tamforge_backend.shadowing.schemas import ShadowingClipCommand, ShadowingPhrase

    return ShadowingClipCommand(
        title=title,
        format="dialogue",
        skill_slug="english_fluency",
        source_note="Recorded talk, minute 3",
        license_note="CC BY 4.0",
        duration_ms=45_000,
        phrases=(
            ShadowingPhrase(
                index=0, start_ms=0, end_ms=2_000, text="Thanks for joining.", enabled=True
            ),
            ShadowingPhrase(
                index=1, start_ms=2_000, end_ms=4_500, text="Let's dive in.", enabled=False
            ),
        ),
    )


def test_clips_are_created_listed_replaced_and_deleted_per_owner(test_database_url: str) -> None:
    from tamforge_backend.shadowing.service import ShadowingClipService, ShadowingNotFound
    from tamforge_backend.storage.fake import InMemoryObjectStore

    with _two_owners(test_database_url) as (owner_id, other_id):

        async def exercise(factory: Any) -> None:
            store = InMemoryObjectStore()
            async with factory() as session:
                service = ShadowingClipService(session, store, clock=lambda: NOW)
                created = await service.create(owner_id=owner_id, command=_command())
            assert created.title == "QBR opening" and created.format == "dialogue"
            assert created.preparation_state == "pending"
            assert created.annotations == () and created.excerpt is None
            assert [phrase.enabled for phrase in created.phrases] == [True, False]
            assert created.created_at == NOW and created.updated_at == NOW

            async with factory() as session:
                service = ShadowingClipService(session, store, clock=lambda: LATER)
                second = await service.create(owner_id=owner_id, command=_command("Renewal call"))
                foreign = await service.create(owner_id=other_id, command=_command("Not yours"))
                page = await service.list(owner_id=owner_id)
                assert [item.id for item in page.items] == [second.id, created.id]
                assert (await service.get(owner_id=owner_id, clip_id=created.id)) == created

                replaced = await service.replace(
                    owner_id=owner_id, clip_id=created.id, command=_command("QBR opening, take 2")
                )
                assert replaced.title == "QBR opening, take 2"
                assert replaced.created_at == NOW and replaced.updated_at == LATER

                for call in (
                    service.get(owner_id=owner_id, clip_id=foreign.id),
                    service.replace(owner_id=owner_id, clip_id=foreign.id, command=_command()),
                    service.delete(owner_id=owner_id, clip_id=foreign.id),
                    service.get(owner_id=owner_id, clip_id=999_999),
                ):
                    with pytest.raises(ShadowingNotFound):
                        await call

                await service.delete(owner_id=owner_id, clip_id=created.id)
                with pytest.raises(ShadowingNotFound):
                    await service.get(owner_id=owner_id, clip_id=created.id)
                assert [item.id for item in (await service.list(owner_id=owner_id)).items] == [
                    second.id
                ]
                assert len((await service.list(owner_id=other_id)).items) == 1

        _run(test_database_url, exercise)


def test_duration_outside_bounds_is_rejected_by_the_database(test_database_url: str) -> None:
    """Carried from the Task 1 review: no test yet exercised the table's check
    constraints against a live database. This proves `duration_bounded`, and by
    extension the constraint names in the model and the migration, are enforced."""
    from sqlalchemy import create_engine
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import Session
    from tamforge_backend.database import database_url_to_sync
    from tamforge_backend.shadowing.models import ShadowingClip

    with _two_owners(test_database_url) as (owner_id, _other_id):
        engine = create_engine(database_url_to_sync(test_database_url))
        try:
            with pytest.raises(IntegrityError, match="duration_bounded"):
                with Session(engine) as session:
                    session.add(
                        ShadowingClip(
                            owner_id=owner_id,
                            title="Too short",
                            format="solo",
                            skill_slug="english_fluency",
                            duration_ms=500,
                            phrases=[],
                            annotations=[],
                        )
                    )
                    session.commit()
        finally:
            engine.dispose()

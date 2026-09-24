"""The slot choice is one row per owner, defaults to A, and refuses anything but a or b."""

from __future__ import annotations

import asyncio

import pytest


@pytest.mark.integration
def test_the_slot_defaults_to_a_keeps_the_last_choice_and_refuses_others(
    test_database_url: str,
) -> None:
    from sqlalchemy import text
    from sqlalchemy.engine import make_url
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from tamforge_backend.agents.token_slots import choose_slot, read_active_slot
    from tamforge_backend.auth.models import Owner

    async def exercise() -> None:
        engine = create_async_engine(
            make_url(test_database_url).set(drivername="postgresql+asyncpg")
        )
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with sessions.begin() as session:
                owner = Owner(github_user_id=102269369, github_login="fgomensoro")
                session.add(owner)
                await session.flush()
                owner_id = owner.id

            async with sessions() as session:
                assert await read_active_slot(session, owner_id=owner_id) == "a"
            async with sessions() as session:
                await choose_slot(session, owner_id=owner_id, slot="b")
            async with sessions() as session:
                await choose_slot(session, owner_id=owner_id, slot="b")
            async with sessions() as session:
                assert await read_active_slot(session, owner_id=owner_id) == "b"
                count = await session.scalar(text("select count(*) from claude_token_slots"))
                assert count == 1
            async with sessions() as session:
                await choose_slot(session, owner_id=owner_id, slot="a")
            async with sessions() as session:
                assert await read_active_slot(session, owner_id=owner_id) == "a"

            with pytest.raises(IntegrityError):
                async with sessions.begin() as session:
                    await session.execute(
                        text("update claude_token_slots set slot = 'c' where owner_id = :id"),
                        {"id": owner_id},
                    )
        finally:
            await engine.dispose()

    asyncio.run(exercise())

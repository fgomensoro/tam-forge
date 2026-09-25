"""The slot choice is one row per owner, defaults to A, and refuses anything but a or b."""

from __future__ import annotations

import asyncio

import pytest


@pytest.fixture(autouse=True)
def fresh_schema(test_database_url: str) -> None:
    """Each test creates the owner; start from an empty schema so none is left over."""
    from alembic import command
    from alembic.config import Config

    config = Config("apps/backend/alembic.ini")
    config.attributes["database_url"] = test_database_url
    command.downgrade(config, "base")
    command.upgrade(config, "head")


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


@pytest.mark.integration
def test_the_api_runtime_follows_the_first_owners_slot(test_database_url: str) -> None:
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from tamforge_backend.agents.token_slots import choose_slot, follow_deployment_slot
    from tamforge_backend.auth.models import Owner

    tokens = {"a": "sk-ant-oat01-fixture", "b": "sk-ant-oat01-fixture-b"}

    class Runtime:
        def __init__(self) -> None:
            self.slots: list[str] = []

        def use_slot(self, slot: str, installed: object) -> None:
            assert installed == tokens
            self.slots.append(slot)

    async def exercise() -> None:
        engine = create_async_engine(
            make_url(test_database_url).set(drivername="postgresql+asyncpg")
        )
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        runtime = Runtime()
        try:
            await follow_deployment_slot(sessions, runtime, tokens)  # type: ignore[arg-type]
            async with sessions.begin() as session:
                owner = Owner(github_user_id=102269369, github_login="fgomensoro")
                session.add(owner)
                await session.flush()
                owner_id = owner.id
            async with sessions() as session:
                await choose_slot(session, owner_id=owner_id, slot="b")
            await follow_deployment_slot(sessions, runtime, tokens)  # type: ignore[arg-type]
            assert runtime.slots == ["a", "b"]
        finally:
            await engine.dispose()

    asyncio.run(exercise())


@pytest.mark.integration
def test_the_api_starts_on_the_chosen_slot(
    test_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The coach, notes, roadmap and follow-ups run Claude in the API process itself."""
    from fastapi.testclient import TestClient
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from tamforge_backend.agents.token_slots import choose_slot
    from tamforge_backend.auth.models import Owner
    from tamforge_backend.config import Settings
    from tamforge_backend.main import create_app

    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-fixture")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN_B", "sk-ant-oat01-fixture-b")

    async def choose_b() -> None:
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
                await choose_slot(session, owner_id=owner_id, slot="b")
        finally:
            await engine.dispose()

    asyncio.run(choose_b())
    app = create_app(
        Settings(
            environment="test",
            github_user_id=102269369,
            database_url=test_database_url,
            cors_origins=["https://app.example.test"],
            secure_cookies=False,
            _env_file=None,
        )
    )
    with TestClient(app):
        runtime = app.state.planner_transport
        assert runtime._worker_environment() == {
            "CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat01-fixture-b"
        }

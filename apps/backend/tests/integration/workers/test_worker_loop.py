"""Workers beat into the shared table and the housekeeping step runs on a real database."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest


@pytest.mark.integration
def test_general_worker_beats_and_housekeeping_runs_against_postgres(
    test_database_url: str,
) -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from tamforge_backend.config import Settings
    from tamforge_backend.database import database_url_to_sync
    from tamforge_backend.observability.heartbeats import WorkerHeartbeatStore
    from tamforge_backend.workers.general import housekeeping_step
    from tamforge_backend.workers.runtime import run_worker

    config = Config("apps/backend/alembic.ini")
    config.attributes["database_url"] = test_database_url
    sync_engine = create_engine(database_url_to_sync(test_database_url))
    try:
        command.downgrade(config, "base")
        command.upgrade(config, "head")

        async def exercise() -> None:
            async_url = make_url(test_database_url).set(drivername="postgresql+asyncpg")
            engine = create_async_engine(async_url)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            try:
                store = WorkerHeartbeatStore(sessions)
                await store.beat(worker="claude", status="needs_attention", reason="auth")
                await store.beat(worker="claude", status="needs_attention", reason="auth")
                now = datetime.now(UTC)
                assert await store.recent(now=now) == {"claude": ("needs_attention", "auth")}
                assert await store.recent(now=now + timedelta(minutes=2)) == {}
                with pytest.raises(ValueError):
                    await store.beat(worker="claude", status="great", reason="none")

                settings = Settings(
                    environment="test",
                    github_user_id=102269369,
                    database_url=test_database_url,
                    cors_origins=["https://app.example.test"],
                    secure_cookies=False,
                    _env_file=None,
                )
                await run_worker(
                    "general",
                    housekeeping_step,
                    settings=settings,
                    interval_seconds=0.01,
                    iterations=2,
                )
                recent = await store.recent(now=datetime.now(UTC))
                assert recent["general"] == ("ok", "none")

                async def failing(_sessions: object) -> str | None:
                    raise RuntimeError("boom")

                await run_worker(
                    "speech", failing, settings=settings, interval_seconds=0.01, iterations=1
                )
                recent = await store.recent(now=datetime.now(UTC))
                assert recent["speech"] == ("needs_attention", "processing_failure")
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

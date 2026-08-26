from __future__ import annotations

import asyncio
from typing import Any

import pytest
from tamforge_backend import database
from tamforge_backend.config import Settings


class FakeEngine:
    def __init__(self) -> None:
        self.disposed = False

    async def dispose(self) -> None:
        self.disposed = True


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.closes = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def close(self) -> None:
        self.closes += 1


def test_database_resources_use_one_bounded_pool_and_lazy_session_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, Any] = {}
    engine = FakeEngine()
    session_factory = object()

    def fake_create_async_engine(url: str, **kwargs: object) -> FakeEngine:
        calls["engine"] = (url, kwargs)
        return engine

    def fake_async_sessionmaker(**kwargs: object) -> object:
        calls["sessionmaker"] = kwargs
        return session_factory

    monkeypatch.setattr(database, "create_async_engine", fake_create_async_engine)
    monkeypatch.setattr(database, "async_sessionmaker", fake_async_sessionmaker)

    resources = database.create_database_resources(Settings())

    url, engine_options = calls["engine"]
    assert url.startswith("postgresql+asyncpg://")
    assert engine_options == {
        "pool_pre_ping": True,
        "pool_size": 4,
        "max_overflow": 2,
        "pool_timeout": 10,
        "pool_recycle": 300,
        "connect_args": {
            "prepared_statement_cache_size": 0,
            "server_settings": {
                "statement_timeout": "30000",
                "idle_in_transaction_session_timeout": "30000",
            },
        },
    }
    assert calls["sessionmaker"] == {
        "bind": engine,
        "class_": database.AsyncSession,
        "expire_on_commit": False,
        "autoflush": False,
    }
    assert resources.engine is engine
    assert resources.session_factory is session_factory


def test_session_scope_commits_only_after_success_and_always_closes() -> None:
    session = FakeSession()

    async def exercise() -> None:
        async with database.session_scope(lambda: session) as yielded:
            assert yielded is session

    asyncio.run(exercise())

    assert session.commits == 1
    assert session.rollbacks == 0
    assert session.closes == 1


def test_session_scope_rolls_back_on_exception_and_always_closes() -> None:
    session = FakeSession()

    async def exercise() -> None:
        with pytest.raises(RuntimeError, match="boom"):
            async with database.session_scope(lambda: session):
                raise RuntimeError("boom")

    asyncio.run(exercise())

    assert session.commits == 0
    assert session.rollbacks == 1
    assert session.closes == 1


def test_database_resources_dispose_the_shared_engine() -> None:
    engine = FakeEngine()
    resources = database.DatabaseResources(engine=engine, session_factory=object())  # type: ignore[arg-type]

    asyncio.run(resources.dispose())

    assert engine.disposed is True


def test_migration_url_translation_is_structured_and_preserves_escaped_values() -> None:
    translated = database.database_url_to_sync(
        "postgresql+asyncpg://tamforge:p%40ss@db.internal:5432/tamforge"
    )

    assert translated == "postgresql+psycopg://tamforge:p%40ss@db.internal:5432/tamforge"


@pytest.mark.parametrize(
    "url",
    [
        "sqlite:///tmp.db",
        "mysql://user:secret@db.invalid/app",
        "postgresql+unknown://user:secret@db.invalid/app",
        "not-a-url",
    ],
)
def test_migration_url_translation_rejects_unsupported_or_malformed_urls(url: str) -> None:
    with pytest.raises(ValueError, match="PostgreSQL"):
        database.database_url_to_sync(url)


def test_test_database_url_validation_accepts_only_the_named_test_database() -> None:
    url = "postgresql+asyncpg://tamforge:secret@postgres:5432/tamforge_test"

    assert database.validate_test_database_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+asyncpg://tamforge:secret@127.0.0.1:54329/tamforge",
        "postgresql+asyncpg://tamforge:secret@prod.invalid:5432/production",
        "sqlite:///tamforge_test.db",
        "not-a-url",
    ],
)
def test_test_database_url_validation_rejects_unsafe_targets_without_echoing_url(
    url: str,
) -> None:
    with pytest.raises(ValueError) as exc_info:
        database.validate_test_database_url(url)

    assert url not in str(exc_info.value)

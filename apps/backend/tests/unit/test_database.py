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


class FakeTransaction:
    def __init__(self, session: FakeSession) -> None:
        self.session = session

    async def __aenter__(self) -> FakeSession:
        self.session.events.append("begin")
        return self.session

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        del exc, traceback
        if exc_type is not None:
            self.session.rollbacks += 1
            self.session.events.append("transaction-rollback")
            return
        self.session.events.append("commit-attempt")
        if self.session.commit_raises:
            raise RuntimeError("commit failed")
        self.session.commits += 1
        self.session.events.append("commit")


class FakeSession:
    def __init__(self, *, rollback_raises: bool = False, commit_raises: bool = False) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.closes = 0
        self.rollback_raises = rollback_raises
        self.commit_raises = commit_raises
        self.events: list[str] = []

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1
        self.events.append("rollback")
        if self.rollback_raises:
            raise RuntimeError("rollback failed")

    async def close(self) -> None:
        self.closes += 1
        self.events.append("close")

    def begin(self) -> FakeTransaction:
        return FakeTransaction(self)


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

    resources = database.create_database_resources(Settings(_env_file=None))

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


def test_session_scope_rolls_back_uncommitted_work_on_normal_response_and_closes() -> None:
    session = FakeSession()

    async def exercise() -> dict[str, str]:
        async with database.session_scope(lambda: session) as yielded:
            assert yielded is session
            response = {"status": "built-before-dependency-teardown"}
        return response

    response = asyncio.run(exercise())

    assert response == {"status": "built-before-dependency-teardown"}
    assert session.commits == 0
    assert session.rollbacks == 1
    assert session.closes == 1
    assert session.events == ["rollback", "close"]


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


def test_session_scope_rolls_back_cancellation_and_always_closes() -> None:
    session = FakeSession()

    async def exercise() -> None:
        with pytest.raises(asyncio.CancelledError):
            async with database.session_scope(lambda: session):
                raise asyncio.CancelledError

    asyncio.run(exercise())

    assert session.commits == 0
    assert session.rollbacks == 1
    assert session.closes == 1


def test_session_scope_closes_even_when_rollback_fails() -> None:
    session = FakeSession(rollback_raises=True)

    async def exercise() -> None:
        with pytest.raises(RuntimeError, match="rollback failed"):
            async with database.session_scope(lambda: session):
                pass

    asyncio.run(exercise())

    assert session.commits == 0
    assert session.rollbacks == 1
    assert session.closes == 1
    assert session.events[-1] == "close"


def test_explicit_transaction_commits_before_handler_returns() -> None:
    session = FakeSession()

    async def handler() -> str:
        async with database.transaction_scope(session):
            session.events.append("write")
        session.events.append("return")
        return "response"

    assert asyncio.run(handler()) == "response"
    assert session.commits == 1
    assert session.events == ["begin", "write", "commit-attempt", "commit", "return"]


def test_explicit_transaction_commit_failure_prevents_handler_return() -> None:
    session = FakeSession(commit_raises=True)

    async def handler() -> None:
        async with database.transaction_scope(session):
            session.events.append("write")
        session.events.append("return")

    with pytest.raises(RuntimeError, match="commit failed"):
        asyncio.run(handler())

    assert "return" not in session.events
    assert session.commits == 0


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
    url = "postgresql+asyncpg://tamforge:secret@127.0.0.1:54329/tamforge_test"

    assert database.validate_test_database_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+asyncpg://tamforge:secret@127.0.0.1:54329/tamforge",
        "postgresql+asyncpg://tamforge:secret@prod.invalid:5432/production",
        "postgresql+asyncpg://tamforge:secret@prod.invalid:5432/tamforge_test",
        "postgresql+asyncpg://tamforge:secret@10.0.0.2:5432/tamforge_test",
        "postgresql+asyncpg://tamforge:secret@8.8.8.8:5432/tamforge_test",
        "postgresql+asyncpg://tamforge:secret@localhost:54329/tamforge_test",
        "postgresql+asyncpg://tamforge:secret@[::1]:54329/tamforge_test",
        "postgresql+asyncpg://tamforge:secret@host1,host2:54329/tamforge_test",
        "postgresql+asyncpg://tamforge:secret@127.0.0.1/tamforge_test",
        "postgresql+asyncpg://tamforge:secret@127.0.0.1:0/tamforge_test",
        "postgresql+asyncpg://tamforge:secret@127.0.0.1:65536/tamforge_test",
        (
            "postgresql+asyncpg://tamforge:secret@127.0.0.1:54329/tamforge_test"
            "?sslmode=require"
        ),
        (
            "postgresql+asyncpg://tamforge:secret@127.0.0.1:54329/tamforge_test"
            "?host=prod.invalid"
        ),
        "postgresql+asyncpg://tamforge:secret@/tamforge_test?host=/tmp",
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


def test_migration_url_resolution_rejects_absent_explicit_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ValueError, match="explicit migration database URL"):
        database.resolve_migration_url(None)


def test_migration_url_resolution_rejects_blank_explicit_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://tamforge:ignored@db.internal:5432/tamforge_test",
    )

    with pytest.raises(ValueError, match="explicit migration database URL"):
        database.resolve_migration_url("   ")


def test_migration_url_resolution_ignores_ambient_application_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ambient_secret = "ambient-application-secret"
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv(
        "TAMFORGE_DATABASE_URL",
        f"postgresql+asyncpg://tamforge:{ambient_secret}@db.internal:5432/tamforge",
    )

    with pytest.raises(ValueError) as exc_info:
        database.resolve_migration_url(None)

    assert ambient_secret not in str(exc_info.value)


def test_migration_url_resolution_converts_explicit_asyncpg_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    resolved = database.resolve_migration_url(
        "postgresql+asyncpg://tamforge:p%40ss@db.internal:5432/tamforge_test"
    )

    assert resolved == "postgresql+psycopg://tamforge:p%40ss@db.internal:5432/tamforge_test"


def test_migration_url_resolution_accepts_explicit_alembic_config_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    resolved = database.resolve_migration_url(
        None,
        configured_url=(
            "postgresql+asyncpg://tamforge:secret@db.internal:5432/tamforge_test"
        ),
    )

    assert resolved == "postgresql+psycopg://tamforge:secret@db.internal:5432/tamforge_test"


def test_migration_url_resolution_uses_database_url_environment_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://tamforge:secret@db.internal:5432/tamforge_test",
    )

    resolved = database.resolve_migration_url(None)

    assert resolved == "postgresql+psycopg://tamforge:secret@db.internal:5432/tamforge_test"


def test_migration_url_resolution_never_echoes_invalid_explicit_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    secret = "migration-secret-that-must-not-leak"

    with pytest.raises(ValueError) as exc_info:
        database.resolve_migration_url(f"not-postgres://user:{secret}@host.invalid/database")

    assert secret not in str(exc_info.value)

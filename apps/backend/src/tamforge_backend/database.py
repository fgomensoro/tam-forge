"""Lazy SQLAlchemy resources and explicit request transaction boundaries."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import cast

from fastapi import Request
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .config import Settings

SessionFactory = async_sessionmaker[AsyncSession]


@dataclass(frozen=True, slots=True)
class DatabaseResources:
    """One engine and session factory shared for an application lifespan."""

    engine: AsyncEngine
    session_factory: SessionFactory

    async def dispose(self) -> None:
        """Release every pooled database connection on application shutdown."""
        await self.engine.dispose()


def create_database_resources(settings: Settings) -> DatabaseResources:
    """Create a bounded, lazy pool without opening a database connection."""
    engine = create_async_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
        pool_size=4,
        max_overflow=2,
        pool_timeout=10,
        pool_recycle=300,
        connect_args={
            "prepared_statement_cache_size": 0,
            "server_settings": {
                "statement_timeout": "30000",
                "idle_in_transaction_session_timeout": "30000",
            },
        },
    )
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    return DatabaseResources(engine=engine, session_factory=session_factory)


@asynccontextmanager
async def session_scope(
    factory: Callable[[], AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Yield a request session that never commits during dependency teardown.

    Route and service code must use :func:`transaction_scope` for writes. That
    keeps commit failures inside the request handler, before a response can be
    returned, rather than discovering them after the response has started.
    """
    session = factory()
    try:
        yield session
    finally:
        try:
            await session.rollback()
        finally:
            await session.close()


@asynccontextmanager
async def transaction_scope(session: AsyncSession) -> AsyncIterator[AsyncSession]:
    """Own an explicit unit of work and commit before the context returns."""
    async with session.begin():
        yield session


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Provide a rollback-only session from the lifespan-scoped factory."""
    resources = cast(DatabaseResources, request.app.state.database)
    async with session_scope(resources.session_factory) as session:
        yield session


def database_url_to_sync(raw_url: str) -> str:
    """Translate a supported application PostgreSQL URL for Alembic safely."""
    try:
        url = make_url(raw_url)
    except Exception as exc:
        raise ValueError("a valid PostgreSQL database URL is required") from exc

    allowed_drivers = {"postgresql", "postgresql+asyncpg", "postgresql+psycopg"}
    if url.drivername not in allowed_drivers:
        raise ValueError("a supported PostgreSQL database URL is required")
    if not url.host or not url.username or not url.password or not url.database:
        raise ValueError("a complete PostgreSQL database URL is required")

    return url.set(drivername="postgresql+psycopg").render_as_string(hide_password=False)


def resolve_migration_url(
    injected_url: str | None,
    *,
    configured_url: str | None = None,
) -> str:
    """Resolve only an explicit Alembic source, never application settings."""
    raw_url: str | None
    if injected_url is not None:
        raw_url = injected_url
    elif configured_url is not None and configured_url.strip():
        raw_url = configured_url
    else:
        raw_url = os.getenv("DATABASE_URL")
    if raw_url is None or not raw_url.strip():
        raise ValueError("an explicit migration database URL is required")
    try:
        return database_url_to_sync(raw_url)
    except ValueError:
        raise ValueError(
            "the explicit migration database URL must be complete PostgreSQL"
        ) from None


def validate_test_database_url(raw_url: str) -> str:
    """Fail closed before a destructive migration test targets the wrong database."""
    try:
        url = make_url(raw_url)
        port = url.port
    except Exception:
        raise ValueError("TEST_DATABASE_URL must target local PostgreSQL tamforge_test") from None

    allowed_drivers = {"postgresql", "postgresql+asyncpg", "postgresql+psycopg"}
    if (
        url.drivername not in allowed_drivers
        or url.host != "127.0.0.1"
        or not url.username
        or not url.password
        or url.database != "tamforge_test"
        or port is None
        or not 1 <= port <= 65535
        or bool(url.query)
    ):
        raise ValueError("TEST_DATABASE_URL must target local PostgreSQL tamforge_test")
    return raw_url

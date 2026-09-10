from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def test_migrations_round_trip_and_keep_version_table(test_database_url: str) -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect
    from tamforge_backend.database import database_url_to_sync

    config = Config("apps/backend/alembic.ini")
    config.attributes["database_url"] = test_database_url

    command.upgrade(config, "head")
    engine = create_engine(database_url_to_sync(test_database_url))
    try:
        assert inspect(engine).has_table("alembic_version")
    finally:
        engine.dispose()

    try:
        command.downgrade(config, "base")
    finally:
        command.upgrade(config, "head")


def test_dropping_the_schema_does_not_leak_into_the_next_test(test_database_url: str) -> None:
    """First half of a pair: drop the schema the way most integration files do at teardown."""
    from sqlalchemy import create_engine, text
    from tamforge_backend.database import database_url_to_sync

    engine = create_engine(database_url_to_sync(test_database_url))
    try:
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
    finally:
        engine.dispose()


def test_next_test_still_sees_the_migrated_schema(test_database_url: str) -> None:
    """Second half: without the autouse restore this fails on an undefined table."""
    from sqlalchemy import create_engine, text
    from tamforge_backend.database import database_url_to_sync

    engine = create_engine(database_url_to_sync(test_database_url))
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT to_regclass('public.owners')")) is not None
    finally:
        engine.dispose()

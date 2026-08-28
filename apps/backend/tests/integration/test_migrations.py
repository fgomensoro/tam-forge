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

    command.downgrade(config, "base")
    command.upgrade(config, "head")

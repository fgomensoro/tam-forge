from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="session")
def test_database_url(destructive_database_lock: None) -> str:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is required; tests never autostart Docker")
    from tamforge_backend.database import validate_test_database_url

    try:
        return validate_test_database_url(url)
    except ValueError:
        pytest.fail(
            "TEST_DATABASE_URL must be a complete PostgreSQL URL for tamforge_test",
            pytrace=False,
        )


@pytest.fixture(autouse=True)
def database_at_head(test_database_url: str) -> None:
    """Restore the schema the previous test dropped.

    Integration tests here rebuild the database themselves, and most drop the public schema at
    teardown. A file that only expects the schema the CI step migrated would otherwise fail at
    setup with an undefined-table error naming a file that is not the one that dropped it.
    """
    from alembic import command
    from alembic.config import Config

    config = Config("apps/backend/alembic.ini")
    config.attributes["database_url"] = test_database_url
    command.upgrade(config, "head")

from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="session")
def test_database_url() -> str:
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

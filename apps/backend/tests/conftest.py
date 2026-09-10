"""Guards shared by every backend suite that rebuilds the real PostgreSQL schema."""

from __future__ import annotations

import fcntl
import os
from collections.abc import Iterator

import pytest


@pytest.fixture(scope="session")
def destructive_database_lock(request: pytest.FixtureRequest) -> Iterator[None]:
    """Serialize the suites that drop and recreate one test database's schema.

    These tests migrate their database down to base and back up between cases, so two
    sessions pointed at the same database delete each other's tables mid-test. That
    surfaces as unrelated tests failing with missing relations, deadlocks or duplicate
    catalog keys and then passing on a rerun. An exclusive file lock makes the second
    session wait its turn.

    The lock is named after the target instance, so a checkout that publishes its own
    container runs at full speed beside the others, and a session with no usable
    TEST_DATABASE_URL takes no lock at all because it cannot reach a database.
    """
    from tamforge_backend.testing.database_lock import destructive_database_lock_path

    path = destructive_database_lock_path(os.getenv("TEST_DATABASE_URL"))
    if path is None:
        yield
        return
    with path.open("w") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            capture = request.config.pluginmanager.getplugin("capturemanager")
            with capture.global_and_fixture_disabled():
                print(
                    f"\nwaiting for another TAM Forge test session to release {path}",
                    flush=True,
                )
            fcntl.flock(handle, fcntl.LOCK_EX)
        yield

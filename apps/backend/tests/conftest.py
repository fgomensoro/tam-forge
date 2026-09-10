"""Guards shared by every backend suite that rebuilds the real PostgreSQL schema."""

from __future__ import annotations

import fcntl
from collections.abc import Iterator
from pathlib import Path

import pytest

# A fixed absolute path, not tempfile.gettempdir(): the lock only works when every
# checkout on the machine opens the same file, and TMPDIR is per user session.
DATABASE_LOCK_PATH = Path("/tmp/tamforge-test-database.lock")


@pytest.fixture(scope="session")
def destructive_database_lock(request: pytest.FixtureRequest) -> Iterator[None]:
    """Serialize the suites that drop and recreate the single shared test schema.

    validate_test_database_url pins every checkout on a machine to the same
    127.0.0.1:54329/tamforge_test instance, and these tests migrate that database
    down to base and back up between cases. Two sessions running at once therefore
    delete each other's tables mid-test, which surfaces as unrelated tests failing
    with missing relations, deadlocks or duplicate catalog keys and then passing on
    a rerun. An exclusive file lock makes the second session wait its turn.
    """
    # ponytail: one machine-wide lock; move to per-database locks if a checkout
    # ever gets its own PostgreSQL instance.
    with DATABASE_LOCK_PATH.open("w") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            capture = request.config.pluginmanager.getplugin("capturemanager")
            with capture.global_and_fixture_disabled():
                print(
                    f"\nwaiting for another TAM Forge test session to release "
                    f"{DATABASE_LOCK_PATH}",
                    flush=True,
                )
            fcntl.flock(handle, fcntl.LOCK_EX)
        yield

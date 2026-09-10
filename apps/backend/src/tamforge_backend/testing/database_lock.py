"""Name the exclusive lock that serializes destructive runs against one test database."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.engine import make_url

from ..database import validate_test_database_url

# A fixed absolute directory, not tempfile.gettempdir(): the lock only works when every
# checkout on the machine opens the same file, and TMPDIR is per user session.
LOCK_DIRECTORY = Path("/tmp")


def destructive_database_lock_path(raw_url: str | None) -> Path | None:
    """Return the lock file for this run's database, or None when it needs no lock.

    A checkout that publishes its own container gets its own lock and runs at full
    speed beside the others, while two runs pointed at one database still take turns.
    A missing or rejected URL takes no lock at all: those runs skip or fail before they
    open a connection. Only a URL the guard already accepts reaches a file name, so the
    host, port and database name cannot smuggle a path separator into it.
    """
    if not raw_url:
        return None
    try:
        url = make_url(validate_test_database_url(raw_url))
    except ValueError:
        return None
    return LOCK_DIRECTORY / f"tamforge-test-{url.host}-{url.port}-{url.database}.lock"

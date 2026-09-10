from __future__ import annotations

import pytest
from tamforge_backend.testing.database_lock import destructive_database_lock_path

BASE = "postgresql+asyncpg://tamforge:secret@127.0.0.1"


def test_each_checkout_container_gets_its_own_lock_file() -> None:
    shared = destructive_database_lock_path(f"{BASE}:54329/tamforge_test")
    isolated = destructive_database_lock_path(f"{BASE}:54330/tamforge_test")

    assert shared is not None
    assert isolated is not None
    assert shared.name == "tamforge-test-127.0.0.1-54329-tamforge_test.lock"
    assert isolated.name == "tamforge-test-127.0.0.1-54330-tamforge_test.lock"
    assert isolated.parent == shared.parent


def test_two_runs_against_one_database_take_turns_on_the_same_lock_file() -> None:
    url = f"{BASE}:54329/tamforge_test"

    assert destructive_database_lock_path(url) == destructive_database_lock_path(url)


@pytest.mark.parametrize(
    "raw_url",
    [
        None,
        "",
        "not-a-url",
        "sqlite:///tamforge_test.db",
        f"{BASE}:54329/tamforge",
        f"{BASE}:5432/tamforge_test",
        f"{BASE}/tamforge_test",
        "postgresql+asyncpg://tamforge:secret@prod.invalid:54329/tamforge_test",
        f"{BASE}:54329/tamforge_test?sslmode=require",
    ],
)
def test_a_run_that_cannot_reach_a_test_database_takes_no_lock(raw_url: str | None) -> None:
    assert destructive_database_lock_path(raw_url) is None

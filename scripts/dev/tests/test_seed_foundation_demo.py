from __future__ import annotations

from datetime import date

import pytest
from tamforge_backend.config import APPROVED_GITHUB_USER_ID

from scripts.dev.seed_foundation_demo import load_test_settings, seed_result


def test_demo_seed_refuses_non_test_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TAMFORGE_ENV", "production")
    monkeypatch.setenv(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://tamforge:tamforge@127.0.0.1:54329/tamforge_test",
    )
    with pytest.raises(ValueError, match="requires TAMFORGE_ENV=test"):
        load_test_settings()


def test_demo_seed_refuses_non_test_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TAMFORGE_ENV", "test")
    monkeypatch.setenv(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://tamforge:tamforge@127.0.0.1:54329/tamforge",
    )
    monkeypatch.setenv(
        "TAMFORGE_DATABASE_URL",
        "postgresql+asyncpg://tamforge:tamforge@127.0.0.1:54329/tamforge",
    )
    with pytest.raises(ValueError, match="tamforge_test"):
        load_test_settings()


def test_demo_seed_reports_only_seeded_data() -> None:
    assert seed_result(date(2026, 8, 24)) == {
        "owner_github_id": APPROVED_GITHUB_USER_ID,
        "study_start_date": "2026-08-24",
    }

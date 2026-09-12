"""Worker settings load from the worker env file alone, by alias or by field name."""

from __future__ import annotations

import pytest
from tamforge_backend.workers.settings import WorkerSettings


def test_settings_load_from_the_environment_without_api_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in list(__import__("os").environ):
        if name.startswith("TAMFORGE_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("TAMFORGE_ENV", "production")
    monkeypatch.setenv("TAMFORGE_DATABASE_URL", "postgresql+asyncpg://w:p@127.0.0.1/tamforge")
    monkeypatch.setenv("TAMFORGE_CLAUDE_ENABLED", "false")

    settings = WorkerSettings()

    assert settings.environment == "production"
    assert settings.database_url.get_secret_value().endswith("/tamforge")
    assert settings.claude_enabled is False
    assert settings.coach_model == "claude-opus-5"


def test_settings_accept_field_names_as_keyword_arguments() -> None:
    settings = WorkerSettings(
        environment="test", database_url="postgresql+asyncpg://w:p@127.0.0.1/t", claude_enabled=True
    )

    assert settings.environment == "test"
    assert settings.claude_enabled is True

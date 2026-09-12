"""What a worker process needs from its environment: the database and the Claude gate.

A worker is not the API. It never sees the GitHub OAuth secrets, the session
signing key or the object-store credentials, so it must not be validated as if it
did; its environment file carries only these values.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerSettings(BaseSettings):
    _FIELD_ENV_ALIASES = {
        "environment": "TAMFORGE_ENV",
        "database_url": "TAMFORGE_DATABASE_URL",
        "claude_enabled": "TAMFORGE_CLAUDE_ENABLED",
        "planner_model": "TAMFORGE_PLANNER_MODEL",
        "coach_model": "TAMFORGE_COACH_MODEL",
    }

    model_config = SettingsConfigDict(env_prefix="TAMFORGE_", extra="ignore")

    environment: str = Field(default="development", validation_alias="TAMFORGE_ENV")
    database_url: SecretStr = Field(validation_alias="TAMFORGE_DATABASE_URL")
    claude_enabled: bool = Field(default=False, validation_alias="TAMFORGE_CLAUDE_ENABLED")
    planner_model: str = Field(
        default="claude-fable-5-1", validation_alias="TAMFORGE_PLANNER_MODEL"
    )
    coach_model: str = Field(default="claude-opus-5", validation_alias="TAMFORGE_COACH_MODEL")

    def __init__(self, **values: Any) -> None:
        mapped = dict(values)
        for field_name, env_alias in self._FIELD_ENV_ALIASES.items():
            if field_name in mapped and env_alias not in mapped:
                mapped[env_alias] = mapped.pop(field_name)
        super().__init__(**mapped)


__all__ = ["WorkerSettings"]

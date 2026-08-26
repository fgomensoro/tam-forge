"""Validated, secret-safe runtime configuration."""

from __future__ import annotations

import re
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

APPROVED_GITHUB_USER_ID = 102269369
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
_BUCKET_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")


class Settings(BaseSettings):
    """One immutable settings snapshot for one application lifespan."""

    model_config = SettingsConfigDict(
        env_prefix="TAMFORGE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
        case_sensitive=False,
    )

    environment: Literal["development", "test", "production"] = Field(
        default="development",
        validation_alias=AliasChoices("environment", "TAMFORGE_ENV"),
    )
    database_url: SecretStr = SecretStr(
        "postgresql+asyncpg://tamforge:tamforge@127.0.0.1:54329/tamforge"
    )
    object_store_endpoint: str = "http://127.0.0.1:9000"
    object_store_bucket: str = "tam-forge-local"
    object_store_access_key: SecretStr = SecretStr("")
    object_store_secret_key: SecretStr = SecretStr("")
    github_client_id: str = ""
    github_client_secret: SecretStr = SecretStr("")
    session_signing_secret: SecretStr = SecretStr("")
    github_user_id: int | None = None
    cors_origins: list[str] = Field(default_factory=list)
    secure_cookies: bool | None = None

    @model_validator(mode="after")
    def validate_runtime_policy(self) -> Self:
        secure_cookies = self.secure_cookies
        if secure_cookies is None:
            object.__setattr__(self, "secure_cookies", self.environment != "test")
        elif self.environment != "test" and not secure_cookies:
            raise ValueError("secure cookies cannot be disabled outside the test environment")

        if self.github_user_id not in (None, APPROVED_GITHUB_USER_ID):
            raise ValueError("GitHub user ID does not match the approved immutable owner")

        if self.environment == "production":
            self._validate_production()
        return self

    def _validate_production(self) -> None:
        required_text = {
            "object store endpoint": self.object_store_endpoint,
            "object store bucket": self.object_store_bucket,
            "GitHub client ID": self.github_client_id,
        }
        for label, value in required_text.items():
            if not value.strip():
                raise ValueError(f"production requires {label}")

        required_secrets = {
            "database URL": self.database_url,
            "object store access key": self.object_store_access_key,
            "object store secret key": self.object_store_secret_key,
            "GitHub client secret": self.github_client_secret,
            "session signing secret": self.session_signing_secret,
        }
        for label, secret_value in required_secrets.items():
            if not secret_value.get_secret_value().strip():
                raise ValueError(f"production requires {label}")

        if self.github_user_id != APPROVED_GITHUB_USER_ID:
            raise ValueError("production requires the approved immutable GitHub user ID")
        if len(self.session_signing_secret.get_secret_value()) < 32:
            raise ValueError("production session signing secret is too short")

        self._validate_production_database_url()
        self._validate_production_object_store()

    def _validate_production_database_url(self) -> None:
        try:
            parsed = urlsplit(self.database_url.get_secret_value())
            port = parsed.port
        except ValueError as exc:
            raise ValueError("production database URL is malformed") from exc
        if (
            parsed.scheme != "postgresql+asyncpg"
            or not parsed.hostname
            or parsed.hostname.lower() in _LOCAL_HOSTS
            or not parsed.username
            or not parsed.password
            or not parsed.path.lstrip("/")
            or port is None
        ):
            raise ValueError("production requires a nonlocal PostgreSQL async database URL")

    def _validate_production_object_store(self) -> None:
        try:
            parsed = urlsplit(self.object_store_endpoint)
            parsed.port
        except ValueError as exc:
            raise ValueError("production object store endpoint is malformed") from exc
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.hostname.lower() in _LOCAL_HOSTS
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError("production requires a secure nonlocal object store endpoint")
        if not _BUCKET_PATTERN.fullmatch(self.object_store_bucket):
            raise ValueError("production object store bucket name is invalid")
        if self.object_store_bucket.endswith("-local"):
            raise ValueError("production object store bucket cannot use a local placeholder")


def get_settings() -> Settings:
    """Build a fresh settings snapshot; callers own its lifetime."""
    return Settings()

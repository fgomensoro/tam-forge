"""Validated, secret-safe runtime configuration."""

from __future__ import annotations

import base64
import binascii
import re
from typing import Any, ClassVar, Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

APPROVED_GITHUB_USER_ID = 102269369
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
_BUCKET_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
_SESSION_SECRET_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
_SESSION_SECRET_PLACEHOLDERS = (
    "changeme",
    "example",
    "placeholder",
    "tamforge",
    "password",
    "secret",
)


class Settings(BaseSettings):
    """One immutable settings snapshot for one application lifespan."""

    _FIELD_ENV_ALIASES: ClassVar[dict[str, str]] = {
        "environment": "TAMFORGE_ENV",
        "database_url": "TAMFORGE_DATABASE_URL",
        "object_store_endpoint": "TAMFORGE_OBJECT_STORE_ENDPOINT",
        "object_store_bucket": "TAMFORGE_OBJECT_STORE_BUCKET",
        "object_store_region": "TAMFORGE_OBJECT_STORE_REGION",
        "object_store_access_key": "TAMFORGE_OBJECT_STORE_ACCESS_KEY",
        "object_store_secret_key": "TAMFORGE_OBJECT_STORE_SECRET_KEY",
        "object_store_max_upload_bytes": "TAMFORGE_OBJECT_STORE_MAX_UPLOAD_BYTES",
        "object_store_memory_spool_bytes": "TAMFORGE_OBJECT_STORE_MEMORY_SPOOL_BYTES",
        "github_client_id": "TAMFORGE_GITHUB_CLIENT_ID",
        "github_client_secret": "TAMFORGE_GITHUB_CLIENT_SECRET",
        "session_signing_secret": "TAMFORGE_SESSION_SIGNING_SECRET",
        "github_user_id": "TAMFORGE_GITHUB_USER_ID",
        "github_callback_url": "TAMFORGE_GITHUB_CALLBACK_URL",
        "cors_origins": "TAMFORGE_CORS_ORIGINS",
        "secure_cookies": "TAMFORGE_SECURE_COOKIES",
        "session_ttl_seconds": "TAMFORGE_SESSION_TTL_SECONDS",
        "oauth_state_ttl_seconds": "TAMFORGE_OAUTH_STATE_TTL_SECONDS",
    }

    model_config = SettingsConfigDict(
        env_prefix="TAMFORGE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
        case_sensitive=True,
        populate_by_name=False,
    )

    environment: Literal["development", "test", "production"] = Field(
        default="development",
        validation_alias="TAMFORGE_ENV",
    )
    database_url: SecretStr = Field(
        default=SecretStr(
            "postgresql+asyncpg://tamforge:tamforge@127.0.0.1:54329/tamforge"
        ),
        validation_alias="TAMFORGE_DATABASE_URL",
    )
    object_store_endpoint: str = Field(
        default="http://127.0.0.1:9000",
        validation_alias="TAMFORGE_OBJECT_STORE_ENDPOINT",
    )
    object_store_bucket: str = Field(
        default="tam-forge-local",
        validation_alias="TAMFORGE_OBJECT_STORE_BUCKET",
    )
    object_store_region: str = Field(
        default="us-east-1",
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9-]+$",
        validation_alias="TAMFORGE_OBJECT_STORE_REGION",
    )
    object_store_access_key: SecretStr = Field(
        default=SecretStr(""),
        validation_alias="TAMFORGE_OBJECT_STORE_ACCESS_KEY",
    )
    object_store_secret_key: SecretStr = Field(
        default=SecretStr(""),
        validation_alias="TAMFORGE_OBJECT_STORE_SECRET_KEY",
    )
    object_store_max_upload_bytes: int = Field(
        default=1024 * 1024 * 1024,
        ge=1,
        le=5 * 1024 * 1024 * 1024,
        validation_alias="TAMFORGE_OBJECT_STORE_MAX_UPLOAD_BYTES",
    )
    object_store_memory_spool_bytes: int = Field(
        default=1024 * 1024,
        ge=1,
        le=64 * 1024 * 1024,
        validation_alias="TAMFORGE_OBJECT_STORE_MEMORY_SPOOL_BYTES",
    )
    github_client_id: str = Field(default="", validation_alias="TAMFORGE_GITHUB_CLIENT_ID")
    github_client_secret: SecretStr = Field(
        default=SecretStr(""),
        validation_alias="TAMFORGE_GITHUB_CLIENT_SECRET",
    )
    session_signing_secret: SecretStr = Field(
        default=SecretStr(""),
        validation_alias="TAMFORGE_SESSION_SIGNING_SECRET",
    )
    github_user_id: int | None = Field(
        default=None,
        validation_alias="TAMFORGE_GITHUB_USER_ID",
    )
    github_callback_url: str = Field(
        default="http://127.0.0.1:8000/api/v1/auth/callback",
        validation_alias="TAMFORGE_GITHUB_CALLBACK_URL",
    )
    cors_origins: list[str] = Field(
        default_factory=list,
        validation_alias="TAMFORGE_CORS_ORIGINS",
    )
    secure_cookies: bool | None = Field(
        default=None,
        validation_alias="TAMFORGE_SECURE_COOKIES",
    )
    session_ttl_seconds: int = Field(
        default=43_200,
        ge=300,
        le=86_400,
        validation_alias="TAMFORGE_SESSION_TTL_SECONDS",
    )
    oauth_state_ttl_seconds: int = Field(
        default=300,
        ge=60,
        le=600,
        validation_alias="TAMFORGE_OAUTH_STATE_TTL_SECONDS",
    )

    def __init__(self, **values: Any) -> None:
        """Allow typed field-name injection without creating unprefixed env aliases."""
        mapped = dict(values)
        for field_name, env_alias in self._FIELD_ENV_ALIASES.items():
            if field_name not in mapped:
                continue
            if env_alias in mapped:
                raise TypeError(f"provide only {field_name}, not both constructor aliases")
            mapped[env_alias] = mapped.pop(field_name)
        super().__init__(**mapped)

    @model_validator(mode="after")
    def validate_runtime_policy(self) -> Self:
        secure_cookies = self.secure_cookies
        if secure_cookies is None:
            object.__setattr__(self, "secure_cookies", self.environment != "test")
        elif self.environment != "test" and not secure_cookies:
            raise ValueError("secure cookies cannot be disabled outside the test environment")

        if self.github_user_id not in (None, APPROVED_GITHUB_USER_ID):
            raise ValueError("GitHub user ID does not match the approved immutable owner")

        self._validate_cors_origins()
        self._validate_github_callback_url()
        if self.object_store_memory_spool_bytes > self.object_store_max_upload_bytes:
            raise ValueError("object-store memory spool cannot exceed upload limit")

        if self.environment == "production":
            self._validate_production()
        return self

    def _validate_production(self) -> None:
        if not self.cors_origins:
            raise ValueError("production requires at least one exact CORS origin")
        required_text = {
            "object store endpoint": self.object_store_endpoint,
            "object store bucket": self.object_store_bucket,
            "object store region": self.object_store_region,
            "GitHub client ID": self.github_client_id,
            "GitHub callback URL": self.github_callback_url,
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
        self._validate_production_session_secret()

        self._validate_production_database_url()
        self._validate_production_object_store()

    def _validate_cors_origins(self) -> None:
        for origin in self.cors_origins:
            if origin == "*" or not origin or len(origin) > 2048:
                raise ValueError("CORS origins must be exact web origins")
            try:
                parsed = urlsplit(origin)
                port = parsed.port
            except ValueError as exc:
                raise ValueError("CORS origins must be exact web origins") from exc
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path
                or parsed.query
                or parsed.fragment
                or "*" in parsed.hostname
            ):
                raise ValueError("CORS origins must be exact web origins")
            host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
            expected = f"{parsed.scheme}://{host}"
            if port is not None:
                expected = f"{expected}:{port}"
            if origin != expected:
                raise ValueError("CORS origins must be exact web origins")
            if self.environment == "production" and parsed.scheme != "https":
                raise ValueError("production CORS origins must use HTTPS")

    def _validate_github_callback_url(self) -> None:
        try:
            parsed = urlsplit(self.github_callback_url)
            parsed.port
        except ValueError as exc:
            raise ValueError("GitHub callback URL is invalid") from exc
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path != "/api/v1/auth/callback"
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("GitHub callback URL is invalid")
        if self.environment == "production" and (
            parsed.scheme != "https" or parsed.hostname.lower() in _LOCAL_HOSTS
        ):
            raise ValueError("production GitHub callback URL must use public HTTPS")

    def _validate_production_session_secret(self) -> None:
        token = self.session_signing_secret.get_secret_value()
        lowered = token.lower()
        if (
            not _SESSION_SECRET_PATTERN.fullmatch(token)
            or any(placeholder in lowered for placeholder in _SESSION_SECRET_PLACEHOLDERS)
        ):
            raise ValueError("production session signing secret must use token_urlsafe(32)")

        padding = "=" * (-len(token) % 4)
        try:
            decoded = base64.b64decode(
                (token + padding).encode("ascii"),
                altchars=b"-_",
                validate=True,
            )
        except (UnicodeEncodeError, binascii.Error, ValueError):
            raise ValueError(
                "production session signing secret must use token_urlsafe(32)"
            ) from None

        canonical = base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii")
        midpoint = len(decoded) // 2
        repeated_half = len(decoded) % 2 == 0 and decoded[:midpoint] == decoded[midpoint:]
        if len(decoded) < 32 or len(set(decoded)) < 16 or repeated_half or canonical != token:
            raise ValueError("production session signing secret must use token_urlsafe(32)")

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

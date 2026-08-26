from __future__ import annotations

import base64
import secrets
from collections.abc import Iterator
from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError
from tamforge_backend.config import Settings

VALID_SESSION_SECRET = secrets.token_urlsafe(32)
PRODUCTION_ENV = {
    "TAMFORGE_ENV": "production",
    "TAMFORGE_DATABASE_URL": (
        "postgresql+asyncpg://tamforge:database-secret@db.internal:5432/tamforge"
    ),
    "TAMFORGE_OBJECT_STORE_ENDPOINT": "https://objects.example.test",
    "TAMFORGE_OBJECT_STORE_BUCKET": "tam-forge",
    "TAMFORGE_OBJECT_STORE_REGION": "eu-central-1",
    "TAMFORGE_OBJECT_STORE_ACCESS_KEY": "object-access-secret",
    "TAMFORGE_OBJECT_STORE_SECRET_KEY": "object-secret-value",
    "TAMFORGE_GITHUB_CLIENT_ID": "github-client-id",
    "TAMFORGE_GITHUB_CLIENT_SECRET": "github-client-secret",
    "TAMFORGE_SESSION_SIGNING_SECRET": VALID_SESSION_SECRET,
    "TAMFORGE_GITHUB_USER_ID": "102269369",
    "TAMFORGE_GITHUB_CALLBACK_URL": "https://tam.example.test/api/v1/auth/callback",
    "TAMFORGE_CORS_ORIGINS": '["https://tam.example.test"]',
}


@pytest.fixture(autouse=True)
def isolate_tamforge_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[None]:
    monkeypatch.chdir(tmp_path)
    for name in tuple(PRODUCTION_ENV) + (
        "TAM_FORGE_ENV",
        "ENVIRONMENT",
        "environment",
        "tamforge_env",
        "Tamforge_ENV",
        "TAMFORGE_env",
        "TAMFORGE_environment",
        "TAMFORGE_CORS_ORIGINS",
        "TAMFORGE_GITHUB_CALLBACK_URL",
        "TAMFORGE_SECURE_COOKIES",
    ):
        monkeypatch.delenv(name, raising=False)
    yield


def set_production_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in PRODUCTION_ENV.items():
        monkeypatch.setenv(name, value)


@pytest.mark.parametrize(
    "missing_name",
    [
        "TAMFORGE_DATABASE_URL",
        "TAMFORGE_OBJECT_STORE_ENDPOINT",
        "TAMFORGE_OBJECT_STORE_BUCKET",
        "TAMFORGE_OBJECT_STORE_ACCESS_KEY",
        "TAMFORGE_OBJECT_STORE_SECRET_KEY",
        "TAMFORGE_GITHUB_CLIENT_ID",
        "TAMFORGE_GITHUB_CLIENT_SECRET",
        "TAMFORGE_SESSION_SIGNING_SECRET",
        "TAMFORGE_GITHUB_USER_ID",
        "TAMFORGE_GITHUB_CALLBACK_URL",
    ],
)
@pytest.mark.parametrize("replacement", [None, "", "   "])
def test_production_rejects_missing_or_blank_required_values(
    monkeypatch: pytest.MonkeyPatch,
    missing_name: str,
    replacement: str | None,
) -> None:
    set_production_environment(monkeypatch)
    if replacement is None:
        monkeypatch.delenv(missing_name)
    else:
        monkeypatch.setenv(missing_name, replacement)

    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.parametrize("owner_id", ["102269368", "not-a-number"])
def test_production_rejects_wrong_or_nonnumeric_owner_id(
    monkeypatch: pytest.MonkeyPatch,
    owner_id: str,
) -> None:
    set_production_environment(monkeypatch)
    monkeypatch.setenv("TAMFORGE_GITHUB_USER_ID", owner_id)

    with pytest.raises(ValidationError):
        Settings()


def test_production_requires_the_approved_immutable_owner_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_production_environment(monkeypatch)

    settings = Settings()

    assert settings.github_user_id == 102269369


def test_sensitive_settings_are_secret_str_and_never_appear_in_repr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_production_environment(monkeypatch)
    settings = Settings()

    sensitive_values = {
        "database-secret",
        "object-access-secret",
        "object-secret-value",
        "github-client-secret",
        VALID_SESSION_SECRET,
    }
    secret_fields = (
        settings.database_url,
        settings.object_store_access_key,
        settings.object_store_secret_key,
        settings.github_client_secret,
        settings.session_signing_secret,
    )

    assert all(isinstance(value, SecretStr) for value in secret_fields)
    rendered = repr(settings)
    assert "**********" in rendered
    assert all(secret not in rendered for secret in sensitive_values)


def test_object_store_resource_limits_are_bounded_and_consistent() -> None:
    settings = Settings(
        environment="test",
        object_store_max_upload_bytes=1024,
        object_store_memory_spool_bytes=512,
        _env_file=None,
    )

    assert settings.object_store_region == "us-east-1"
    assert settings.object_store_max_upload_bytes == 1024
    assert settings.object_store_memory_spool_bytes == 512

    with pytest.raises(ValidationError):
        Settings(
            environment="test",
            object_store_max_upload_bytes=512,
            object_store_memory_spool_bytes=1024,
            _env_file=None,
        )

    with pytest.raises(ValidationError):
        Settings(
            environment="test",
            object_store_memory_spool_bytes=0,
            _env_file=None,
        )


def test_invalid_secret_input_is_redacted_from_validation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_production_environment(monkeypatch)
    monkeypatch.setenv("TAMFORGE_DATABASE_URL", "do-not-leak-this-database-secret")

    with pytest.raises(ValidationError) as exc_info:
        Settings()

    assert "do-not-leak-this-database-secret" not in str(exc_info.value)


def test_cors_denies_by_default_and_cookie_security_depends_only_on_test_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    development = Settings()
    monkeypatch.setenv("TAMFORGE_ENV", "test")
    test = Settings()

    assert development.cors_origins == []
    assert development.secure_cookies is True
    assert test.cors_origins == []
    assert test.secure_cookies is False


def test_production_rejects_insecure_cookie_override(monkeypatch: pytest.MonkeyPatch) -> None:
    set_production_environment(monkeypatch)
    monkeypatch.setenv("TAMFORGE_SECURE_COOKIES", "false")

    with pytest.raises(ValidationError):
        Settings()


def test_production_rejects_wildcard_cors(monkeypatch: pytest.MonkeyPatch) -> None:
    set_production_environment(monkeypatch)
    monkeypatch.setenv("TAMFORGE_CORS_ORIGINS", '["*"]')

    with pytest.raises(ValidationError):
        Settings()


def test_production_requires_at_least_one_cors_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_production_environment(monkeypatch)
    monkeypatch.delenv("TAMFORGE_CORS_ORIGINS")

    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.parametrize(
    "origin",
    [
        "https://tam.example.test/path",
        "https://user@tam.example.test",
        "https://*.example.test",
        "null",
    ],
)
def test_cors_origins_must_be_exact_web_origins(origin: str) -> None:
    with pytest.raises(ValidationError):
        Settings(cors_origins=[origin], _env_file=None)


def test_exact_env_prefix_ignores_bootstrap_legacy_namespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TAM_FORGE_ENV", "production")

    settings = Settings()

    assert settings.environment == "development"


@pytest.mark.parametrize(
    "name",
    [
        "ENVIRONMENT",
        "environment",
        "tamforge_env",
        "Tamforge_ENV",
        "TAMFORGE_env",
        "TAMFORGE_environment",
    ],
)
def test_environment_ignores_unprefixed_and_wrong_case_variants(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
) -> None:
    monkeypatch.setenv(name, "test")

    settings = Settings()

    assert settings.environment == "development"
    assert settings.secure_cookies is True


def test_ambient_generic_environment_cannot_downgrade_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_production_environment(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "test")

    settings = Settings()

    assert settings.environment == "production"
    assert settings.secure_cookies is True


def test_field_name_constructor_injection_remains_available() -> None:
    settings = Settings(environment="test", _env_file=None)

    assert settings.environment == "test"
    assert settings.secure_cookies is False


def test_explicit_dotenv_source_uses_only_canonical_environment_name(tmp_path: Path) -> None:
    env_file = tmp_path / "settings.env"
    env_file.write_text("TAMFORGE_ENV=test\nENVIRONMENT=production\n", encoding="utf-8")

    settings = Settings(_env_file=env_file)

    assert settings.environment == "test"
    assert settings.secure_cookies is False


def test_settings_instances_are_isolated_and_not_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    first = Settings()
    monkeypatch.setenv("TAMFORGE_ENV", "test")
    second = Settings()

    assert first is not second
    assert first.environment == "development"
    assert second.environment == "test"


@pytest.mark.parametrize(
    ("name", "value"),
    [
        (
            "TAMFORGE_DATABASE_URL",
            "postgresql+asyncpg://tamforge:secret@127.0.0.1:54329/tamforge",
        ),
        ("TAMFORGE_OBJECT_STORE_ENDPOINT", "http://objects.example.test"),
    ],
)
def test_production_rejects_local_or_insecure_endpoints(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
) -> None:
    set_production_environment(monkeypatch)
    monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.parametrize(
    "weak_secret",
    [
        "x" * 32,
        "x" * 43,
        "a" * 41,
        "changeme-please-use-a-real-secret-value",
        "tamforge-example-session-signing-secret",
        "not_base64url!not_base64url!not_base64url!",
        base64.urlsafe_b64encode(b"A" * 32).rstrip(b"=").decode("ascii"),
        base64.urlsafe_b64encode(b"0123456789abcdef" * 2).rstrip(b"=").decode("ascii"),
        base64.urlsafe_b64encode(secrets.token_bytes(31)).rstrip(b"=").decode("ascii"),
    ],
)
def test_production_rejects_weak_or_malformed_session_signing_secret(
    monkeypatch: pytest.MonkeyPatch,
    weak_secret: str,
) -> None:
    set_production_environment(monkeypatch)
    monkeypatch.setenv("TAMFORGE_SESSION_SIGNING_SECRET", weak_secret)

    with pytest.raises(ValidationError) as exc_info:
        Settings()

    assert weak_secret not in str(exc_info.value)


def test_production_accepts_token_urlsafe_32_session_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_production_environment(monkeypatch)
    generated = secrets.token_urlsafe(32)
    monkeypatch.setenv("TAMFORGE_SESSION_SIGNING_SECRET", generated)

    settings = Settings()

    assert settings.session_signing_secret.get_secret_value() == generated
    assert generated not in repr(settings)

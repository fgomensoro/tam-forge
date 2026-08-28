from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from tamforge_backend.config import Settings
from tamforge_backend.main import create_app


def _settings() -> Settings:
    return Settings(
        environment="test",
        github_user_id=102269369,
        github_client_id="client-id",
        github_client_secret="provider-secret",
        session_signing_secret="state-signing-secret-with-enough-entropy",
        _env_file=None,
    )


def test_native_validation_errors_never_echo_submitted_credentials() -> None:
    marker = "refresh-secret-marker-that-must-never-enter-errors"

    with TestClient(create_app(_settings())) as client:
        response = client.post(
            "/api/v1/auth/native/refresh",
            json={"refresh_token": marker},
        )

    assert response.status_code == 422
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-type"].startswith("application/problem+json")
    assert marker not in response.text
    assert response.json()["code"] == "invalid_native_auth_request"


def test_native_secrets_are_body_only_and_bearer_contract_is_explicit() -> None:
    schema = create_app(_settings()).openapi()
    secret_names = {"code_verifier", "refresh_token", "access_token"}

    for path, path_item in schema["paths"].items():
        if not path.startswith("/api/v1/auth/native/"):
            continue
        for operation in path_item.values():
            if not isinstance(operation, dict):
                continue
            parameters = operation.get("parameters", [])
            assert not any(parameter.get("name") in secret_names for parameter in parameters)

    session_parameters = schema["paths"]["/api/v1/auth/native/session"]["get"][
        "parameters"
    ]
    assert any(
        parameter["name"] == "Authorization" and parameter["in"] == "header"
        for parameter in session_parameters
    )


def test_native_client_persists_refresh_credentials_only_as_device_keychain_items() -> None:
    source = Path(
        "apps/macos/TAMForge/Core/Auth/KeychainCredentialStore.swift"
    ).read_text(encoding="utf-8")

    assert "kSecClassGenericPassword" in source
    assert "kSecAttrAccessibleWhenUnlockedThisDeviceOnly" in source
    assert "kSecAttrSynchronizable as String: false" in source
    assert "UserDefaults" not in source
    assert "write(to:" not in source

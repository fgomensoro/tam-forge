from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from tamforge_backend.auth.schemas import (
    AuthenticatedOwner,
    IssuedNativeCredentials,
    OAuthStart,
)
from tamforge_backend.config import Settings
from tamforge_backend.main import create_app

NOW = datetime(2026, 8, 28, 12, tzinfo=UTC)


class StubNativeAuthService:
    def __init__(self) -> None:
        self.revocations = 0
        self.bearer_calls = 0

    async def start_native_login(self, *, pkce_challenge: str, redirect_uri: str) -> OAuthStart:
        assert pkce_challenge == "c" * 43
        assert redirect_uri == "https://app.example.test/api/v1/auth/callback"
        return OAuthStart(
            state="n" * 43,
            authorization_url=f"https://github.example/authorize?state={'n' * 43}",
        )

    async def complete_native_login(self, **values: object) -> str:
        assert values == {
            "code": "provider-secret-code",
            "state": "n" * 43,
            "redirect_uri": "https://app.example.test/api/v1/auth/callback",
        }
        return "e" * 43

    async def exchange_native_code(self, **values: object) -> IssuedNativeCredentials:
        assert values == {"code": "e" * 43, "code_verifier": "v" * 43}
        return self._credentials("a", "r")

    async def refresh_native_session(self, refresh_token: str) -> IssuedNativeCredentials:
        assert refresh_token == "r" * 43
        return self._credentials("b", "s")

    async def revoke_native_session(self, refresh_token: str) -> None:
        assert refresh_token == "s" * 43
        self.revocations += 1

    async def authenticate_bearer(self, token: str) -> AuthenticatedOwner:
        assert token == "b" * 43
        self.bearer_calls += 1
        return AuthenticatedOwner(
            owner_id=7,
            github_user_id=102269369,
            github_login="fgomensoro",
            session_id=11,
            csrf_hash=None,
            expires_at=NOW + timedelta(minutes=15),
            authentication_method="bearer",
        )

    async def authenticate(self, token: str | None) -> AuthenticatedOwner:
        assert token == "cookie-token"
        return AuthenticatedOwner(
            owner_id=7,
            github_user_id=102269369,
            github_login="fgomensoro",
            session_id=10,
            csrf_hash=b"c" * 32,
            expires_at=NOW + timedelta(hours=12),
        )

    def verify_csrf(self, owner: AuthenticatedOwner, token: str | None) -> None:
        assert owner.authentication_method == "cookie"
        assert token == "csrf-token"

    @staticmethod
    def _credentials(access: str, refresh: str) -> IssuedNativeCredentials:
        return IssuedNativeCredentials(
            access_token=access * 43,
            refresh_token=refresh * 43,
            access_expires_in=900,
            github_login="fgomensoro",
        )


def make_client() -> tuple[TestClient, StubNativeAuthService]:
    from tamforge_backend.auth.dependencies import get_auth_service

    settings = Settings(
        environment="test",
        github_user_id=102269369,
        github_client_id="client-id",
        github_client_secret="client-secret",
        session_signing_secret="state-signing-secret-with-enough-entropy",
        github_callback_url="https://app.example.test/api/v1/auth/callback",
        cors_origins=["https://app.example.test"],
        secure_cookies=False,
        _env_file=None,
    )
    service = StubNativeAuthService()
    app = create_app(settings)
    app.dependency_overrides[get_auth_service] = lambda: service

    return TestClient(app), service


def test_native_oauth_callback_and_rotation_contract() -> None:
    client, service = make_client()
    with client:
        started = client.post("/api/v1/auth/native/start", json={"code_challenge": "c" * 43})
        callback = client.get(
            "/api/v1/auth/callback",
            params={"code": "provider-secret-code", "state": "n" * 43},
            follow_redirects=False,
        )
        exchanged = client.post(
            "/api/v1/auth/native/exchange",
            json={"code": "e" * 43, "code_verifier": "v" * 43},
        )
        refreshed = client.post(
            "/api/v1/auth/native/refresh", json={"refresh_token": "r" * 43}
        )
        revoked = client.post(
            "/api/v1/auth/native/revoke", json={"refresh_token": "s" * 43}
        )

    assert started.status_code == 200
    assert started.headers["cache-control"] == "no-store"
    assert started.json()["authorization_url"].startswith("https://github.example/")
    assert callback.status_code == 303
    callback_url = urlsplit(callback.headers["location"])
    assert (callback_url.scheme, callback_url.netloc, callback_url.path) == (
        "tamforge",
        "auth",
        "/callback",
    )
    assert parse_qs(callback_url.query) == {"code": ["e" * 43]}
    assert "provider-secret-code" not in callback.headers["location"]
    assert exchanged.json() == {
        "access_token": "a" * 43,
        "refresh_token": "r" * 43,
        "token_type": "bearer",
        "expires_in": 900,
        "github_login": "fgomensoro",
    }
    assert exchanged.headers["cache-control"] == "no-store"
    assert refreshed.json()["refresh_token"] == "s" * 43
    assert revoked.status_code == 204
    assert revoked.headers["cache-control"] == "no-store"
    assert service.revocations == 1


def test_bearer_auth_is_unambiguous_and_skips_only_browser_csrf() -> None:
    client, service = make_client()
    with client:
        native_session = client.get(
            "/api/v1/auth/native/session",
            headers={"Authorization": f"Bearer {'b' * 43}"},
        )
        client.cookies.set("tamforge_session", "cookie-token", path="/api/v1")
        mixed = client.get(
            "/api/v1/auth/native/session",
            headers={"Authorization": f"Bearer {'b' * 43}"},
        )

    assert native_session.status_code == 200
    assert native_session.json() == {"github_login": "fgomensoro"}
    assert mixed.status_code == 401
    assert service.bearer_calls == 1


@pytest.mark.anyio
async def test_mutation_guard_skips_csrf_only_for_validated_bearer_owner() -> None:
    from tamforge_backend.auth.dependencies import OriginRejected, require_csrf_owner

    service = StubNativeAuthService()
    settings = Settings(
        environment="test",
        cors_origins=["https://app.example.test"],
        _env_file=None,
    )
    app = SimpleNamespace(state=SimpleNamespace(settings=settings))
    request = Request({"type": "http", "headers": [], "app": app})
    bearer = await service.authenticate_bearer("b" * 43)
    accepted = await require_csrf_owner(request, service, bearer, None)

    assert accepted.authentication_method == "bearer"

    cookie = await service.authenticate("cookie-token")
    with pytest.raises(OriginRejected):
        await require_csrf_owner(request, service, cookie, None)

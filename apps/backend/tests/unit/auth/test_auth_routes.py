"""Offline auth routes; database-backed coverage lives under integration/auth."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from tamforge_backend.auth.schemas import (
    AuthenticatedOwner,
    IssuedSession,
    OAuthStart,
    PersistedSession,
)
from tamforge_backend.config import Settings
from tamforge_backend.main import create_app

NOW = datetime(2026, 8, 26, 12, tzinfo=UTC)


class StubAuthService:
    def __init__(self) -> None:
        self.logout_calls = 0

    def start_login(self, *, redirect_uri: str) -> OAuthStart:
        assert redirect_uri == "https://app.example.test/api/v1/auth/callback"
        return OAuthStart(
            state="signed-oauth-state",
            authorization_url="https://github.com/login/oauth/authorize?state=signed-oauth-state",
        )

    async def complete_login(self, **values: object) -> IssuedSession:
        from tamforge_backend.auth.service import Unauthenticated

        assert values["state"] == "signed-oauth-state"
        assert values["state_cookie"] == "signed-oauth-state"
        if len(str(values["code"])) > 512:
            raise Unauthenticated("must-not-be-public")
        persisted = PersistedSession(
            session_id=1,
            owner_id=2,
            github_user_id=102269369,
            github_login="fgomensoro",
            token_hash=b"t" * 32,
            csrf_hash=b"c" * 32,
            created_at=NOW,
            expires_at=NOW + timedelta(hours=12),
            revoked_at=None,
        )
        return IssuedSession(
            raw_session_token="s" * 43,
            raw_csrf_token="c" * 43,
            persisted_session=persisted,
        )

    async def authenticate(self, raw_session_token: str | None) -> AuthenticatedOwner:
        assert raw_session_token == "s" * 43
        return AuthenticatedOwner(
            owner_id=2,
            github_user_id=102269369,
            github_login="fgomensoro",
            session_id=1,
            csrf_hash=b"c" * 32,
            expires_at=NOW + timedelta(hours=12),
        )

    async def expose_csrf(
        self,
        owner: AuthenticatedOwner,
        raw_csrf_token: str | None,
    ) -> str:
        assert owner.owner_id == 2
        assert raw_csrf_token == "c" * 43
        return "c" * 43

    async def logout(
        self,
        raw_session_token: str | None,
        raw_csrf_token: str | None,
    ) -> None:
        assert raw_session_token == "s" * 43
        assert raw_csrf_token == "c" * 43
        self.logout_calls += 1


def make_client(*, secure_cookies: bool = False) -> tuple[TestClient, StubAuthService]:
    from tamforge_backend.auth.dependencies import get_auth_service

    settings = Settings(
        environment="test" if not secure_cookies else "development",
        github_user_id=102269369,
        github_client_id="client-id",
        github_client_secret="client-secret",
        session_signing_secret="state-signing-secret-with-enough-entropy",
        github_callback_url="https://app.example.test/api/v1/auth/callback",
        cors_origins=["https://app.example.test"],
        secure_cookies=secure_cookies,
        _env_file=None,
    )
    service = StubAuthService()
    app = create_app(settings)
    app.dependency_overrides[get_auth_service] = lambda: service
    return TestClient(app), service


def test_login_redirects_with_short_lived_httponly_host_only_state_cookie() -> None:
    client, _ = make_client()
    with client:
        response = client.get("/api/v1/auth/login", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"].startswith("https://github.com/login/oauth/authorize")
    cookie = response.headers["set-cookie"]
    assert "tamforge_oauth_state=signed-oauth-state" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Path=/api/v1/auth/callback" in cookie
    assert "Max-Age=300" in cookie
    assert "Domain=" not in cookie
    assert response.headers["referrer-policy"] == "no-referrer"


def test_callback_sets_only_opaque_secure_httponly_host_only_cookies() -> None:
    client, _ = make_client(secure_cookies=True)
    with client:
        client.cookies.set(
            "tamforge_oauth_state",
            "signed-oauth-state",
            path="/api/v1/auth/callback",
        )
        response = client.get(
            "/api/v1/auth/callback?code=code&state=signed-oauth-state",
            follow_redirects=False,
        )

    assert response.status_code == 303
    cookies = response.headers.get_list("set-cookie")
    session_cookie = next(value for value in cookies if value.startswith("tamforge_session="))
    csrf_cookie = next(value for value in cookies if value.startswith("tamforge_csrf="))
    for cookie in (session_cookie, csrf_cookie):
        assert "HttpOnly" in cookie
        assert "Secure" in cookie
        assert "SameSite=lax" in cookie
        assert "Domain=" not in cookie
    assert "Path=/api/v1" in session_cookie
    assert "Path=/api/v1/auth/session" in csrf_cookie
    assert "access_token" not in "\n".join(cookies)
    assert response.headers["referrer-policy"] == "no-referrer"


def test_session_returns_display_and_csrf_without_owner_id() -> None:
    client, _ = make_client()
    with client:
        client.cookies.set("tamforge_session", "s" * 43, path="/api/v1")
        client.cookies.set("tamforge_csrf", "c" * 43, path="/api/v1/auth/session")
        response = client.get("/api/v1/auth/session")

    assert response.status_code == 200
    assert response.json() == {"github_login": "fgomensoro", "csrf_token": "c" * 43}
    assert "owner_id" not in response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"


def test_callback_validation_never_echoes_oauth_code_or_state() -> None:
    client, _ = make_client()
    oauth_code = "secret-oauth-code-" + "x" * 512
    with client:
        client.cookies.set(
            "tamforge_oauth_state",
            "signed-oauth-state",
            path="/api/v1/auth/callback",
        )
        response = client.get(
            "/api/v1/auth/callback",
            params={"code": oauth_code, "state": "signed-oauth-state"},
            follow_redirects=False,
        )

    assert response.status_code == 401
    assert oauth_code not in response.text
    assert "signed-oauth-state" not in response.text
    assert response.json()["code"] == "unauthenticated"
    assert response.headers["referrer-policy"] == "no-referrer"


def test_logout_requires_exact_origin_and_csrf_then_clears_cookies() -> None:
    client, service = make_client()
    with client:
        client.cookies.set("tamforge_session", "s" * 43, path="/api/v1")
        denied = client.post(
            "/api/v1/auth/logout",
            headers={"Origin": "https://evil.example.test", "X-CSRF-Token": "c" * 43},
        )
        allowed = client.post(
            "/api/v1/auth/logout",
            headers={"Origin": "https://app.example.test", "X-CSRF-Token": "c" * 43},
        )

    assert denied.status_code == 403
    assert denied.json()["code"] == "origin_rejected"
    assert service.logout_calls == 1
    assert allowed.status_code == 204
    cleared = allowed.headers.get_list("set-cookie")
    assert any('tamforge_session=""' in value and "Max-Age=0" in value for value in cleared)
    assert any('tamforge_csrf=""' in value and "Max-Age=0" in value for value in cleared)
    assert allowed.headers["referrer-policy"] == "no-referrer"

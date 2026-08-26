from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import respx

pytestmark = pytest.mark.integration


@respx.mock
def test_owner_only_oauth_session_and_logout_round_trip(test_database_url: str) -> None:
    from alembic import command
    from alembic.config import Config
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    from tamforge_backend.auth.crypto import hash_secret
    from tamforge_backend.config import Settings
    from tamforge_backend.database import database_url_to_sync
    from tamforge_backend.main import create_app

    migration = Config("apps/backend/alembic.ini")
    migration.attributes["database_url"] = test_database_url
    command.downgrade(migration, "base")
    command.upgrade(migration, "head")

    async_url = make_url(test_database_url).set(drivername="postgresql+asyncpg")
    settings = Settings(
        environment="test",
        database_url=async_url.render_as_string(hide_password=False),
        github_user_id=102269369,
        github_client_id="client-id",
        github_client_secret="provider-secret-not-persisted",
        session_signing_secret="state-signing-secret-with-enough-entropy",
        github_callback_url="https://app.example.test/api/v1/auth/callback",
        cors_origins=["https://app.example.test"],
        _env_file=None,
    )
    token_route = respx.post("https://github.com/login/oauth/access_token").mock(
        side_effect=[
            httpx.Response(
                200,
                json={"access_token": "wrong-identity-token", "token_type": "bearer"},
            ),
            httpx.Response(
                200,
                json={"access_token": "owner-identity-token", "token_type": "bearer"},
            ),
        ]
    )
    user_route = respx.get("https://api.github.com/user").mock(
        side_effect=[
            httpx.Response(200, json={"id": 999, "login": "lookalike"}),
            httpx.Response(200, json={"id": 102269369, "login": "renamed-owner"}),
        ]
    )
    app = create_app(settings)
    engine = create_engine(database_url_to_sync(test_database_url))

    def counts() -> tuple[int, int]:
        with engine.connect() as connection:
            return (
                connection.execute(text("SELECT count(*) FROM owners")).scalar_one(),
                connection.execute(text("SELECT count(*) FROM auth_sessions")).scalar_one(),
            )

    try:
        with TestClient(app) as client:
            login = client.get("/api/v1/auth/login", follow_redirects=False)
            wrong_state = parse_qs(urlsplit(login.headers["location"]).query)["state"][0]
            denied = client.get(
                "/api/v1/auth/callback",
                params={"code": "one-time-code", "state": wrong_state},
                follow_redirects=False,
            )
            assert denied.status_code == 403
            assert counts() == (0, 0)

            login = client.get("/api/v1/auth/login", follow_redirects=False)
            state = parse_qs(urlsplit(login.headers["location"]).query)["state"][0]
            callback = client.get(
                "/api/v1/auth/callback",
                params={"code": "one-time-code", "state": state},
                follow_redirects=False,
            )
            assert callback.status_code == 303
            assert counts() == (1, 1)

            replay = client.get(
                "/api/v1/auth/callback",
                params={"code": "one-time-code", "state": state},
                follow_redirects=False,
            )
            assert replay.status_code == 400
            assert counts() == (1, 1)

            session = client.get("/api/v1/auth/session")
            assert session.status_code == 200
            assert session.json()["github_login"] == "renamed-owner"
            csrf_token = session.json()["csrf_token"]

            raw_session = client.cookies.get("tamforge_session")
            assert raw_session is not None
            logout = client.post(
                "/api/v1/auth/logout",
                headers={
                    "Origin": "https://app.example.test",
                    "X-CSRF-Token": csrf_token,
                },
            )
            assert logout.status_code == 204

            repeated = client.post(
                "/api/v1/auth/logout",
                headers={
                    "Origin": "https://app.example.test",
                    "X-CSRF-Token": csrf_token,
                    "Cookie": f"tamforge_session={raw_session}",
                },
            )
            assert repeated.status_code == 204

            assert token_route.call_count == 2
            assert user_route.call_count == 2

        with engine.connect() as connection:
            session_row = connection.execute(
                text("SELECT token_hash, csrf_hash, revoked_at FROM auth_sessions")
            ).one()
            assert len(session_row.token_hash) == 32
            assert len(session_row.csrf_hash) == 32
            assert session_row.token_hash == hash_secret(raw_session)
            assert session_row.csrf_hash == hash_secret(csrf_token)
            assert raw_session.encode() not in session_row.token_hash
            assert csrf_token.encode() not in session_row.csrf_hash
            assert session_row.revoked_at is not None
            assert "provider-secret-not-persisted" not in repr(session_row)
    finally:
        engine.dispose()

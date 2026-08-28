from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import respx

pytestmark = pytest.mark.integration


def _settings(test_database_url: str) -> object:
    from sqlalchemy.engine import make_url
    from tamforge_backend.config import Settings

    async_url = make_url(test_database_url).set(drivername="postgresql+asyncpg")
    return Settings(
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


@respx.mock
def test_native_oauth_rotation_replay_and_hash_only_storage(
    test_database_url: str,
) -> None:
    from alembic import command
    from alembic.config import Config
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine, text
    from tamforge_backend.auth.service import AuthService
    from tamforge_backend.database import database_url_to_sync
    from tamforge_backend.main import create_app

    migration = Config("apps/backend/alembic.ini")
    migration.attributes["database_url"] = test_database_url
    command.downgrade(migration, "base")
    command.upgrade(migration, "head")

    respx.post("https://github.com/login/oauth/access_token").mock(
        return_value=httpx.Response(
            200,
            json={"access_token": "provider-access-token", "token_type": "bearer"},
        )
    )
    respx.get("https://api.github.com/user").mock(
        return_value=httpx.Response(200, json={"id": 102269369, "login": "fgomensoro"})
    )

    verifier = "v" * 43
    challenge = AuthService.pkce_challenge(verifier)
    app = create_app(_settings(test_database_url))  # type: ignore[arg-type]
    engine = create_engine(database_url_to_sync(test_database_url))
    try:
        with TestClient(app) as client:
            started = client.post(
                "/api/v1/auth/native/start",
                json={"code_challenge": challenge},
            )
            assert started.status_code == 200
            state = parse_qs(
                urlsplit(started.json()["authorization_url"]).query
            )["state"][0]

            callback = client.get(
                "/api/v1/auth/callback",
                params={"code": "provider-code", "state": state},
                follow_redirects=False,
            )
            exchange_code = parse_qs(urlsplit(callback.headers["location"]).query)["code"][0]
            exchanged = client.post(
                "/api/v1/auth/native/exchange",
                json={"code": exchange_code, "code_verifier": verifier},
            )
            assert exchanged.status_code == 200
            first = exchanged.json()
            assert client.get(
                "/api/v1/auth/native/session",
                headers={"Authorization": f"Bearer {first['access_token']}"},
            ).status_code == 200

            refreshed = client.post(
                "/api/v1/auth/native/refresh",
                json={"refresh_token": first["refresh_token"]},
            )
            assert refreshed.status_code == 200
            second = refreshed.json()
            assert client.get(
                "/api/v1/auth/native/session",
                headers={"Authorization": f"Bearer {first['access_token']}"},
            ).status_code == 401

            replay = client.post(
                "/api/v1/auth/native/refresh",
                json={"refresh_token": first["refresh_token"]},
            )
            assert replay.status_code == 401
            assert client.get(
                "/api/v1/auth/native/session",
                headers={"Authorization": f"Bearer {second['access_token']}"},
            ).status_code == 401
            assert client.post(
                "/api/v1/auth/native/refresh",
                json={"refresh_token": second["refresh_token"]},
            ).status_code == 401

        with engine.connect() as connection:
            stored = {
                "flow": connection.execute(
                    text("SELECT state_hash, pkce_challenge FROM native_oauth_flows")
                ).all(),
                "exchange": connection.execute(
                    text("SELECT code_hash, pkce_challenge FROM native_exchange_codes")
                ).all(),
                "session": connection.execute(
                    text(
                        "SELECT access_token_hash, revoked_at FROM native_auth_sessions"
                    )
                ).all(),
                "refresh": connection.execute(
                    text(
                        "SELECT token_hash, consumed_at, revoked_at "
                        "FROM native_refresh_tokens ORDER BY id"
                    )
                ).all(),
            }
            audits = connection.execute(
                text(
                    "SELECT action, redacted_metadata FROM audit_events "
                    "WHERE action LIKE 'auth.native_%' ORDER BY id"
                )
            ).all()

        assert len(stored["flow"][0].state_hash) == 32
        assert len(stored["exchange"][0].code_hash) == 32
        assert len(stored["session"][0].access_token_hash) == 32
        assert all(len(row.token_hash) == 32 for row in stored["refresh"])
        assert stored["session"][0].revoked_at is not None
        replay_audit = [row for row in audits if row.action == "auth.native_refresh.denied"][-1]
        assert replay_audit.redacted_metadata["flags"]["replayed"] is True
        assert replay_audit.redacted_metadata["flags"]["redacted"] is True
        persisted = repr((stored, audits))
        for raw_secret in (
            state,
            exchange_code,
            first["access_token"],
            first["refresh_token"],
            second["access_token"],
            second["refresh_token"],
            "provider-access-token",
            "provider-secret-not-persisted",
        ):
            assert raw_secret not in persisted
    finally:
        engine.dispose()


def test_native_auth_downgrade_refuses_active_session(test_database_url: str) -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import DBAPIError
    from tamforge_backend.database import database_url_to_sync

    migration = Config("apps/backend/alembic.ini")
    migration.attributes["database_url"] = test_database_url
    command.downgrade(migration, "base")
    command.upgrade(migration, "head")
    engine = create_engine(database_url_to_sync(test_database_url))
    try:
        with engine.begin() as connection:
            owner_id = connection.execute(
                text(
                    "INSERT INTO owners (github_user_id, github_login) "
                    "VALUES (102269369, 'fgomensoro') RETURNING id"
                )
            ).scalar_one()
            session_id = connection.execute(
                text(
                    "INSERT INTO native_auth_sessions "
                    "(owner_id, access_token_hash, access_expires_at) "
                    "VALUES (:owner_id, :token_hash, CURRENT_TIMESTAMP + INTERVAL '15 minutes') "
                    "RETURNING id"
                ),
                {"owner_id": owner_id, "token_hash": b"a" * 32},
            ).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO native_refresh_tokens "
                    "(session_id, token_hash, expires_at) "
                    "VALUES (:session_id, :token_hash, CURRENT_TIMESTAMP + INTERVAL '30 days')"
                ),
                {"session_id": session_id, "token_hash": b"r" * 32},
            )

        with pytest.raises(DBAPIError, match="active native sessions must be revoked"):
            command.downgrade(migration, "20260828_0011_durable_jobs")

        with engine.begin() as connection:
            connection.execute(
                text("UPDATE native_auth_sessions SET revoked_at = CURRENT_TIMESTAMP")
            )
            connection.execute(
                text("UPDATE native_refresh_tokens SET revoked_at = CURRENT_TIMESTAMP")
            )
        command.downgrade(migration, "20260828_0011_durable_jobs")
    finally:
        engine.dispose()
        command.upgrade(migration, "head")

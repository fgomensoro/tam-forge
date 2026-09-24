from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from tamforge_backend.auth.dependencies import get_auth_service, get_authenticated_owner
from tamforge_backend.auth.schemas import AuthenticatedOwner
from tamforge_backend.auth.service import Unauthenticated
from tamforge_backend.config import Settings
from tamforge_backend.main import create_app
from tamforge_backend.observability.routes import get_database_ready


def test_health_and_owner_operational_routes_do_not_change_native_contract() -> None:
    app = create_app(Settings(environment="test", _env_file=None))
    app.dependency_overrides[get_database_ready] = lambda: True
    owner = AuthenticatedOwner(
        owner_id=1,
        github_user_id=102269369,
        github_login="private",
        session_id=1,
        csrf_hash=None,
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
    )
    app.dependency_overrides[get_authenticated_owner] = lambda: owner
    with TestClient(app) as client:
        # Missing ingest evidence refuses readiness; liveness is still healthy.
        assert client.get("/healthz").status_code == 200
        assert client.get("/readyz").status_code == 503
        app.state.operational_health.report("ingest", "ok", "none")
        app.state.operational_health.report("claude", "needs_attention", "quota")
        response = client.get("/readyz")
        assert response.status_code == 200
        assert response.json() == {"status": "degraded"}
        assert response.headers["cache-control"] == "no-store"
        response = client.get("/ops/status")
        assert response.json()["components"]["claude"]["reason"] == "quota"
        assert response.headers["cache-control"] == "no-store"
        metrics = client.get("/ops/metrics")
        assert metrics.status_code == 200
        assert metrics.headers["cache-control"] == "no-store"
        assert "tamforge_http_requests_total" in metrics.text
        assert "private" not in metrics.text
        assert "/ops/status" not in app.openapi()["paths"]


def test_operational_details_require_owner_authentication() -> None:
    app = create_app(Settings(environment="test", _env_file=None))

    def reject() -> None:
        raise Unauthenticated("authentication required")

    async def forbidden_probe() -> bool:
        raise AssertionError("unauthenticated requests must not probe database")

    app.dependency_overrides[get_authenticated_owner] = reject
    app.dependency_overrides[get_database_ready] = forbidden_probe
    # The CSRF dependency builds the auth service before it asks for the owner; without a
    # database that is a 503, so stand it in and let the owner check refuse the request.
    app.dependency_overrides[get_auth_service] = lambda: object()
    with TestClient(app) as client:
        assert client.get("/ops/status").status_code == 401
        assert client.get("/ops/metrics").status_code == 401
        assert client.get("/ops/claude/slot").status_code == 401
        assert client.put("/ops/claude/slot", json={"slot": "b"}).status_code == 401


def test_the_application_starts_without_object_store_credentials() -> None:
    """The ingest heartbeat must not become a startup dependency.

    The object store is built on first use, so a deployment configured without its
    credentials still starts and still serves every path that does not touch it.
    Building the store eagerly for the heartbeat would have turned a missing optional
    credential into a failure to boot.
    """
    app = create_app(Settings(environment="test", _env_file=None))
    app.dependency_overrides[get_database_ready] = lambda: True
    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/readyz").status_code == 503


def test_the_ingest_heartbeat_runs_for_the_lifetime_of_the_application() -> None:
    app = create_app(Settings(environment="test", _env_file=None))
    with TestClient(app):
        heartbeat = app.state.ingest_heartbeat
        assert heartbeat.done() is False
    assert heartbeat.done() is True


def test_the_owner_reads_and_switches_the_claude_token_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tamforge_backend.auth.dependencies import require_csrf_owner
    from tamforge_backend.database import get_db_session
    from tamforge_backend.observability import routes

    app = create_app(Settings(environment="test", _env_file=None))
    owner = AuthenticatedOwner(
        owner_id=1,
        github_user_id=102269369,
        github_login="private",
        session_id=1,
        csrf_hash=None,
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
    )
    app.dependency_overrides[get_authenticated_owner] = lambda: owner
    app.dependency_overrides[require_csrf_owner] = lambda: owner
    app.dependency_overrides[get_db_session] = lambda: object()
    chosen: list[tuple[int, str]] = []

    async def read(session: object, *, owner_id: int) -> str:
        return chosen[-1][1] if chosen else "a"

    async def choose(session: object, *, owner_id: int, slot: str) -> None:
        chosen.append((owner_id, slot))

    monkeypatch.setattr(routes, "read_active_slot", read)
    monkeypatch.setattr(routes, "choose_slot", choose)
    with TestClient(app) as client:
        response = client.get("/ops/claude/slot")
        assert response.json() == {"slot": "a"}
        assert response.headers["cache-control"] == "no-store"

        response = client.put("/ops/claude/slot", json={"slot": "b"})
        assert response.status_code == 200
        assert response.json() == {"slot": "b"}
        assert chosen == [(1, "b")]
        assert client.get("/ops/claude/slot").json() == {"slot": "b"}

        assert client.put("/ops/claude/slot", json={"slot": "c"}).status_code == 422
        assert (
            client.put(
                "/ops/claude/slot", json={"slot": "a", "token": "sk-ant-oat01-fixture"}
            ).status_code
            == 422
        )
        assert chosen == [(1, "b")]
        assert "/ops/claude/slot" not in app.openapi()["paths"]

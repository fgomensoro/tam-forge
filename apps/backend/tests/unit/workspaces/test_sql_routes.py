from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from tamforge_backend.auth.dependencies import get_authenticated_owner, require_csrf_owner
from tamforge_backend.auth.schemas import AuthenticatedOwner
from tamforge_backend.config import Settings
from tamforge_backend.main import create_app
from tamforge_backend.workspaces.sql_contracts import build_sql_result

OWNER = AuthenticatedOwner(
    owner_id=1,
    github_user_id=102269369,
    github_login="fgomensoro",
    session_id=1,
    csrf_hash=b"c" * 32,
    expires_at=datetime.now(UTC) + timedelta(hours=1),
)


def _result() -> object:
    from tamforge_backend.workspaces.sql_contracts import SqlExercise

    exercise = SqlExercise(
        key="support_counts",
        version=1,
        schema_name="learning_support",
        role_name="tamforge_learning_runner_support",
        task_stable_ids=("fixture.sql.support-counts",),
        columns=("account_id", "ticket_count"),
        expected_rows=(("a", "2"),),
        grain_columns=("account_id",),
        ordered=False,
    )
    return build_sql_result(exercise, exercise.columns, exercise.expected_rows, 12)


def _response() -> object:
    from tamforge_backend.workspaces.sql_service import SqlExecutionResponse

    query = "SELECT account_id, count(*) AS ticket_count FROM tickets GROUP BY 1"
    return SqlExecutionResponse(
        execution_id=11,
        activity_id=7,
        query=query,
        query_sha256=hashlib.sha256(query.encode()).hexdigest(),
        result=_result(),
    )


class StubSqlExecutionService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.error: Exception | None = None

    async def execute(self, **values: object) -> object:
        self.calls.append(("execute", values))
        if self.error is not None:
            raise self.error
        return _response()

    async def history(self, **values: object) -> object:
        from tamforge_backend.workspaces.sql_service import SqlExecutionHistory

        self.calls.append(("history", values))
        if self.error is not None:
            raise self.error
        return SqlExecutionHistory(items=(_response(),))


def _client() -> tuple[TestClient, StubSqlExecutionService]:
    from tamforge_backend.workspaces.routes import get_sql_execution_service

    app = create_app(
        Settings(
            environment="test",
            github_user_id=102269369,
            cors_origins=["https://app.example.test"],
            secure_cookies=False,
            _env_file=None,
        )
    )
    service = StubSqlExecutionService()
    app.dependency_overrides[get_sql_execution_service] = lambda: service
    app.dependency_overrides[get_authenticated_owner] = lambda: OWNER
    app.dependency_overrides[require_csrf_owner] = lambda: OWNER
    return TestClient(app), service


def test_sql_execution_routes_forward_only_owner_scoped_bounded_inputs() -> None:
    from tamforge_backend.workspaces.sql_service import SqlExecutionCommand

    client, service = _client()
    query = "SELECT account_id, count(*) AS ticket_count FROM tickets GROUP BY 1"
    with client:
        executed = client.post(
            "/api/v1/activities/7/sql-executions",
            json={"expected_version": 2, "query": query},
            headers={"Idempotency-Key": "sql-run-7-1"},
        )
        history = client.get("/api/v1/activities/7/sql-executions")

    assert executed.status_code == 200
    assert executed.json() == _response().model_dump(mode="json")  # type: ignore[union-attr]
    assert history.status_code == 200
    assert history.json() == {
        "items": [_response().model_dump(mode="json")]  # type: ignore[union-attr]
    }
    assert executed.headers["cache-control"] == "no-store"
    assert history.headers["cache-control"] == "no-store"
    assert service.calls == [
        (
            "execute",
            {
                "owner_id": 1,
                "activity_id": 7,
                "command": SqlExecutionCommand(expected_version=2, query=query),
                "idempotency_key": "sql-run-7-1",
            },
        ),
        ("history", {"owner_id": 1, "activity_id": 7}),
    ]


@pytest.mark.parametrize(
    ("error_name", "detail", "status", "code"),
    [
        ("SqlExecutionNotFound", "private missing detail", 404, "sql_activity_not_found"),
        ("SqlExecutionConflict", "private conflict detail", 409, "sql_execution_conflict"),
        ("SqlExecutionInvalid", "SELECT private_secret", 422, "invalid_sql_execution"),
        ("SqlExecutionBusy", "private capacity detail", 429, "sql_execution_busy"),
        (
            "SqlExecutionUnavailable",
            "postgresql://user:secret@private-db/app",
            503,
            "sql_execution_unavailable",
        ),
    ],
)
def test_sql_execution_errors_are_fixed_and_never_leak_details(
    error_name: str, detail: str, status: int, code: str
) -> None:
    from tamforge_backend.workspaces import sql_service

    error = getattr(sql_service, error_name)(detail)
    client, service = _client()
    service.error = error

    with client:
        response = client.post(
            "/api/v1/activities/7/sql-executions",
            json={"expected_version": 2, "query": "SELECT 1"},
            headers={"Idempotency-Key": "sql-run-error"},
        )

    assert response.status_code == status
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["code"] == code
    assert str(error) not in response.text


def test_sql_history_rollback_db_failure_is_safe_and_non_cacheable() -> None:
    from tamforge_backend.workspaces.routes import get_sql_execution_service
    from tamforge_backend.workspaces.sql_service import SqlExecutionService

    class EmptyReceiptResult:
        def scalars(self) -> EmptyReceiptResult:
            return self

        def all(self) -> list[object]:
            return []

    class FailingRollbackSession:
        async def scalar(self, statement: object) -> int:
            del statement
            return 7

        async def execute(self, statement: object) -> EmptyReceiptResult:
            del statement
            return EmptyReceiptResult()

        async def rollback(self) -> None:
            raise SQLAlchemyError("postgresql://user:secret@private-db/app")

    app = create_app(
        Settings(
            environment="test",
            github_user_id=102269369,
            secure_cookies=False,
            _env_file=None,
        )
    )
    service = SqlExecutionService(
        cast(AsyncSession, FailingRollbackSession()),
        catalog=None,
        runner=None,
    )
    app.dependency_overrides[get_sql_execution_service] = lambda: service
    app.dependency_overrides[get_authenticated_owner] = lambda: OWNER

    with TestClient(app) as client:
        response = client.get("/api/v1/activities/7/sql-executions")

    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["code"] == "sql_execution_unavailable"
    assert "private-db" not in response.text


@pytest.mark.parametrize(
    "payload",
    [
        {"expected_version": 2, "query": ""},
        {"expected_version": 2, "query": " \n\t"},
        {"expected_version": 2, "query": "SELECT 1", "owner_id": 9},
        {"expected_version": 2, "query": "é" * 32_769},
    ],
)
def test_sql_execution_route_rejects_invalid_or_oversized_queries(payload: dict) -> None:
    client, service = _client()

    with client:
        response = client.post(
            "/api/v1/activities/7/sql-executions",
            json=payload,
            headers={"Idempotency-Key": "sql-invalid"},
        )

    assert response.status_code == 422
    assert response.headers["cache-control"] == "no-store"
    assert service.calls == []


def test_sql_execution_post_requires_csrf_while_history_is_read_only() -> None:
    from tamforge_backend.auth.dependencies import get_auth_service
    from tamforge_backend.workspaces.routes import get_sql_execution_service

    class StubAuthService:
        @staticmethod
        def verify_csrf(owner: object, raw_csrf_token: str | None) -> None:
            del owner, raw_csrf_token

    app = create_app(
        Settings(
            environment="test",
            github_user_id=102269369,
            cors_origins=["https://app.example.test"],
            secure_cookies=False,
            _env_file=None,
        )
    )
    service = StubSqlExecutionService()
    app.dependency_overrides[get_sql_execution_service] = lambda: service
    app.dependency_overrides[get_auth_service] = lambda: StubAuthService()
    app.dependency_overrides[get_authenticated_owner] = lambda: OWNER

    with TestClient(app) as client:
        rejected = client.post(
            "/api/v1/activities/7/sql-executions",
            json={"expected_version": 2, "query": "SELECT 1"},
            headers={"Idempotency-Key": "sql-csrf"},
        )
        history = client.get("/api/v1/activities/7/sql-executions")

    assert rejected.status_code in {401, 403}
    assert history.status_code == 200
    assert service.calls == [("history", {"owner_id": 1, "activity_id": 7})]


def test_sql_execution_routes_require_an_authenticated_owner() -> None:
    from tamforge_backend.auth.service import Unauthenticated
    from tamforge_backend.workspaces.routes import get_sql_execution_service

    app = create_app(
        Settings(
            environment="test",
            github_user_id=102269369,
            secure_cookies=False,
            _env_file=None,
        )
    )
    service = StubSqlExecutionService()

    def missing_owner() -> None:
        raise Unauthenticated("private authentication detail")

    app.dependency_overrides[get_sql_execution_service] = lambda: service
    app.dependency_overrides[get_authenticated_owner] = missing_owner
    app.dependency_overrides[require_csrf_owner] = missing_owner

    with TestClient(app) as client:
        history = client.get("/api/v1/activities/7/sql-executions")
        executed = client.post(
            "/api/v1/activities/7/sql-executions",
            json={"expected_version": 2, "query": "SELECT 1"},
            headers={"Idempotency-Key": "sql-auth"},
        )

    assert history.status_code == 401
    assert executed.status_code == 401
    assert history.headers["cache-control"] == "no-store"
    assert executed.headers["cache-control"] == "no-store"
    assert service.calls == []


def test_invalid_sql_configuration_does_not_prevent_app_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TAMFORGE_SQL_EXERCISE_CATALOG", "/missing/private/catalog.json")
    monkeypatch.setenv("TAMFORGE_SQL_EXERCISE_DSNS", '{"secret":"postgresql://secret"}')

    app = create_app(
        Settings(
            environment="test",
            github_user_id=102269369,
            secure_cookies=False,
            _env_file=None,
        )
    )
    with TestClient(app) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_app_initializes_exactly_one_shared_sql_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    from tamforge_backend.workspaces import routes
    from tamforge_backend.workspaces.sql_settings import SqlExerciseCatalog

    catalog = SqlExerciseCatalog()
    created: list[object] = []

    class CountingRunner:
        def __init__(self, selected_catalog: object) -> None:
            assert selected_catalog is catalog
            created.append(self)

    monkeypatch.setattr(
        routes.SqlExerciseCatalog,
        "from_env",
        classmethod(lambda cls: catalog),
    )
    monkeypatch.setattr(routes, "PostgresSqlRunner", CountingRunner)

    app = create_app(
        Settings(
            environment="test",
            github_user_id=102269369,
            secure_cookies=False,
            _env_file=None,
        )
    )

    assert len(created) == 1
    assert app.state.sql_execution_runtime.runner is created[0]

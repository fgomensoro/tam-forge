from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.engine import Connection

pytestmark = pytest.mark.integration


def _seed_activity(
    connection: Connection,
    *,
    owner_id: int,
    suffix: str,
    local_date: date,
    stable_id: str,
    block: str = "sql",
) -> int:
    from sqlalchemy import text

    source_id = connection.execute(
        text(
            "INSERT INTO roadmap_sources (owner_id, source_key, name, source_kind) "
            "VALUES (:owner_id, :source_key, 'SQL API fixture', 'manual') RETURNING id"
        ),
        {"owner_id": owner_id, "source_key": f"sql-api-{suffix}"},
    ).scalar_one()
    version_id = connection.execute(
        text(
            "INSERT INTO roadmap_versions ("
            "owner_id, source_id, version_key, version_number, month_number, content_hash, "
            "object_key, manifest, raw_payload, normalized_payload, mirror_status, state"
            ") VALUES ("
            ":owner_id, :source_id, :version_key, 1, 1, :content_hash, :object_key, "
            "'{}'::jsonb, '{}'::jsonb, '{}'::jsonb, 'not_required', 'draft'"
            ") RETURNING id"
        ),
        {
            "owner_id": owner_id,
            "source_id": source_id,
            "version_key": f"sql-api-{suffix}-v1",
            "content_hash": hashlib.sha256(suffix.encode()).digest(),
            "object_key": f"private/sql-api/{suffix}.json",
        },
    ).scalar_one()
    node_id = connection.execute(
        text(
            "INSERT INTO curriculum_nodes ("
            "owner_id, roadmap_version_id, stable_id, ordinal, kind, title"
            ") VALUES (:owner_id, :version_id, :stable_id, 0, 'task', 'SQL API') "
            "RETURNING id"
        ),
        {
            "owner_id": owner_id,
            "version_id": version_id,
            "stable_id": f"node-{suffix}",
        },
    ).scalar_one()
    task_id = connection.execute(
        text(
            "INSERT INTO task_definitions ("
            "owner_id, roadmap_version_id, curriculum_node_id, stable_id, exercise_type, "
            "mapping_version, objective, timebox_minutes, block, required, output_contract, "
            "pass_contract, evidence_contract, source_references, allowed_ai_role"
            ") VALUES ("
            ":owner_id, :version_id, :node_id, :stable_id, :exercise_type, 'fixture-v1', "
            "'Execute the assigned query.', 45, :block, true, '{}'::jsonb, '{}'::jsonb, "
            "'{}'::jsonb, '[]'::jsonb, 'none'"
            ") RETURNING id"
        ),
        {
            "owner_id": owner_id,
            "version_id": version_id,
            "node_id": node_id,
            "stable_id": stable_id,
            "exercise_type": "sql_guided_lesson" if block == "sql" else "reading",
            "block": block,
        },
    ).scalar_one()
    day_id = connection.execute(
        text(
            "INSERT INTO study_days ("
            "owner_id, roadmap_version_id, local_date, planned_minutes, focused_minutes, "
            "day_type, status, started_at"
            ") VALUES ("
            ":owner_id, :version_id, :local_date, 45, 0, 'weekday', 'planned', NULL"
            ") RETURNING id"
        ),
        {"owner_id": owner_id, "version_id": version_id, "local_date": local_date},
    ).scalar_one()
    activity_id = connection.execute(
        text(
            "INSERT INTO activity_instances ("
            "owner_id, study_day_id, roadmap_version_id, task_definition_id, "
            "task_stable_id_snapshot, task_mapping_version_snapshot, task_objective_snapshot, "
            "task_timebox_minutes_snapshot, roadmap_version_key_snapshot, state, attempt_kind, "
            "assistance_mode, classification, timebox_minutes, source_hidden, "
            "optimistic_version, replacement_version"
            ") VALUES ("
            ":owner_id, :day_id, :version_id, :task_id, :stable_id, 'fixture-v1', "
            "'Execute the assigned query.', 45, :version_key, 'ready', 'none', 'none', "
            "'required', 45, false, 1, 1"
            ") RETURNING id"
        ),
        {
            "owner_id": owner_id,
            "day_id": day_id,
            "version_id": version_id,
            "task_id": task_id,
            "stable_id": stable_id,
            "version_key": f"sql-api-{suffix}-v1",
        },
    ).scalar_one()
    return int(activity_id)


def test_sql_execution_api_persists_immutable_owner_scoped_bounded_receipts(
    test_database_url: str,
) -> None:
    import asyncio

    from alembic import command
    from alembic.config import Config
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine, func, select, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.exc import DBAPIError, IntegrityError
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool
    from tamforge_backend.auth.dependencies import (
        get_authenticated_owner,
        require_csrf_owner,
    )
    from tamforge_backend.auth.schemas import AuthenticatedOwner
    from tamforge_backend.config import Settings
    from tamforge_backend.database import database_url_to_sync
    from tamforge_backend.learning.service import ActivityService
    from tamforge_backend.main import create_app
    from tamforge_backend.workspaces.models import SqlExecution
    from tamforge_backend.workspaces.routes import get_sql_execution_service
    from tamforge_backend.workspaces.sql_contracts import (
        MAX_QUERY_BYTES,
        SqlExercise,
        SqlRunnerError,
        build_sql_result,
        canonical_result_bytes,
    )
    from tamforge_backend.workspaces.sql_service import SqlExecutionService
    from tamforge_backend.workspaces.sql_settings import SqlExerciseCatalog

    migration = Config("apps/backend/alembic.ini")
    migration.attributes["database_url"] = test_database_url
    sync_engine = create_engine(database_url_to_sync(test_database_url))
    async_engine = create_async_engine(
        make_url(test_database_url).set(drivername="postgresql+asyncpg"),
        poolclass=NullPool,
    )
    factory = async_sessionmaker(async_engine, expire_on_commit=False, autoflush=False)
    exercise = SqlExercise(
        key="support_counts",
        version=7,
        schema_name="learning_support",
        role_name="tamforge_learning_runner_support",
        task_stable_ids=("fixture.sql.support-counts",),
        columns=("account_id", "ticket_count"),
        expected_rows=(("a", "2"), ("b", "1")),
        grain_columns=("account_id",),
        ordered=False,
    )
    catalog = SqlExerciseCatalog(
        exercises=(exercise,),
        dsns={
            exercise.key: (
                "postgresql://tamforge_learning_runner_support:fixture-secret@localhost/learning"
            )
        },
    )

    class FakeRunner:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def run(self, selected: SqlExercise, query: str):  # type: ignore[no-untyped-def]
            self.calls.append(query)
            if query == "FAIL":
                raise SqlRunnerError("rejected_query")
            if len(query.encode()) == MAX_QUERY_BYTES:
                # Independently counted Task 1 boundary: 59 envelope bytes.
                cell = "x" * (262_144 - 59)
                result = build_sql_result(selected, selected.columns, (("a", cell),), 9)
                assert len(canonical_result_bytes(result.columns, result.rows)) == 262_144
                return result
            return build_sql_result(
                selected,
                selected.columns,
                (("b", 1), ("a", 2)),
                12,
            )

    runner = FakeRunner()
    active_owner: list[AuthenticatedOwner]
    try:
        command.downgrade(migration, "base")
        command.upgrade(migration, "head")
        with sync_engine.begin() as connection:
            owner_a = int(
                connection.execute(
                    text(
                        "INSERT INTO owners (github_user_id, github_login) "
                        "VALUES (102269369, 'owner-a') RETURNING id"
                    )
                ).scalar_one()
            )
            owner_b = int(
                connection.execute(
                    text(
                        "INSERT INTO owners (github_user_id, github_login) "
                        "VALUES (102269370, 'owner-b') RETURNING id"
                    )
                ).scalar_one()
            )
            activity_id = _seed_activity(
                connection,
                owner_id=owner_a,
                suffix="mapped",
                local_date=date(2026, 9, 4),
                stable_id="fixture.sql.support-counts",
            )
            non_sql_id = _seed_activity(
                connection,
                owner_id=owner_a,
                suffix="non-sql",
                local_date=date(2026, 9, 7),
                stable_id="fixture.reading.task",
                block="technical_learning",
            )
            unmapped_id = _seed_activity(
                connection,
                owner_id=owner_a,
                suffix="unmapped",
                local_date=date(2026, 9, 8),
                stable_id="fixture.sql.unmapped",
            )

        async def start_fixture_activities() -> None:
            async with factory() as session:
                service = ActivityService(session)
                for label, seeded_activity_id in (
                    ("mapped", activity_id),
                    ("non-sql", non_sql_id),
                    ("unmapped", unmapped_id),
                ):
                    started = await service.start(
                        owner_id=owner_a,
                        activity_id=seeded_activity_id,
                        expected_version=1,
                        idempotency_key=f"sql-api-start-{label}",
                    )
                    assert started.state.value == "active"
                    assert started.optimistic_version == 2

        asyncio.run(start_fixture_activities())

        now = datetime.now(UTC)
        owner_a_auth = AuthenticatedOwner(
            owner_id=owner_a,
            github_user_id=102269369,
            github_login="owner-a",
            session_id=1,
            csrf_hash=b"a" * 32,
            expires_at=now + timedelta(hours=1),
        )
        owner_b_auth = AuthenticatedOwner(
            owner_id=owner_b,
            github_user_id=102269370,
            github_login="owner-b",
            session_id=2,
            csrf_hash=b"b" * 32,
            expires_at=now + timedelta(hours=1),
        )
        active_owner = [owner_a_auth]
        app = create_app(
            Settings(
                environment="test",
                database_url=make_url(test_database_url)
                .set(drivername="postgresql+asyncpg")
                .render_as_string(hide_password=False),
                github_user_id=102269369,
                secure_cookies=False,
                _env_file=None,
            )
        )

        async def service_dependency() -> AsyncIterator[SqlExecutionService]:
            async with factory() as session:
                yield SqlExecutionService(session, catalog=catalog, runner=runner)

        app.dependency_overrides[get_sql_execution_service] = service_dependency
        app.dependency_overrides[get_authenticated_owner] = lambda: active_owner[0]
        app.dependency_overrides[require_csrf_owner] = lambda: active_owner[0]
        path = f"/api/v1/activities/{activity_id}/sql-executions"
        first_query = "SELECT account_id, count(*) AS ticket_count FROM tickets GROUP BY 1"
        with TestClient(app) as client:
            first = client.post(
                path,
                json={"expected_version": 2, "query": first_query},
                headers={"Idempotency-Key": "first"},
            )
            replay = client.post(
                path,
                json={"expected_version": 2, "query": first_query},
                headers={"Idempotency-Key": "first"},
            )
            mismatch = client.post(
                path,
                json={"expected_version": 2, "query": "SELECT 2"},
                headers={"Idempotency-Key": "first"},
            )
            stale = client.post(
                path,
                json={"expected_version": 1, "query": "SELECT 1"},
                headers={"Idempotency-Key": "stale"},
            )
            failed = client.post(
                path,
                json={"expected_version": 2, "query": "FAIL"},
                headers={"Idempotency-Key": "failed"},
            )
            non_sql = client.post(
                f"/api/v1/activities/{non_sql_id}/sql-executions",
                json={"expected_version": 2, "query": "SELECT 1"},
                headers={"Idempotency-Key": "non-sql"},
            )
            unmapped = client.post(
                f"/api/v1/activities/{unmapped_id}/sql-executions",
                json={"expected_version": 2, "query": "SELECT 1"},
                headers={"Idempotency-Key": "unmapped"},
            )

            maximum_query = "x" * MAX_QUERY_BYTES
            large_ids: list[int] = []
            for index in range(4):
                response = client.post(
                    path,
                    json={"expected_version": 2, "query": maximum_query},
                    headers={"Idempotency-Key": f"large-{index}"},
                )
                assert response.status_code == 200
                assert len(response.json()["result"]["rows"][0][1]) == 262_144 - 59
                large_ids.append(response.json()["execution_id"])
            history = client.get(path)

            async def pause_fixture_activity() -> None:
                async with factory() as session:
                    paused = await ActivityService(session).pause(
                        owner_id=owner_a,
                        activity_id=activity_id,
                        expected_version=2,
                        client_sequence=1,
                        idempotency_key="sql-api-pause-mapped",
                    )
                    assert paused.state.value == "paused"
                    assert paused.optimistic_version == 3

            asyncio.run(pause_fixture_activity())
            replay_after_progress = client.post(
                path,
                json={"expected_version": 2, "query": first_query},
                headers={"Idempotency-Key": "first"},
            )
            inactive = client.post(
                path,
                json={"expected_version": 3, "query": "SELECT 3"},
                headers={"Idempotency-Key": "inactive"},
            )

            async def unavailable_dependency() -> AsyncIterator[SqlExecutionService]:
                async with factory() as session:
                    yield SqlExecutionService(session, catalog=None, runner=None)

            app.dependency_overrides[get_sql_execution_service] = unavailable_dependency
            unavailable_replay = client.post(
                path,
                json={"expected_version": 2, "query": first_query},
                headers={"Idempotency-Key": "first"},
            )
            unavailable_history = client.get(path)
            unavailable_new = client.post(
                f"/api/v1/activities/{unmapped_id}/sql-executions",
                json={"expected_version": 2, "query": "SELECT 1"},
                headers={"Idempotency-Key": "unavailable"},
            )

            active_owner[0] = owner_b_auth
            cross_owner_history = client.get(path)
            cross_owner_execute = client.post(
                path,
                json={"expected_version": 3, "query": "SELECT 1"},
                headers={"Idempotency-Key": "cross-owner"},
            )

        assert first.status_code == 200
        assert first.json()["query"] == first_query
        assert first.json()["query_sha256"] == hashlib.sha256(first_query.encode()).hexdigest()
        assert first.json()["result"]["validation"] == "matched"
        assert replay.status_code == 200
        assert replay.json() == first.json()
        assert mismatch.status_code == 409
        assert stale.status_code == 409
        assert failed.status_code == 422
        assert non_sql.status_code == 409
        assert unmapped.status_code == 503
        assert history.status_code == 200
        assert len(history.content) <= 1024 * 1024
        assert 1 <= len(history.json()["items"]) < 5
        assert [item["execution_id"] for item in history.json()["items"]] == list(
            reversed(large_ids[-len(history.json()["items"]) :])
        )
        assert all(item["query"] == maximum_query for item in history.json()["items"])
        assert replay_after_progress.status_code == 200
        assert replay_after_progress.json() == first.json()
        assert inactive.status_code == 409
        assert unavailable_replay.status_code == 200
        assert unavailable_replay.json() == first.json()
        assert unavailable_history.status_code == 200
        assert unavailable_new.status_code == 503
        assert cross_owner_history.status_code == 404
        assert cross_owner_execute.status_code == 404
        assert len(runner.calls) == 6

        async def persisted_count() -> int:
            async with factory() as session:
                return int(
                    await session.scalar(
                        select(func.count())
                        .select_from(SqlExecution)
                        .where(SqlExecution.owner_id == owner_a)
                        .where(SqlExecution.activity_instance_id == activity_id)
                    )
                    or 0
                )

        assert asyncio.run(persisted_count()) == 5
        with sync_engine.connect() as connection:
            stored = connection.execute(
                text(
                    "SELECT octet_length(query), octet_length(canonical_result_json) "
                    "FROM sql_executions WHERE id = :execution_id"
                ),
                {"execution_id": large_ids[-1]},
            ).one()
        assert stored == (65_536, 262_144)

        with pytest.raises((IntegrityError, DBAPIError)):
            with sync_engine.begin() as connection:
                connection.execute(
                    text("UPDATE sql_executions SET elapsed_ms = 99 WHERE id = :id"),
                    {"id": first.json()["execution_id"]},
                )
        with pytest.raises((IntegrityError, DBAPIError)):
            with sync_engine.begin() as connection:
                connection.execute(
                    text("DELETE FROM sql_executions WHERE id = :id"),
                    {"id": first.json()["execution_id"]},
                )
        with pytest.raises((IntegrityError, DBAPIError)):
            with sync_engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO sql_executions ("
                        "owner_id, activity_instance_id, task_stable_id_snapshot, "
                        "task_mapping_version_snapshot, exercise_key, exercise_version, query, "
                        "query_sha256, canonical_result_json, result_sha256, elapsed_ms, "
                        "row_count, validation, idempotency_key, request_digest, created_at"
                        ") SELECT :owner_b, activity_instance_id, task_stable_id_snapshot, "
                        "task_mapping_version_snapshot, exercise_key, exercise_version, query, "
                        "query_sha256, canonical_result_json, result_sha256, elapsed_ms, "
                        "row_count, validation, 'cross-owner-fk', request_digest, created_at "
                        "FROM sql_executions WHERE id = :id"
                    ),
                    {"owner_b": owner_b, "id": first.json()["execution_id"]},
                )
    finally:
        asyncio.run(async_engine.dispose())
        try:
            with sync_engine.begin() as connection:
                connection.execute(text("DROP SCHEMA public CASCADE"))
                connection.execute(text("CREATE SCHEMA public"))
        finally:
            sync_engine.dispose()

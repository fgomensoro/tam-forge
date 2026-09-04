from __future__ import annotations

import hashlib
import io
from contextlib import redirect_stdout
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.orm import make_transient_to_detached


def _receipt() -> object:
    from tamforge_backend.workspaces.models import SqlExecution

    result_json = '{"columns":["account_id","ticket_count"],"rows":[["a","2"]]}'
    return SqlExecution(
        id=1,
        owner_id=1,
        activity_instance_id=7,
        task_stable_id_snapshot="fixture.sql.support-counts",
        task_mapping_version_snapshot="month-1-v1",
        exercise_key="support_counts",
        exercise_version=1,
        query="SELECT account_id, count(*) AS ticket_count FROM tickets GROUP BY 1",
        query_sha256=b"q" * 32,
        canonical_result_json=result_json,
        result_sha256=hashlib.sha256(result_json.encode()).digest(),
        elapsed_ms=12,
        row_count=1,
        validation="matched",
        idempotency_key="run-7-1",
        request_digest=b"r" * 32,
        created_at=datetime(2026, 9, 4, 20, tzinfo=UTC),
    )


def test_sql_execution_schema_is_owner_scoped_bounded_and_append_only() -> None:
    from tamforge_backend.models import Base, load_all_models
    from tamforge_backend.workspaces.models import (
        SqlExecution,
        reject_sql_execution_delete,
        reject_sql_execution_update,
    )

    load_all_models()
    table = Base.metadata.tables["sql_executions"]
    assert table is SqlExecution.__table__
    assert set(table.columns.keys()) == {
        "id",
        "owner_id",
        "activity_instance_id",
        "task_stable_id_snapshot",
        "task_mapping_version_snapshot",
        "exercise_key",
        "exercise_version",
        "query",
        "query_sha256",
        "canonical_result_json",
        "result_sha256",
        "elapsed_ms",
        "row_count",
        "validation",
        "idempotency_key",
        "request_digest",
        "created_at",
    }
    assert isinstance(table.c.query.type, sa.Text)
    assert isinstance(table.c.canonical_result_json.type, sa.Text)
    assert {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, sa.ForeignKeyConstraint)
    } == {"fk_sql_executions_owner_activity_activity_instances"}
    assert {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, sa.UniqueConstraint)
    } == {"uq_sql_executions_owner_activity_idempotency"}
    check_names = {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, sa.CheckConstraint)
    }
    assert {
        "ck_sql_executions_task_stable_id_snapshot_bounded",
        "ck_sql_executions_task_mapping_version_snapshot_bounded",
        "ck_sql_executions_exercise_key_shape",
        "ck_sql_executions_exercise_version_positive",
        "ck_sql_executions_query_bounded",
        "ck_sql_executions_query_sha256_length",
        "ck_sql_executions_query_sha256_matches",
        "ck_sql_executions_canonical_result_json_bounded",
        "ck_sql_executions_canonical_result_shape",
        "ck_sql_executions_result_sha256_length",
        "ck_sql_executions_result_sha256_matches",
        "ck_sql_executions_elapsed_ms_nonnegative",
        "ck_sql_executions_row_count_bounded",
        "ck_sql_executions_row_count_matches",
        "ck_sql_executions_validation_allowed",
        "ck_sql_executions_idempotency_key_bounded",
        "ck_sql_executions_request_digest_length",
    } <= check_names
    assert sa.event.contains(SqlExecution, "before_update", reject_sql_execution_update)
    assert sa.event.contains(SqlExecution, "before_delete", reject_sql_execution_delete)


def test_sql_execution_orm_rejects_attribute_mutation_and_delete() -> None:
    from tamforge_backend.workspaces.models import (
        AppendOnlySqlExecutionError,
        reject_sql_execution_delete,
    )

    receipt = _receipt()
    make_transient_to_detached(receipt)

    with pytest.raises(AppendOnlySqlExecutionError, match="immutable"):
        receipt.query = "SELECT secret"  # type: ignore[union-attr]
    with pytest.raises(AppendOnlySqlExecutionError, match="immutable"):
        reject_sql_execution_delete(None, None, receipt)  # type: ignore[arg-type]


def test_sql_execution_public_contracts_are_frozen_strict_and_byte_bounded() -> None:
    from tamforge_backend.workspaces.sql_service import (
        SqlExecutionCommand,
        SqlExecutionHistory,
        SqlExecutionResponse,
    )

    command = SqlExecutionCommand(expected_version=2, query="SELECT 1")
    assert command.expected_version == 2
    assert command.query == "SELECT 1"
    with pytest.raises(ValidationError):
        command.query = "SELECT 2"
    with pytest.raises(ValidationError):
        SqlExecutionCommand.model_validate(
            {"expected_version": 2, "query": "SELECT 1", "owner_id": 1}
        )
    for invalid in ("", " \n\t", "SELECT '\u0000'", "é" * 32_769):
        with pytest.raises(ValidationError):
            SqlExecutionCommand(expected_version=2, query=invalid)

    assert tuple(SqlExecutionResponse.model_fields) == (
        "execution_id",
        "activity_id",
        "query",
        "query_sha256",
        "result",
    )
    assert tuple(SqlExecutionHistory.model_fields) == ("items",)
    assert SqlExecutionCommand.model_json_schema()["properties"]["query"]["maxLength"] == 65_536
    assert SqlExecutionResponse.model_json_schema()["properties"]["query"]["maxLength"] == 65_536


def test_sql_execution_migration_contains_database_immutability_guards() -> None:
    from alembic import command
    from alembic.config import Config

    config = Config("apps/backend/alembic.ini")
    config.set_main_option(
        "sqlalchemy.url",
        "postgresql+psycopg://tamforge:secret@127.0.0.1:54329/tamforge_test",
    )
    output = io.StringIO()
    with redirect_stdout(output):
        command.upgrade(config, "20260904_0014_sql_executions", sql=True)
    sql = output.getvalue().lower()

    assert "create table sql_executions" in sql
    assert "tamforge_reject_sql_execution_mutation" in sql
    assert "before update or delete on public.sql_executions" in sql
    assert "foreign key(owner_id, activity_instance_id)" in sql

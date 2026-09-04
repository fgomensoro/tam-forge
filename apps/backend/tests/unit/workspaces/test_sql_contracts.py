from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, time
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError
from tamforge_backend.workspaces.sql_contracts import (
    SqlExercise,
    SqlRunnerError,
    build_sql_result,
)
from tamforge_backend.workspaces.sql_settings import SqlExerciseCatalog


def exercise(**changes: object) -> SqlExercise:
    return SqlExercise.model_validate(
        {
            "key": "support_counts",
            "version": 1,
            "schema_name": "learning_support",
            "role_name": "tamforge_learning_runner_support",
            "task_stable_ids": ("fixture.sql.support-counts",),
            "columns": ("account_id", "ticket_count"),
            "expected_rows": (("a", "2"), ("b", "1")),
            "grain_columns": ("account_id",),
            "ordered": False,
            **changes,
        }
    )


def test_golden_exact_result_and_grain() -> None:
    matched = build_sql_result(exercise(), ("account_id", "ticket_count"), (("b", 1), ("a", 2)), 12)
    assert matched.validation == "matched"
    assert matched.row_count == 2
    assert matched.rows == (("b", "1"), ("a", "2"))
    assert matched.elapsed_ms == 12
    assert matched.exercise_key == "support_counts"
    assert matched.exercise_version == 1
    canonical = b'{"columns":["account_id","ticket_count"],"rows":[["b","1"],["a","2"]]}'
    assert matched.result_sha256 == hashlib.sha256(canonical).hexdigest()
    wrong = build_sql_result(exercise(), ("account_id", "ticket_count"), (("a", 2), ("a", 1)), 12)
    assert wrong.validation == "wrong_grain"


@pytest.mark.parametrize(
    ("changes", "columns", "rows", "want"),
    [
        ({}, ("account_id", "ticket_count"), (("a", 3), ("b", 1)), "mismatch"),
        ({}, ("account_id", "count"), (("a", 2), ("b", 1)), "mismatch"),
        ({"ordered": True}, ("account_id", "ticket_count"), (("b", 1), ("a", 2)), "mismatch"),
        ({}, ("account_id", "ticket_count"), (("a", 2), ("a", 2)), "wrong_grain"),
        ({}, ("account_id", "ticket_count"), ((None, 2), (None, 1)), "wrong_grain"),
        ({}, ("account_id", "ticket_count"), ((None, 2), ("b", 1)), "wrong_grain"),
        ({}, ("account_id", "ticket_count"), (("a", 2),), "mismatch"),
    ],
)
def test_validation(changes: dict, columns: tuple, rows: tuple, want: str) -> None:
    assert build_sql_result(exercise(**changes), columns, rows, 0).validation == want


def test_normalizes_supported_cells_deterministically() -> None:
    ex = exercise(columns=("id", "value"), grain_columns=("id",), expected_rows=())
    cells = [
        True,
        False,
        2,
        1.5,
        Decimal("2.500"),
        date(2026, 9, 4),
        datetime(2026, 9, 4, 1, 2, tzinfo=UTC),
        time(1, 2),
        UUID("00000000-0000-0000-0000-000000000001"),
        None,
    ]
    result = build_sql_result(ex, ("id", "value"), tuple(enumerate(cells)), 1)
    assert tuple(row[1] for row in result.rows) == (
        "true",
        "false",
        "2",
        "1.5",
        "2.5",
        "2026-09-04",
        "2026-09-04T01:02:00+00:00",
        "01:02:00",
        "00000000-0000-0000-0000-000000000001",
        None,
    )


@pytest.mark.parametrize(
    "value",
    [float("nan"), float("inf"), Decimal("NaN"), b"secret", {"secret": 1}, [1], object(), "\ud800"],
)
def test_invalid_cells_have_closed_errors(value: object) -> None:
    with pytest.raises(SqlRunnerError) as caught:
        build_sql_result(exercise(), ("account_id", "ticket_count"), (("a", value),), 0)
    assert str(caught.value) == "invalid_result"
    assert caught.value.__cause__ is None


@pytest.mark.parametrize(
    ("columns", "rows", "code"),
    [
        (("account_id", "account_id"), (("a", 1),), "invalid_result"),
        (("account_id", "ticket_count"), (("a",),), "invalid_result"),
        (
            ("account_id", "ticket_count"),
            tuple((str(i), i) for i in range(1001)),
            "result_too_large",
        ),
        (tuple(f"c{i}" for i in range(33)), (), "result_too_large"),
        (("account_id", "ticket_count"), (("a", "é" * 131072),), "result_too_large"),
        (("account_id", "ticket_count"), (("a", "\n" * 131072),), "result_too_large"),
    ],
)
def test_result_limits(columns: tuple, rows: tuple, code: str) -> None:
    with pytest.raises(SqlRunnerError) as caught:
        build_sql_result(exercise(), columns, rows, 0)
    assert str(caught.value) == code


@pytest.mark.parametrize(
    "changes",
    [
        {"schema_name": "public; secret"},
        {"schema_name": "pg_catalog"},
        {"role_name": "Admin"},
        {"key": "é"},
        {"key": "x" * 64},
        {"version": True},
        {"version": 0},
        {"ordered": "false"},
        {"task_stable_ids": ()},
        {"columns": ("a", "a")},
        {"grain_columns": ("absent",)},
        {"expected_rows": (("a", "1"), ("a", "2"))},
        {"expected_rows": ((None, "1"),)},
        {"expected_rows": (("a", 1),)},
        {"secret": "marker"},
    ],
)
def test_exercise_rejects_invalid_configuration_without_echo(changes: dict) -> None:
    with pytest.raises(ValidationError) as caught:
        exercise(**changes)
    assert "input_value" not in str(caught.value)
    assert "public; secret" not in str(caught.value)


def test_contracts_are_frozen_and_result_is_validated_on_reconstruction() -> None:
    ex = exercise()
    with pytest.raises(ValidationError):
        ex.version = 2
    result = build_sql_result(ex, ex.columns, ex.expected_rows, 1)
    with pytest.raises(ValidationError):
        type(result).model_validate({**result.model_dump(), "row_count": 99})
    with pytest.raises(ValidationError):
        type(result).model_validate({**result.model_dump(), "result_sha256": "0" * 64})


def test_catalog_resolves_task_and_hides_secrets() -> None:
    ex = exercise()
    dsn = "postgresql://tamforge_learning_runner_support:top-secret@localhost/learning"
    catalog = SqlExerciseCatalog(exercises=(ex,), dsns={ex.key: dsn})
    assert catalog.enabled
    assert catalog.resolve("fixture.sql.support-counts") == ex
    assert catalog.dsn_for(ex) == dsn
    assert "top-secret" not in repr(catalog)
    with pytest.raises(SqlRunnerError, match="^unknown_exercise$"):
        catalog.resolve("unknown-secret")
    with pytest.raises(SqlRunnerError, match="^unknown_exercise$"):
        catalog.dsn_for(exercise(version=2))


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql://postgres:top-secret@localhost/learning",
        "postgresql://tamforge_learning_runner_support:top-secret@localhost/learning?user=postgres",
        "postgresql://tamforge_learning_runner_support:top-secret@localhost/learning?options=-crole=x",
        "postgresql://tamforge_learning_runner_support:top-secret@localhost/learning?sslmode=disable",
        "user=tamforge_learning_runner_support password=top-secret",
        "postgresql://tamforge_learning_runner_support:top-secret@localhost/",
    ],
)
def test_catalog_rejects_unsafe_dsns(dsn: str) -> None:
    with pytest.raises(SqlRunnerError) as caught:
        SqlExerciseCatalog(exercises=(exercise(),), dsns={"support_counts": dsn})
    assert str(caught.value) == "unsafe_configuration"
    assert "top-secret" not in repr(caught.value)


def test_catalog_rejects_duplicate_task_assignments() -> None:
    with pytest.raises(SqlRunnerError, match="^unsafe_configuration$"):
        SqlExerciseCatalog(exercises=(exercise(), exercise(key="other")), dsns={})


def test_missing_configuration_is_disabled_with_no_application_fallback() -> None:
    catalog = SqlExerciseCatalog.from_env({"DATABASE_URL": "postgresql://postgres:secret@db/app"})
    assert not catalog.enabled
    with pytest.raises(SqlRunnerError, match="^disabled$"):
        catalog.resolve("fixture.sql.support-counts")


def test_env_catalog_is_strict_and_secrets_are_separate(tmp_path) -> None:
    path = tmp_path / "catalog.json"
    payload = {"catalog_version": 1, "exercises": [exercise().model_dump(mode="json")]}
    path.write_text(json.dumps(payload))
    env = {
        "TAMFORGE_SQL_EXERCISE_CATALOG": str(path),
        "TAMFORGE_SQL_EXERCISE_DSNS": json.dumps(
            {
                "support_counts": "postgresql://tamforge_learning_runner_support:secret@localhost/learning"
            }
        ),
    }
    assert SqlExerciseCatalog.from_env(env).resolve("fixture.sql.support-counts") == exercise()
    path.write_text(json.dumps({**payload, "dsn": "secret"}))
    with pytest.raises(SqlRunnerError, match="^unsafe_configuration$"):
        SqlExerciseCatalog.from_env(env)
    path.write_text('{"catalog_version":1,"catalog_version":1,"exercises":[]}')
    with pytest.raises(SqlRunnerError, match="^unsafe_configuration$"):
        SqlExerciseCatalog.from_env(env)


def test_catalog_version_must_be_integer_not_boolean(tmp_path) -> None:
    path = tmp_path / "catalog.json"
    path.write_text(
        json.dumps(
            {
                "catalog_version": True,
                "exercises": [exercise().model_dump(mode="json")],
            }
        )
    )
    with pytest.raises(SqlRunnerError, match="^unsafe_configuration$"):
        SqlExerciseCatalog.from_env(
            {
                "TAMFORGE_SQL_EXERCISE_CATALOG": str(path),
                "TAMFORGE_SQL_EXERCISE_DSNS": json.dumps(
                    {
                        "support_counts": "postgresql://tamforge_learning_runner_support:secret@localhost/learning"
                    }
                ),
            }
        )


def test_decimal_precision_does_not_depend_on_ambient_context() -> None:
    result = build_sql_result(
        exercise(),
        ("account_id", "ticket_count"),
        (("a", Decimal("123456789012345678901234567890.123456789")),),
        0,
    )
    assert result.rows == (("a", "123456789012345678901234567890.123456789"),)


def test_exact_maximum_rows_and_canonical_bytes_are_accepted() -> None:
    result = build_sql_result(
        exercise(), ("account_id", "ticket_count"), ((str(i), i) for i in range(1000)), 0
    )
    assert result.row_count == 1000
    # Independently counted JSON envelope: 59 bytes including the empty value.
    cell = "x" * (262144 - 59)
    result = build_sql_result(exercise(), ("account_id", "ticket_count"), (("a", cell),), 0)
    assert result.rows == (("a", cell),)
    with pytest.raises(SqlRunnerError, match="^result_too_large$"):
        build_sql_result(exercise(), ("account_id", "ticket_count"), (("a", cell + "x"),), 0)


def test_oversized_cell_stops_before_normalizing_remaining_row() -> None:
    with pytest.raises(SqlRunnerError, match="^result_too_large$"):
        build_sql_result(exercise(), ("account_id", "ticket_count"), (("é" * 131072, object()),), 0)

"""Frozen SQL exercise/result contracts, independent of database transport."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import date, datetime, time
from decimal import Decimal
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_QUERY_BYTES = 64 * 1024
MAX_RESULT_BYTES = 256 * 1024
MAX_ROWS = 1000
MAX_COLUMNS = 32
Identifier = Annotated[str, Field(pattern=r"^[a-z_][a-z0-9_]{0,62}$")]
Cell = str | None
Row = tuple[Cell, ...]
ErrorCode = Literal[
    "disabled",
    "unknown_exercise",
    "unsafe_configuration",
    "unavailable",
    "busy",
    "timeout",
    "invalid_query",
    "rejected_query",
    "invalid_result",
    "result_too_large",
]
_ERROR_CODES = frozenset(
    {
        "disabled",
        "unknown_exercise",
        "unsafe_configuration",
        "unavailable",
        "busy",
        "timeout",
        "invalid_query",
        "rejected_query",
        "invalid_result",
        "result_too_large",
    }
)


class SqlRunnerError(Exception):
    """Only a closed reason code may cross the workspace boundary."""

    def __init__(self, code: ErrorCode) -> None:
        self.code: ErrorCode = code if code in _ERROR_CODES else "unavailable"
        super().__init__(self.code)


def canonical_result_bytes(columns: Sequence[str], rows: Sequence[Row]) -> bytes:
    return json.dumps(
        {"columns": columns, "rows": rows},
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _json_bytes(value: object) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode(
            "utf-8"
        )
    except (ValueError, TypeError, UnicodeError):
        raise SqlRunnerError("invalid_result") from None


def _normalize(value: object) -> Cell:
    if value is None:
        return None
    if isinstance(value, str):
        result = value
    elif isinstance(value, bool):
        result = "true" if value else "false"
    elif isinstance(value, int):
        try:
            result = str(value)
        except ValueError:
            raise SqlRunnerError("invalid_result") from None
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise SqlRunnerError("invalid_result")
        result = str(value)
    elif isinstance(value, Decimal):
        if not value.is_finite():
            raise SqlRunnerError("invalid_result")
        # Bound fixed-point expansion before allocating it; never round through
        # Decimal.normalize(), which depends on the ambient decimal context.
        if abs(value.as_tuple().exponent) > MAX_RESULT_BYTES:  # type: ignore[arg-type]
            raise SqlRunnerError("result_too_large")
        result = format(value, "f")
        if "." in result:
            result = result.rstrip("0").rstrip(".")
        if value == 0:
            result = "0"
    elif isinstance(value, (datetime, date, time)):
        result = value.isoformat()
    elif isinstance(value, UUID):
        result = str(value)
    else:
        raise SqlRunnerError("invalid_result")
    if len(result) > MAX_RESULT_BYTES:
        raise SqlRunnerError("result_too_large")
    return result


class ResultRows:
    """Incremental canonical-byte accounting; never silently truncate a result."""

    def __init__(self, columns: Sequence[str]) -> None:
        self.columns = tuple(columns)
        if len(self.columns) > MAX_COLUMNS:
            raise SqlRunnerError("result_too_large")
        if (
            not self.columns
            or any(not isinstance(c, str) or not c or len(c) > 63 for c in self.columns)
            or len(set(self.columns)) != len(self.columns)
        ):
            raise SqlRunnerError("invalid_result")
        self.rows: list[Row] = []
        self._size = len(_json_bytes({"columns": self.columns, "rows": []}))

    def append(self, values: Sequence[object]) -> None:
        if len(self.rows) >= MAX_ROWS:
            raise SqlRunnerError("result_too_large")
        if len(values) != len(self.columns):
            raise SqlRunnerError("invalid_result")
        cells: list[Cell] = []
        row_size = 2 + bool(self.rows)  # Brackets and the preceding row separator.
        for value in values:
            cell = _normalize(value)
            row_size += len(_json_bytes(cell)) + bool(cells)
            if self._size + row_size > MAX_RESULT_BYTES:
                raise SqlRunnerError("result_too_large")
            cells.append(cell)
        self._size += row_size
        self.rows.append(tuple(cells))


def _wrong_grain(columns: tuple[str, ...], rows: Sequence[Row], grain: tuple[str, ...]) -> bool:
    indices = tuple(columns.index(name) for name in grain)
    seen: set[Row] = set()
    for row in rows:
        key = tuple(row[index] for index in indices)
        if None in key or key in seen:
            return True
        seen.add(key)
    return False


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True, hide_input_in_errors=True)


class SqlExercise(_FrozenModel):
    key: Identifier
    version: Annotated[int, Field(gt=0)]
    schema_name: Identifier
    role_name: Identifier
    task_stable_ids: Annotated[
        tuple[Annotated[str, Field(min_length=1, max_length=256, pattern=r"^[a-z0-9_.-]+$")], ...],
        Field(min_length=1, max_length=1000),
    ]
    columns: Annotated[tuple[Identifier, ...], Field(min_length=1, max_length=MAX_COLUMNS)]
    expected_rows: Annotated[tuple[Row, ...], Field(max_length=MAX_ROWS)]
    grain_columns: Annotated[tuple[Identifier, ...], Field(min_length=1, max_length=MAX_COLUMNS)]
    ordered: bool

    @model_validator(mode="after")
    def validate_exercise(self) -> Self:
        if self.schema_name.startswith("pg_") or self.schema_name in {
            "public",
            "information_schema",
        }:
            raise ValueError("reserved exercise schema")
        if self.role_name.startswith("pg_") or self.role_name in {"postgres", "public"}:
            raise ValueError("reserved exercise role")
        if (
            len(set(self.task_stable_ids)) != len(self.task_stable_ids)
            or len(set(self.grain_columns)) != len(self.grain_columns)
            or not set(self.grain_columns).issubset(self.columns)
        ):
            raise ValueError("invalid exercise mapping or grain")
        try:
            bounded = ResultRows(self.columns)
            for row in self.expected_rows:
                bounded.append(row)
            if _wrong_grain(self.columns, self.expected_rows, self.grain_columns):
                raise ValueError("invalid expected grain")
        except SqlRunnerError:
            raise ValueError("invalid expected result") from None
        return self


class SqlResult(_FrozenModel):
    columns: tuple[str, ...]
    rows: tuple[Row, ...]
    elapsed_ms: Annotated[int, Field(ge=0)]
    row_count: Annotated[int, Field(ge=0, le=MAX_ROWS)]
    result_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    validation: Literal["matched", "mismatch", "wrong_grain"]
    exercise_key: Identifier
    exercise_version: Annotated[int, Field(gt=0)]

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        try:
            bounded = ResultRows(self.columns)
            for row in self.rows:
                bounded.append(row)
        except SqlRunnerError:
            raise ValueError("invalid bounded result") from None
        if (
            self.row_count != len(self.rows)
            or self.result_sha256
            != hashlib.sha256(canonical_result_bytes(self.columns, self.rows)).hexdigest()
        ):
            raise ValueError("invalid result integrity")
        return self


def build_sql_result(
    exercise: SqlExercise,
    columns: Sequence[str],
    rows: Iterable[Sequence[object]],
    elapsed_ms: int,
) -> SqlResult:
    bounded = ResultRows(columns)
    for row in rows:
        bounded.append(row)
    result_rows = tuple(bounded.rows)
    validation: Literal["matched", "mismatch", "wrong_grain"] = "mismatch"
    if set(exercise.grain_columns).issubset(bounded.columns) and _wrong_grain(
        bounded.columns,
        result_rows,
        exercise.grain_columns,
    ):
        validation = "wrong_grain"
    elif bounded.columns == exercise.columns and (
        result_rows == exercise.expected_rows
        if exercise.ordered
        else Counter(result_rows) == Counter(exercise.expected_rows)
    ):
        validation = "matched"
    if type(elapsed_ms) is not int or elapsed_ms < 0:
        raise SqlRunnerError("invalid_result")
    return SqlResult(
        columns=bounded.columns,
        rows=result_rows,
        elapsed_ms=elapsed_ms,
        row_count=len(result_rows),
        validation=validation,
        exercise_key=exercise.key,
        exercise_version=exercise.version,
        result_sha256=hashlib.sha256(
            canonical_result_bytes(bounded.columns, result_rows)
        ).hexdigest(),
    )

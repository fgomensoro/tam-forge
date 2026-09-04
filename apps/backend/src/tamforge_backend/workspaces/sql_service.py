"""Transactional policy and immutable response reconstruction for SQL runs."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import transaction_scope
from ..learning.models import ActivityInstance
from ..roadmaps.models import TaskDefinition
from .models import SqlExecution
from .sql_contracts import (
    MAX_QUERY_BYTES,
    MAX_RESULT_BYTES,
    SqlExercise,
    SqlResult,
    SqlRunnerError,
    canonical_result_bytes,
)
from .sql_runner import SqlRunner
from .sql_settings import SqlExerciseCatalog

MAX_HISTORY_ITEMS = 20
MAX_HISTORY_BYTES = 1024 * 1024
_SAFE_IDEMPOTENCY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True, hide_input_in_errors=True)


class SqlExecutionCommand(_FrozenModel):
    expected_version: Annotated[int, Field(gt=0)]
    query: Annotated[str, Field(max_length=MAX_QUERY_BYTES)]

    @model_validator(mode="after")
    def validate_query(self) -> Self:
        try:
            valid = (
                bool(self.query.strip())
                and "\x00" not in self.query
                and len(self.query) <= MAX_QUERY_BYTES
                and len(self.query.encode("utf-8")) <= MAX_QUERY_BYTES
            )
        except UnicodeError:
            valid = False
        if not valid:
            raise ValueError("query is invalid")
        return self


class SqlExecutionResponse(_FrozenModel):
    execution_id: Annotated[int, Field(gt=0)]
    activity_id: Annotated[int, Field(gt=0)]
    query: Annotated[str, Field(max_length=MAX_QUERY_BYTES)]
    query_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    result: SqlResult

    @model_validator(mode="after")
    def validate_query_integrity(self) -> Self:
        try:
            valid = (
                bool(self.query.strip())
                and "\x00" not in self.query
                and len(self.query.encode("utf-8")) <= MAX_QUERY_BYTES
                and hashlib.sha256(self.query.encode("utf-8")).hexdigest()
                == self.query_sha256
            )
        except UnicodeError:
            valid = False
        if not valid:
            raise ValueError("query integrity is invalid")
        return self


class SqlExecutionHistory(_FrozenModel):
    items: Annotated[tuple[SqlExecutionResponse, ...], Field(max_length=MAX_HISTORY_ITEMS)]


class SqlExecutionError(Exception):
    """Base error safe for closed HTTP problem mapping."""


class SqlExecutionNotFound(SqlExecutionError):
    """The owner-scoped activity does not exist."""


class SqlExecutionConflict(SqlExecutionError):
    """The activity state, version, or idempotent request conflicts."""


class SqlExecutionInvalid(SqlExecutionError):
    """The submitted query or executor result is invalid."""


class SqlExecutionBusy(SqlExecutionError):
    """The process runner has no execution capacity."""


class SqlExecutionUnavailable(SqlExecutionError):
    """Private SQL execution resources are unavailable."""


class SqlExecutionService:
    """Execute and persist one owner-scoped SQL receipt per transaction."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        catalog: SqlExerciseCatalog | None,
        runner: SqlRunner | None,
    ) -> None:
        self._session = session
        self._catalog = catalog
        self._runner = runner

    async def execute(
        self,
        owner_id: int,
        activity_id: int,
        command: SqlExecutionCommand,
        idempotency_key: str,
    ) -> SqlExecutionResponse:
        self._validate_identity(owner_id, activity_id)
        self._validate_idempotency_key(idempotency_key)
        request_digest = self._request_digest(activity_id, command)
        try:
            async with transaction_scope(self._session):
                activity, definition = await self._load_activity(
                    owner_id=owner_id,
                    activity_id=activity_id,
                    lock=True,
                )
                duplicate = await self._find_receipt(
                    owner_id=owner_id,
                    activity_id=activity_id,
                    idempotency_key=idempotency_key,
                )
                if duplicate is not None:
                    if not hmac.compare_digest(duplicate.request_digest, request_digest):
                        raise SqlExecutionConflict("idempotency key belongs to another request")
                    return self._response(duplicate)

                if activity.state != "active":
                    raise SqlExecutionConflict("activity is not active")
                if activity.optimistic_version != command.expected_version:
                    raise SqlExecutionConflict("stale activity version")
                if definition.block != "sql":
                    raise SqlExecutionConflict("activity is not a SQL activity")
                if self._catalog is None or self._runner is None:
                    raise SqlExecutionUnavailable("SQL execution is unavailable")
                try:
                    exercise = self._catalog.resolve(activity.task_stable_id_snapshot)
                except SqlRunnerError as exc:
                    raise self._mapped_runner_error(exc) from None
                result = await self._run(exercise, command.query)
                if (
                    result.exercise_key != exercise.key
                    or result.exercise_version != exercise.version
                ):
                    raise SqlExecutionInvalid("executor result exercise does not match")
                canonical = canonical_result_bytes(result.columns, result.rows)
                if len(canonical) > MAX_RESULT_BYTES:
                    raise SqlExecutionInvalid("executor result exceeds its bound")
                query_bytes = command.query.encode("utf-8")
                receipt = SqlExecution(
                    owner_id=owner_id,
                    activity_instance_id=activity_id,
                    task_stable_id_snapshot=activity.task_stable_id_snapshot,
                    task_mapping_version_snapshot=activity.task_mapping_version_snapshot,
                    exercise_key=exercise.key,
                    exercise_version=exercise.version,
                    query=command.query,
                    query_sha256=hashlib.sha256(query_bytes).digest(),
                    canonical_result_json=canonical.decode("utf-8"),
                    result_sha256=bytes.fromhex(result.result_sha256),
                    elapsed_ms=result.elapsed_ms,
                    row_count=result.row_count,
                    validation=result.validation,
                    idempotency_key=idempotency_key,
                    request_digest=request_digest,
                )
                self._session.add(receipt)
                await self._session.flush()
                return self._response(receipt)
        except SqlExecutionError:
            raise
        except (SQLAlchemyError, UnicodeError, ValueError, TypeError):
            raise SqlExecutionUnavailable("SQL execution persistence is unavailable") from None

    async def history(self, owner_id: int, activity_id: int) -> SqlExecutionHistory:
        self._validate_identity(owner_id, activity_id)
        try:
            activity_exists = await self._session.scalar(
                select(ActivityInstance.id)
                .where(ActivityInstance.owner_id == owner_id)
                .where(ActivityInstance.id == activity_id)
            )
            if activity_exists is None:
                raise SqlExecutionNotFound("activity was not found")
            receipts = (
                (
                    await self._session.execute(
                        select(SqlExecution)
                        .where(SqlExecution.owner_id == owner_id)
                        .where(SqlExecution.activity_instance_id == activity_id)
                        .order_by(SqlExecution.created_at.desc(), SqlExecution.id.desc())
                        .limit(MAX_HISTORY_ITEMS)
                    )
                )
                .scalars()
                .all()
            )
            items: list[SqlExecutionResponse] = []
            for receipt in receipts:
                candidate = SqlExecutionHistory(items=tuple((*items, self._response(receipt))))
                if len(candidate.model_dump_json().encode("utf-8")) > MAX_HISTORY_BYTES:
                    break
                items = list(candidate.items)
            return SqlExecutionHistory(items=tuple(items))
        except SqlExecutionError:
            raise
        except (SQLAlchemyError, UnicodeError, ValueError, TypeError, ValidationError):
            raise SqlExecutionUnavailable("SQL execution history is unavailable") from None
        finally:
            await self._session.rollback()

    async def _load_activity(
        self, *, owner_id: int, activity_id: int, lock: bool
    ) -> tuple[ActivityInstance, TaskDefinition]:
        statement = (
            select(ActivityInstance, TaskDefinition)
            .join(
                TaskDefinition,
                (TaskDefinition.owner_id == ActivityInstance.owner_id)
                & (TaskDefinition.id == ActivityInstance.task_definition_id),
            )
            .where(ActivityInstance.owner_id == owner_id)
            .where(ActivityInstance.id == activity_id)
        )
        if lock:
            statement = statement.with_for_update(of=ActivityInstance)
        row = (await self._session.execute(statement)).first()
        if row is None:
            raise SqlExecutionNotFound("activity was not found")
        return row[0], row[1]

    async def _find_receipt(
        self, *, owner_id: int, activity_id: int, idempotency_key: str
    ) -> SqlExecution | None:
        return (
            await self._session.execute(
                select(SqlExecution)
                .where(SqlExecution.owner_id == owner_id)
                .where(SqlExecution.activity_instance_id == activity_id)
                .where(SqlExecution.idempotency_key == idempotency_key)
            )
        ).scalar_one_or_none()

    async def _run(self, exercise: SqlExercise, query: str) -> SqlResult:
        assert self._runner is not None
        try:
            raw = await self._runner.run(exercise, query)
            return SqlResult.model_validate(raw.model_dump())
        except SqlRunnerError as exc:
            raise self._mapped_runner_error(exc) from None
        except (ValidationError, AttributeError, TypeError, ValueError):
            raise SqlExecutionInvalid("executor returned an invalid result") from None
        except Exception:
            raise SqlExecutionUnavailable("SQL executor is unavailable") from None

    @staticmethod
    def _mapped_runner_error(error: SqlRunnerError) -> SqlExecutionError:
        if error.code == "busy":
            return SqlExecutionBusy("SQL execution capacity is busy")
        if error.code in {
            "invalid_query",
            "rejected_query",
            "invalid_result",
            "result_too_large",
        }:
            return SqlExecutionInvalid("SQL execution request is invalid")
        return SqlExecutionUnavailable("SQL execution is unavailable")

    @staticmethod
    def _request_digest(activity_id: int, command: SqlExecutionCommand) -> bytes:
        payload = json.dumps(
            {
                "activity_id": activity_id,
                "expected_version": command.expected_version,
                "query": command.query,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(payload).digest()

    @staticmethod
    def _validate_identity(owner_id: int, activity_id: int) -> None:
        if (
            type(owner_id) is not int
            or owner_id <= 0
            or type(activity_id) is not int
            or activity_id <= 0
        ):
            raise SqlExecutionNotFound("activity was not found")

    @staticmethod
    def _validate_idempotency_key(idempotency_key: str) -> None:
        if not isinstance(idempotency_key, str) or not _SAFE_IDEMPOTENCY.fullmatch(
            idempotency_key
        ):
            raise SqlExecutionInvalid("idempotency key is invalid")

    @staticmethod
    def _response(receipt: SqlExecution) -> SqlExecutionResponse:
        try:
            payload = json.loads(receipt.canonical_result_json)
            if not isinstance(payload, dict) or set(payload) != {"columns", "rows"}:
                raise ValueError("invalid result payload")
            raw_columns = payload["columns"]
            raw_rows = payload["rows"]
            if not isinstance(raw_columns, list) or not isinstance(raw_rows, list):
                raise ValueError("invalid result payload")
            columns = tuple(raw_columns)
            rows = tuple(tuple(row) for row in raw_rows)
            canonical = canonical_result_bytes(columns, rows)
            query_bytes = receipt.query.encode("utf-8")
            if (
                canonical != receipt.canonical_result_json.encode("utf-8")
                or not hmac.compare_digest(
                    hashlib.sha256(canonical).digest(), receipt.result_sha256
                )
                or not hmac.compare_digest(
                    hashlib.sha256(query_bytes).digest(), receipt.query_sha256
                )
            ):
                raise ValueError("receipt integrity mismatch")
            result = SqlResult(
                columns=columns,
                rows=rows,
                elapsed_ms=receipt.elapsed_ms,
                row_count=receipt.row_count,
                result_sha256=receipt.result_sha256.hex(),
                validation=receipt.validation,  # type: ignore[arg-type]
                exercise_key=receipt.exercise_key,
                exercise_version=receipt.exercise_version,
            )
            return SqlExecutionResponse(
                execution_id=receipt.id,
                activity_id=receipt.activity_instance_id,
                query=receipt.query,
                query_sha256=receipt.query_sha256.hex(),
                result=result,
            )
        except (KeyError, TypeError, ValueError, UnicodeError, ValidationError):
            raise SqlExecutionUnavailable("stored SQL receipt is invalid") from None


__all__ = [
    "MAX_HISTORY_BYTES",
    "MAX_HISTORY_ITEMS",
    "SqlExecutionBusy",
    "SqlExecutionCommand",
    "SqlExecutionConflict",
    "SqlExecutionError",
    "SqlExecutionHistory",
    "SqlExecutionInvalid",
    "SqlExecutionNotFound",
    "SqlExecutionResponse",
    "SqlExecutionService",
    "SqlExecutionUnavailable",
]

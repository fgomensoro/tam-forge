"""Owner-scoped immutable receipts for SQL workspace executions."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    LargeBinary,
    Text,
    UniqueConstraint,
    event,
    func,
    inspect,
)
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Mapped, Mapper, mapped_column
from sqlalchemy.orm.base import LoaderCallableStatus

from ..models.base import Base, utc_now


class AppendOnlySqlExecutionError(ValueError):
    """Raised when an immutable SQL execution receipt is changed."""


class SqlExecution(Base):
    """One complete result bound to its owner, activity, query, and exercise."""

    __tablename__ = "sql_executions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "activity_instance_id"],
            ["activity_instances.owner_id", "activity_instances.id"],
            name="fk_sql_executions_owner_activity_activity_instances",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "owner_id",
            "activity_instance_id",
            "idempotency_key",
            name="uq_sql_executions_owner_activity_idempotency",
        ),
        CheckConstraint(
            "btrim(task_stable_id_snapshot) <> '' AND "
            "octet_length(task_stable_id_snapshot) <= 192",
            name="task_stable_id_snapshot_bounded",
        ),
        CheckConstraint(
            "btrim(task_mapping_version_snapshot) <> '' AND "
            "octet_length(task_mapping_version_snapshot) <= 64",
            name="task_mapping_version_snapshot_bounded",
        ),
        CheckConstraint(
            "exercise_key ~ '^[a-z_][a-z0-9_]{0,62}$'",
            name="exercise_key_shape",
        ),
        CheckConstraint("exercise_version > 0", name="exercise_version_positive"),
        CheckConstraint(
            "btrim(query) <> '' AND octet_length(query) <= 65536",
            name="query_bounded",
        ),
        CheckConstraint("octet_length(query_sha256) = 32", name="query_sha256_length"),
        CheckConstraint(
            "query_sha256 = public.digest(pg_catalog.convert_to(query, 'UTF8'), 'sha256')",
            name="query_sha256_matches",
        ),
        CheckConstraint(
            "octet_length(canonical_result_json) <= 262144",
            name="canonical_result_json_bounded",
        ),
        CheckConstraint(
            "jsonb_typeof(canonical_result_json::jsonb) = 'object' AND "
            "canonical_result_json::jsonb ?& ARRAY['columns', 'rows'] AND "
            "canonical_result_json::jsonb - 'columns' - 'rows' = '{}'::jsonb AND "
            "jsonb_typeof(canonical_result_json::jsonb->'columns') = 'array' AND "
            "jsonb_array_length(canonical_result_json::jsonb->'columns') BETWEEN 1 AND 32 AND "
            "jsonb_typeof(canonical_result_json::jsonb->'rows') = 'array'",
            name="canonical_result_shape",
        ),
        CheckConstraint("octet_length(result_sha256) = 32", name="result_sha256_length"),
        CheckConstraint(
            "result_sha256 = public.digest("
            "pg_catalog.convert_to(canonical_result_json, 'UTF8'), 'sha256')",
            name="result_sha256_matches",
        ),
        CheckConstraint("elapsed_ms >= 0", name="elapsed_ms_nonnegative"),
        CheckConstraint("row_count BETWEEN 0 AND 1000", name="row_count_bounded"),
        CheckConstraint(
            "row_count = jsonb_array_length(canonical_result_json::jsonb->'rows')",
            name="row_count_matches",
        ),
        CheckConstraint(
            "validation IN ('matched', 'mismatch', 'wrong_grain')",
            name="validation_allowed",
        ),
        CheckConstraint(
            "idempotency_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'",
            name="idempotency_key_bounded",
        ),
        CheckConstraint("octet_length(request_digest) = 32", name="request_digest_length"),
        Index(
            "ix_sql_executions_owner_activity_created",
            "owner_id",
            "activity_instance_id",
            "created_at",
            "id",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    activity_instance_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    task_stable_id_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    task_mapping_version_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    exercise_key: Mapped[str] = mapped_column(Text, nullable=False)
    exercise_version: Mapped[int] = mapped_column(Integer, nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    query_sha256: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    canonical_result_json: Mapped[str] = mapped_column(Text, nullable=False)
    result_sha256: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    elapsed_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    validation: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    request_digest: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )


def _reject_sql_execution_attribute_change(
    target: SqlExecution,
    value: object,
    old_value: object,
    initiator: object,
) -> object:
    del initiator
    state = inspect(target)
    if (
        (state.persistent or state.detached)
        and old_value is not LoaderCallableStatus.NO_VALUE
        and value != old_value
    ):
        raise AppendOnlySqlExecutionError("SQL execution receipts are immutable")
    return value


for _mapped_attribute in inspect(SqlExecution).column_attrs:
    event.listen(
        getattr(SqlExecution, _mapped_attribute.key),
        "set",
        _reject_sql_execution_attribute_change,
        retval=True,
        active_history=True,
    )


def reject_sql_execution_update(
    mapper: Mapper[SqlExecution] | None,
    connection: Connection | None,
    target: SqlExecution,
) -> None:
    del mapper, connection, target
    raise AppendOnlySqlExecutionError("SQL execution receipts are immutable")


def reject_sql_execution_delete(
    mapper: Mapper[SqlExecution] | None,
    connection: Connection | None,
    target: SqlExecution,
) -> None:
    del mapper, connection, target
    raise AppendOnlySqlExecutionError("SQL execution receipts are immutable")


event.listen(SqlExecution, "before_update", reject_sql_execution_update)
event.listen(SqlExecution, "before_delete", reject_sql_execution_delete)


__all__ = [
    "AppendOnlySqlExecutionError",
    "SqlExecution",
    "reject_sql_execution_delete",
    "reject_sql_execution_update",
]

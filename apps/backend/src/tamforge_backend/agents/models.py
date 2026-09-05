"""Append-only provenance rows; canonical_json is the complete hashed byte domain."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Integer,
    LargeBinary,
    Text,
    UniqueConstraint,
    event,
    func,
)
from sqlalchemy.orm import Mapped, make_transient_to_detached, mapped_column

from ..models.base import Base
from .contracts import ImmutableVersionConflict


class Record(Base):
    __abstract__ = True
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("owners.id"), nullable=False)
    canonical_json: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    hash_format: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


def _checks(table: str, *, prompt: bool = False, limit: int = 262144) -> tuple[Any, ...]:
    checks: tuple[Any, ...] = (
        UniqueConstraint("owner_id", "id", name=f"uq_{table}_owner_id_id"),
        CheckConstraint("id > 0", name="id_positive"),
        CheckConstraint("owner_id > 0", name="owner_positive"),
        CheckConstraint("hash_format = 1", name="hash_format_v1"),
        CheckConstraint(
            f"octet_length(canonical_json) BETWEEN 1 AND {limit}", name="content_bounded"
        ),
        CheckConstraint(
            "content_hash = public.digest(convert_to(canonical_json, 'UTF8'), 'sha256')",
            name="hash_matches",
        ),
    )
    if not prompt:
        checks += (
            CheckConstraint(
                "canonical_json = public.tamforge_provenance_canonical(canonical_json::jsonb)",
                name="canonical_bytes",
            ),
        )
    return checks


class PromptVersion(Record):
    __tablename__ = "prompt_versions"
    __table_args__ = _checks("prompt_versions", prompt=True, limit=1048576) + (
        UniqueConstraint("owner_id", "key", "version", name="uq_prompt_versions_key_version"),
        CheckConstraint(
            "key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$' AND "
            "version ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'",
            name="keys_safe",
        ),
    )
    key: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(Text, nullable=False)


class OutputSchemaVersion(Record):
    __tablename__ = "output_schema_versions"
    __table_args__ = _checks("output_schema_versions", limit=1048576) + (
        UniqueConstraint(
            "owner_id", "key", "version", name="uq_output_schema_versions_key_version"
        ),
        CheckConstraint(
            "key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$' AND "
            "version ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'",
            name="keys_safe",
        ),
        CheckConstraint(
            "jsonb_typeof(canonical_json::jsonb) = 'object' AND "
            "canonical_json::jsonb->>'$id' = key IS TRUE",
            name="schema_identity",
        ),
    )
    key: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(Text, nullable=False)


def _id_expression(key: str) -> Computed:
    return Computed(f"(canonical_json::jsonb->>'{key}')::bigint", persisted=True)


def _pin_expression(key: str) -> Computed:
    return Computed(f"(canonical_json::jsonb->'{key}'->>'id')::bigint", persisted=True)


class RubricVersionHash(Record):
    __tablename__ = "rubric_version_hashes"
    __table_args__ = _checks(
        "rubric_version_hashes",
    ) + (
        UniqueConstraint("owner_id", "rubric_id", name="uq_rubric_version_hashes_rubric"),
        ForeignKeyConstraint(
            ["owner_id", "config_id", "rubric_id"],
            [
                "rubric_versions.owner_id",
                "rubric_versions.config_seed_version_id",
                "rubric_versions.id",
            ],
        ),
    )
    config_id: Mapped[int] = mapped_column(BigInteger, _id_expression("config_id"), nullable=False)
    rubric_id: Mapped[int] = mapped_column(BigInteger, _id_expression("rubric_id"), nullable=False)


class ModelRun(Record):
    __tablename__ = "model_runs"
    __table_args__ = _checks(
        "model_runs",
    ) + (
        UniqueConstraint("owner_id", "invocation_key", name="uq_model_runs_invocation"),
        UniqueConstraint("owner_id", "activity_id", "id", name="uq_model_runs_activity_id"),
        ForeignKeyConstraint(
            ["owner_id", "activity_id", "attempt_id"],
            ["attempts.owner_id", "attempts.activity_instance_id", "attempts.id"],
            name="fk_model_runs_attempt",
        ),
        ForeignKeyConstraint(
            ["owner_id", "prompt_id"],
            ["prompt_versions.owner_id", "prompt_versions.id"],
            name="fk_model_runs_prompt",
        ),
        ForeignKeyConstraint(
            ["owner_id", "schema_id"],
            ["output_schema_versions.owner_id", "output_schema_versions.id"],
            name="fk_model_runs_schema",
        ),
        ForeignKeyConstraint(
            ["owner_id", "rubric_binding_id"],
            ["rubric_version_hashes.owner_id", "rubric_version_hashes.id"],
            name="fk_model_runs_rubric",
        ),
        ForeignKeyConstraint(
            ["owner_id", "job_id"],
            ["background_jobs.owner_id", "background_jobs.id"],
            name="fk_model_runs_job",
        ),
        ForeignKeyConstraint(
            ["owner_id", "activity_id", "predecessor_id"],
            ["model_runs.owner_id", "model_runs.activity_id", "model_runs.id"],
            name="fk_model_runs_predecessor",
        ),
    )
    invocation_key: Mapped[str] = mapped_column(
        Text, Computed("canonical_json::jsonb->>'invocation_key'", persisted=True), nullable=False
    )
    activity_id: Mapped[int] = mapped_column(
        BigInteger, _id_expression("activity_id"), nullable=False
    )
    attempt_id: Mapped[int] = mapped_column(BigInteger, _pin_expression("attempt"), nullable=False)
    prompt_id: Mapped[int] = mapped_column(BigInteger, _pin_expression("prompt"), nullable=False)
    schema_id: Mapped[int] = mapped_column(
        BigInteger, _pin_expression("schema_version"), nullable=False
    )
    rubric_binding_id: Mapped[int] = mapped_column(
        BigInteger, _pin_expression("rubric_binding"), nullable=False
    )
    job_id: Mapped[int | None] = mapped_column(BigInteger, _id_expression("job_id"))
    predecessor_id: Mapped[int | None] = mapped_column(BigInteger, _pin_expression("predecessor"))


class RunChild(Record):
    __abstract__ = True
    run_id: Mapped[int] = mapped_column(BigInteger, nullable=False)


def _child_checks(table: str, *, limit: int = 262144) -> tuple[Any, ...]:
    return _checks(table, limit=limit) + (
        ForeignKeyConstraint(["owner_id", "run_id"], ["model_runs.owner_id", "model_runs.id"]),
    )


class ModelRunContextItem(RunChild):
    __tablename__ = "model_run_context_items"
    __table_args__ = _child_checks(
        "model_run_context_items",
    ) + (UniqueConstraint("run_id", "ordinal"),)
    ordinal: Mapped[int] = mapped_column(Integer, _id_expression("ordinal"), nullable=False)


class ModelRunEvent(RunChild):
    __tablename__ = "model_run_events"
    __table_args__ = _child_checks(
        "model_run_events",
    ) + (UniqueConstraint("run_id", "sequence", name="uq_model_run_events_sequence"),)
    sequence: Mapped[int] = mapped_column(Integer, _id_expression("sequence"), nullable=False)


class AgentToolCall(RunChild):
    __tablename__ = "agent_tool_calls"
    __table_args__ = _child_checks("agent_tool_calls", limit=16384) + (
        UniqueConstraint("run_id", "sequence", name="uq_agent_tool_calls_sequence"),
        UniqueConstraint("run_id", "call_key", "phase_slot", name="uq_agent_tool_calls_call_phase"),
    )
    sequence: Mapped[int] = mapped_column(Integer, _id_expression("sequence"), nullable=False)
    call_key: Mapped[str] = mapped_column(
        Text,
        Computed("canonical_json::jsonb->'audit'->>'call_key'", persisted=True),
        nullable=False,
    )
    phase_slot: Mapped[int] = mapped_column(
        Integer,
        Computed(
            "CASE WHEN canonical_json::jsonb->'audit'->>'phase' = 'request' THEN 0 ELSE 1 END",
            persisted=True,
        ),
        nullable=False,
    )


RECORD_TYPES = (
    PromptVersion,
    OutputSchemaVersion,
    RubricVersionHash,
    ModelRun,
    ModelRunContextItem,
    ModelRunEvent,
    AgentToolCall,
)


def reject_mutation(*args: Any, **kwargs: Any) -> None:
    raise ImmutableVersionConflict()


for _model in RECORD_TYPES:
    event.listen(_model, "before_update", reject_mutation)
    event.listen(_model, "before_delete", reject_mutation)


def snapshot_record[R: Record](row: R) -> R:
    """Return loaded provenance independent of later session commits or rollbacks."""
    snapshot = type(row)(
        **{column.key: getattr(row, column.key) for column in row.__table__.columns}
    )
    make_transient_to_detached(snapshot)
    return snapshot

from __future__ import annotations

import importlib.util
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from io import StringIO
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import URL
from sqlalchemy.orm import make_transient_to_detached

MIGRATION_PATH = Path(
    "apps/backend/alembic/versions/20260825_0005_today_read_models.py"
)
EXPECTED_TABLES = {
    "corrections",
    "interviews",
    "activity_processing_statuses",
    "notifications",
    "outbox_events",
    "background_jobs",
    "notification_delivery_cursor",
}
ALLOWED_NOTIFICATION_TYPES = {
    "feedback_ready",
    "correction_due",
    "upcoming_real_interview",
    "saturday_assessment",
    "processing_failure_requires_action",
}


def _load_migration() -> object:
    assert MIGRATION_PATH.exists(), "Today/notification migration must exist"
    spec = importlib.util.spec_from_file_location("today_notification_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_fresh_python(source: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", source],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )


def _offline_sql(direction: str, revision: str) -> str:
    output = StringIO()
    config = Config("apps/backend/alembic.ini", output_buffer=output)
    config.attributes["database_url"] = URL.create(
        "postgresql+psycopg",
        username="tamforge",
        password="offline-today-contract-password",
        host="127.0.0.1",
        port=54329,
        database="tamforge_test",
    ).render_as_string(hide_password=False)
    if direction == "upgrade":
        command.upgrade(config, revision, sql=True)
    else:
        command.downgrade(config, revision, sql=True)
    return output.getvalue()


def _constraint_names(table: sa.Table) -> set[str]:
    return {item.name for item in table.constraints if item.name is not None}


def _index_columns(table: sa.Table) -> dict[str, tuple[str, ...]]:
    return {
        index.name: tuple(column.name for column in index.columns)
        for index in table.indexes
        if index.name is not None
    }


def _detach(instance: object) -> None:
    make_transient_to_detached(instance)


def _job(**overrides: object) -> object:
    from tamforge_backend.notifications.models import BackgroundJob

    now = datetime.now(UTC)
    values: dict[str, object] = {
        "owner_id": 1,
        "kind": "transcribe_activity",
        "payload_schema_version": 1,
        "payload": {"schema_version": 1, "subject_id": 10},
        "priority": 50,
        "state": "queued",
        "idempotency_key": "job-1",
        "available_at": now,
        "attempt_count": 0,
        "max_attempts": 3,
        "lease_owner": None,
        "lease_expires_at": None,
        "last_error_category": None,
        "last_error_details": None,
        "created_at": now,
        "updated_at": now,
        "started_at": None,
        "completed_at": None,
    }
    values.update(overrides)
    return BackgroundJob(**values)


def test_revision_contract_is_exact_and_linear() -> None:
    migration = _load_migration()

    assert migration.revision == "20260825_0005_today_read_models"
    assert migration.down_revision == "20260825_0004_evidence_scoring"
    assert migration.branch_labels is None
    assert migration.depends_on is None


def test_models_register_lazily_without_import_cycles() -> None:
    result = _run_fresh_python(
        "from tamforge_backend.models import Base, load_all_models; "
        "assert not Base.metadata.tables; "
        "load_all_models(); "
        f"assert {EXPECTED_TABLES!r} <= set(Base.metadata.tables)"
    )

    assert result.returncode == 0, result.stderr


def test_models_expose_exact_foundation_columns_and_postgres_json() -> None:
    from tamforge_backend.models import Base, load_all_models

    load_all_models()
    expected_columns = {
        "corrections": {
            "id",
            "owner_id",
            "source_activity_id",
            "source_evidence_event_id",
            "priority",
            "status",
            "due_date",
            "instruction",
            "attempt_b_activity_id",
            "created_at",
            "updated_at",
            "completed_at",
        },
        "interviews": {
            "id",
            "owner_id",
            "company",
            "role",
            "stage",
            "starts_at",
            "expected_duration_minutes",
            "status",
            "privacy_permission_code",
            "created_at",
            "updated_at",
        },
        "activity_processing_statuses": {
            "id",
            "owner_id",
            "activity_instance_id",
            "state",
            "progress_label",
            "last_error_category",
            "last_error_details",
            "created_at",
            "updated_at",
        },
        "notifications": {
            "id",
            "owner_id",
            "notification_type",
            "subject_kind",
            "subject_id",
            "created_at",
            "read_at",
        },
        "outbox_events": {
            "id",
            "owner_id",
            "aggregate_type",
            "aggregate_id",
            "event_type",
            "payload_schema_version",
            "payload",
            "occurred_at",
            "published_at",
            "attempts",
            "idempotency_key",
        },
        "background_jobs": {
            "id",
            "owner_id",
            "kind",
            "payload_schema_version",
            "payload",
            "priority",
            "state",
            "idempotency_key",
            "available_at",
            "attempt_count",
            "max_attempts",
            "lease_owner",
            "lease_expires_at",
            "last_error_category",
            "last_error_details",
            "created_at",
            "updated_at",
            "started_at",
            "completed_at",
        },
        "notification_delivery_cursor": {
            "id",
            "owner_id",
            "stream_key",
            "last_event_id",
            "created_at",
            "updated_at",
        },
    }
    for table_name, columns in expected_columns.items():
        table = Base.metadata.tables[table_name]
        assert set(table.columns.keys()) == columns

    for table_name, column_name in (
        ("activity_processing_statuses", "last_error_details"),
        ("outbox_events", "payload"),
        ("background_jobs", "payload"),
        ("background_jobs", "last_error_details"),
    ):
        assert isinstance(Base.metadata.tables[table_name].c[column_name].type, postgresql.JSONB)


def test_corrections_use_restrictive_owner_scoped_history_links() -> None:
    from tamforge_backend.models import Base, load_all_models

    load_all_models()
    table = Base.metadata.tables["corrections"]
    assert not table.c.source_evidence_event_id.nullable
    targets = {
        tuple(element.parent.name for element in constraint.elements): (
            constraint.referred_table.name,
            tuple(element.column.name for element in constraint.elements),
            constraint.ondelete,
        )
        for constraint in table.foreign_key_constraints
    }

    assert targets[("owner_id", "source_activity_id")] == (
        "activity_instances",
        ("owner_id", "id"),
        "RESTRICT",
    )
    assert targets[("owner_id", "source_evidence_event_id")] == (
        "skill_evidence_events",
        ("owner_id", "id"),
        "RESTRICT",
    )
    assert targets[("owner_id", "attempt_b_activity_id")] == (
        "activity_instances",
        ("owner_id", "id"),
        "RESTRICT",
    )
    assert "uq_skill_evidence_events_owner_id_id" in _constraint_names(
        Base.metadata.tables["skill_evidence_events"]
    )
    assert all(foreign_key.ondelete == "RESTRICT" for foreign_key in table.foreign_keys)


def test_two_correction_slots_are_service_enforced_not_a_global_database_limit() -> None:
    from tamforge_backend.models import Base, load_all_models

    load_all_models()
    table = Base.metadata.tables["corrections"]
    assert _index_columns(table)["ix_corrections_owner_due_status_priority"] == (
        "owner_id",
        "due_date",
        "status",
        "priority",
    )
    assert all(
        not (
            isinstance(constraint, sa.UniqueConstraint)
            and {column.name for column in constraint.columns} >= {
                "owner_id",
                "due_date",
                "priority",
            }
        )
        for constraint in table.constraints
    )
    assert "uq_corrections_owner_source_activity_priority" not in _constraint_names(table)


def test_scheduled_correction_can_be_superseded_without_rewriting_history() -> None:
    from tamforge_backend.today.models import Correction, validate_correction

    now = datetime.now(UTC)
    correction = Correction(
        owner_id=1,
        source_activity_id=1,
        source_evidence_event_id=7,
        priority=1,
        status="scheduled",
        due_date=date.today(),
        instruction="Lead with customer impact.",
        attempt_b_activity_id=2,
        created_at=now,
        updated_at=now,
        completed_at=None,
    )
    _detach(correction)
    correction.status = "superseded"
    correction.updated_at = now + timedelta(seconds=1)
    correction.completed_at = now + timedelta(seconds=1)
    validate_correction(None, None, correction)



def test_correction_slot_service_locks_queries_and_inserts_in_one_transaction() -> None:
    from tamforge_backend.today.service import create_correction_with_slot_reservation

    class _Result:
        def __init__(
            self,
            *,
            rows: list[tuple[int]] | None = None,
            scalar: int | None = None,
        ) -> None:
            self.rows = rows or []
            self.scalar = scalar

        def all(self) -> list[tuple[int]]:
            return self.rows

        def scalar_one(self) -> int:
            assert self.scalar is not None
            return self.scalar

    class _Executor:
        def __init__(self) -> None:
            self.calls: list[tuple[object, object]] = []
            self.results = [_Result(), _Result(rows=[(1,)]), _Result(scalar=42)]

        def execute(self, statement: object, parameters: object = None) -> _Result:
            self.calls.append((statement, parameters))
            return self.results.pop(0)

    executor = _Executor()
    correction_id = create_correction_with_slot_reservation(
        executor,  # type: ignore[arg-type]
        owner_id=7,
        source_activity_id=11,
        source_evidence_event_id=13,
        priority=2,
        due_date=date(2026, 8, 27),
        instruction="Lead with the customer impact.",
    )

    assert correction_id == 42
    assert len(executor.calls) == 3
    assert "pg_advisory_xact_lock" in str(executor.calls[0][0])
    assert "corrections.owner_id" in str(executor.calls[1][0])
    assert "corrections.due_date" in str(executor.calls[1][0])
    assert "corrections.status IN" in str(executor.calls[1][0])
    assert str(executor.calls[2][0]).startswith("INSERT INTO corrections")


def test_correction_slot_service_rejects_third_before_insert() -> None:
    from tamforge_backend.today.service import (
        CorrectionSlotLimitError,
        create_correction_with_slot_reservation,
    )

    class _Result:
        def __init__(self, rows: list[tuple[int]] | None = None) -> None:
            self.rows = rows or []

        def all(self) -> list[tuple[int]]:
            return self.rows

    class _Executor:
        def __init__(self) -> None:
            self.calls: list[object] = []
            self.results = [_Result(), _Result([(1,), (2,)])]

        def execute(self, statement: object, parameters: object = None) -> _Result:
            del parameters
            self.calls.append(statement)
            return self.results.pop(0)

    executor = _Executor()
    with pytest.raises(CorrectionSlotLimitError, match="two active corrections"):
        create_correction_with_slot_reservation(
            executor,  # type: ignore[arg-type]
            owner_id=7,
            source_activity_id=17,
            source_evidence_event_id=19,
            priority=1,
            due_date=date(2026, 8, 27),
            instruction="Use one explicit recommendation.",
        )
    assert len(executor.calls) == 2


def test_interview_foundation_cannot_store_audio_transcript_or_interview_content() -> None:
    from tamforge_backend.models import Base, load_all_models

    load_all_models()
    columns = set(Base.metadata.tables["interviews"].columns.keys())
    prohibited_fragments = {"audio", "transcript", "prompt", "answer", "content", "notes"}
    assert not any(fragment in column for fragment in prohibited_fragments for column in columns)
    assert "privacy_permission_code" in columns


def test_only_approved_notification_types_and_today_query_indexes_exist() -> None:
    from tamforge_backend.models import Base, load_all_models
    from tamforge_backend.notifications.models import NOTIFICATION_TYPES

    load_all_models()
    assert NOTIFICATION_TYPES == ALLOWED_NOTIFICATION_TYPES
    expected_indexes = {
        "corrections": {"ix_corrections_owner_due_status_priority"},
        "interviews": {"ix_interviews_owner_starts_at"},
        "activity_processing_statuses": {"ix_processing_status_owner_state_updated"},
        "notifications": {
            "ix_notifications_owner_created",
            "ix_notifications_owner_unread_created",
        },
        "outbox_events": {"ix_outbox_events_unpublished_occurred"},
        "background_jobs": {"ix_background_jobs_claimable"},
    }
    for table_name, names in expected_indexes.items():
        assert names <= set(_index_columns(Base.metadata.tables[table_name]))

    assert "ix_activity_instances_pending_self_review" in _index_columns(
        Base.metadata.tables["activity_instances"]
    )


def test_idempotency_is_owner_scoped_for_outbox_and_jobs() -> None:
    from tamforge_backend.models import Base, load_all_models

    load_all_models()
    for table_name in ("outbox_events", "background_jobs"):
        unique_shapes = {
            tuple(column.name for column in constraint.columns)
            for constraint in Base.metadata.tables[table_name].constraints
            if isinstance(constraint, sa.UniqueConstraint)
        }
        assert ("owner_id", "idempotency_key") in unique_shapes


def test_structured_payload_contracts_reject_free_text_urls_and_secrets() -> None:
    from tamforge_backend.notifications.models import (
        NotificationContractError,
        validate_error_details_v1,
        validate_reference_payload_v1,
    )

    assert validate_reference_payload_v1({"schema_version": 1, "subject_id": 7})
    assert validate_reference_payload_v1(
        {"schema_version": 1, "subject_id": 2**63 - 1, "related_id": 2**63 - 1}
    )
    assert not validate_reference_payload_v1(
        {"schema_version": 1, "subject_id": 2**63}
    )
    assert not validate_reference_payload_v1(
        {"schema_version": 1, "subject_id": 7, "related_id": 2**63}
    )
    assert validate_reference_payload_v1(
        {"schema_version": 1, "subject_id": 7, "related_id": 9}
    )
    assert validate_error_details_v1(
        {"schema_version": 1, "attempt": 2, "retry_after_seconds": 30}
    )
    for payload in (
        {"schema_version": 1, "subject_id": 7, "message": "raw transcript"},
        {"schema_version": 1, "subject_id": 7, "url": "https://example.com"},
        {"schema_version": 1, "subject_id": 7, "password": "hunter2"},
        {"schema_version": 1, "subject_id": "7"},
        {"schema_version": 2, "subject_id": 7},
    ):
        assert not validate_reference_payload_v1(payload)
    for details in (
        {"schema_version": 1, "message": "source excerpt"},
        {"schema_version": 1, "url": "postgresql://secret"},
        {"schema_version": 1, "token": "secret"},
        {"schema_version": 1, "attempt": -1},
    ):
        assert not validate_error_details_v1(details)

    with pytest.raises(NotificationContractError, match="structured payload"):
        _job(payload={"schema_version": 1, "subject_id": 7, "message": "secret"})


def test_processing_status_transitions_and_error_shape_are_deterministic() -> None:
    from tamforge_backend.today.models import ActivityProcessingStatus, ProcessingWorkflowError

    now = datetime.now(UTC)
    status = ActivityProcessingStatus(
        owner_id=1,
        activity_instance_id=1,
        state="uploaded",
        progress_label="uploaded",
        last_error_category=None,
        last_error_details=None,
        created_at=now,
        updated_at=now,
    )
    _detach(status)
    status.updated_at = now + timedelta(seconds=1)
    status.state = "processing_audio"
    status.progress_label = "processing_audio"

    with pytest.raises(ProcessingWorkflowError, match="transition"):
        status.state = "ready"

    needs_attention = ActivityProcessingStatus(
        owner_id=1,
        activity_instance_id=2,
        state="needs_attention",
        progress_label="action_required",
        last_error_category="transient_dependency",
        last_error_details={"schema_version": 1, "attempt": 1},
        created_at=now,
        updated_at=now,
    )
    _detach(needs_attention)
    needs_attention.updated_at = now + timedelta(seconds=1)
    needs_attention.state = "transcribing"
    needs_attention.progress_label = "transcribing"
    needs_attention.last_error_category = None
    needs_attention.last_error_details = None


def test_correction_requires_committed_attempt_a_source_and_exact_attempt_b_lineage() -> None:
    from tamforge_backend.today.models import (
        Correction,
        CorrectionWorkflowError,
        validate_correction,
    )

    class _Result:
        def __init__(self, value: object) -> None:
            self.value = value

        def one_or_none(self) -> object:
            return self.value

        def scalar_one_or_none(self) -> object:
            return self.value

    class _Connection:
        def __init__(self, results: list[object]) -> None:
            self.results = results

        def execute(self, statement: object) -> _Result:
            del statement
            return _Result(self.results.pop(0))

    now = datetime.now(UTC)
    correction = Correction(
        owner_id=1,
        source_activity_id=1,
        source_evidence_event_id=7,
        priority=1,
        status="pending",
        due_date=date.today(),
        instruction="State the customer impact before implementation detail.",
        attempt_b_activity_id=None,
        created_at=now,
        updated_at=now,
        completed_at=None,
    )

    with pytest.raises(CorrectionWorkflowError, match="source evidence"):
        validate_correction(
            None,
            _Connection([(2, 17, "attempt_a")]),  # type: ignore[arg-type]
            correction,
        )

    with pytest.raises(CorrectionWorkflowError, match="committed Attempt A"):
        validate_correction(
            None,
            _Connection([(1, 17, "attempt_b")]),  # type: ignore[arg-type]
            correction,
        )

    scheduled = Correction(
        owner_id=1,
        source_activity_id=1,
        source_evidence_event_id=7,
        priority=1,
        status="scheduled",
        due_date=date.today(),
        instruction="State the evidence.",
        attempt_b_activity_id=2,
        created_at=now,
        updated_at=now,
        completed_at=None,
    )
    validate_correction(
        None,
        _Connection([(1, 17, "attempt_a"), "attempt_b"]),  # type: ignore[arg-type]
        scheduled,
    )

    completed = Correction(
        owner_id=1,
        source_activity_id=1,
        source_evidence_event_id=7,
        priority=1,
        status="completed",
        due_date=date.today(),
        instruction="State the evidence.",
        attempt_b_activity_id=2,
        created_at=now,
        updated_at=now,
        completed_at=now,
    )
    with pytest.raises(CorrectionWorkflowError, match="parent Attempt A"):
        validate_correction(
            None,
            _Connection([(1, 17, "attempt_a"), "attempt_b", None]),  # type: ignore[arg-type]
            completed,
        )
    validate_correction(
        None,
        _Connection([(1, 17, "attempt_a"), "attempt_b", 23]),  # type: ignore[arg-type]
        completed,
    )

    missing = Correction(
        owner_id=1,
        source_activity_id=1,
        source_evidence_event_id=None,  # type: ignore[arg-type]
        priority=1,
        status="pending",
        due_date=date.today(),
        instruction="State the evidence.",
        attempt_b_activity_id=None,
        created_at=now,
        updated_at=now,
        completed_at=None,
    )
    with pytest.raises(CorrectionWorkflowError, match="source evidence is required"):
        validate_correction(None, None, missing)


def test_job_updates_use_persisted_snapshot_and_are_assignment_order_independent() -> None:
    from tamforge_backend.notifications.models import validate_background_job_update

    class _MappingResult:
        def __init__(self, value: dict[str, object]) -> None:
            self.value = value

        def mappings(self) -> _MappingResult:
            return self

        def one_or_none(self) -> dict[str, object]:
            return self.value

    class _Connection:
        def __init__(self, value: dict[str, object]) -> None:
            self.value = value

        def execute(self, statement: object) -> _MappingResult:
            del statement
            return _MappingResult(self.value)

    def snapshot(job: object) -> dict[str, object]:
        from tamforge_backend.notifications.models import BackgroundJob

        assert isinstance(job, BackgroundJob)
        return {
            column.name: getattr(job, column.name)
            for column in BackgroundJob.__table__.columns
        }

    now = datetime.now(UTC)
    for state_first in (True, False):
        queued = _job(id=1)
        old = snapshot(queued)
        _detach(queued)
        queued.updated_at = now + timedelta(seconds=1)
        if state_first:
            queued.state = "running"
        queued.attempt_count = 1
        queued.lease_owner = "worker-1"
        queued.lease_expires_at = now + timedelta(minutes=1)
        queued.started_at = now + timedelta(seconds=1)
        if not state_first:
            queued.state = "running"
        validate_background_job_update(None, _Connection(old), queued)  # type: ignore[arg-type]

    old_time = now - timedelta(minutes=2)
    for state_first in (True, False):
        running = _job(
            id=2,
            state="running",
            attempt_count=1,
            lease_owner="worker-1",
            lease_expires_at=now - timedelta(minutes=1),
            created_at=old_time,
            updated_at=old_time + timedelta(seconds=1),
            started_at=old_time + timedelta(seconds=1),
        )
        old = snapshot(running)
        _detach(running)
        running.updated_at = now
        if state_first:
            running.state = "queued"
        running.lease_owner = None
        running.lease_expires_at = None
        running.available_at = now + timedelta(seconds=20)
        running.last_error_category = "transient_dependency"
        running.last_error_details = {"schema_version": 1, "attempt": 1}
        if not state_first:
            running.state = "queued"
        validate_background_job_update(None, _Connection(old), running)  # type: ignore[arg-type]

    for state_first in (True, False):
        running = _job(
            id=3,
            state="running",
            attempt_count=1,
            lease_owner="worker-1",
            lease_expires_at=now + timedelta(minutes=1),
            created_at=now - timedelta(seconds=1),
            updated_at=now,
            started_at=now,
        )
        old = snapshot(running)
        _detach(running)
        running.updated_at = now + timedelta(seconds=2)
        if state_first:
            running.state = "succeeded"
        running.lease_owner = None
        running.lease_expires_at = None
        running.completed_at = now + timedelta(seconds=2)
        if not state_first:
            running.state = "succeeded"
        validate_background_job_update(None, _Connection(old), running)  # type: ignore[arg-type]

    heartbeat = _job(
        id=4,
        state="running",
        attempt_count=1,
        lease_owner="worker-1",
        lease_expires_at=now + timedelta(minutes=1),
        created_at=now - timedelta(seconds=1),
        updated_at=now,
        started_at=now,
    )
    old = snapshot(heartbeat)
    _detach(heartbeat)
    heartbeat.updated_at = now + timedelta(seconds=1)
    heartbeat.lease_expires_at = now + timedelta(minutes=2)
    validate_background_job_update(None, _Connection(old), heartbeat)  # type: ignore[arg-type]


def test_job_update_final_rows_reject_invalid_claim_heartbeat_reclaim_and_terminal() -> None:
    from tamforge_backend.notifications.models import (
        BackgroundJob,
        JobWorkflowError,
        validate_background_job_update,
    )

    class _Result:
        def __init__(self, value: dict[str, object]) -> None:
            self.value = value

        def mappings(self) -> _Result:
            return self

        def one_or_none(self) -> dict[str, object]:
            return self.value

    class _Connection:
        def __init__(self, value: dict[str, object]) -> None:
            self.value = value

        def execute(self, statement: object) -> _Result:
            del statement
            return _Result(self.value)

    def snapshot(job: object) -> dict[str, object]:
        assert isinstance(job, BackgroundJob)
        return {
            column.name: getattr(job, column.name)
            for column in BackgroundJob.__table__.columns
        }

    now = datetime.now(UTC)
    created_at = now - timedelta(seconds=1)
    invalid_rows: list[tuple[object, dict[str, object], str]] = []

    queued_retry = _job(
        id=1,
        state="queued",
        attempt_count=1,
        created_at=created_at,
        updated_at=now,
        started_at=now,
    )
    bad_claim = _job(
        id=1,
        state="running",
        attempt_count=1,
        lease_owner="worker-1",
        lease_expires_at=now + timedelta(minutes=1),
        created_at=created_at,
        started_at=now,
        updated_at=now + timedelta(seconds=1),
    )
    invalid_rows.append((bad_claim, snapshot(queued_retry), "attempt"))

    heartbeat_old = _job(
        id=2,
        state="running",
        attempt_count=1,
        lease_owner="worker-1",
        lease_expires_at=now + timedelta(minutes=1),
        created_at=created_at,
        updated_at=now,
        started_at=now,
    )
    heartbeat = _job(
        id=2,
        state="running",
        attempt_count=1,
        lease_owner="worker-2",
        lease_expires_at=now + timedelta(minutes=2),
        created_at=created_at,
        started_at=now,
        updated_at=now + timedelta(seconds=1),
    )
    invalid_rows.append((heartbeat, snapshot(heartbeat_old), "heartbeat"))

    future_old = _job(
        id=3,
        state="running",
        attempt_count=1,
        lease_owner="worker-1",
        lease_expires_at=now + timedelta(minutes=1),
        created_at=created_at,
        updated_at=now,
        started_at=now,
    )
    reclaim = _job(
        id=3,
        state="queued",
        attempt_count=1,
        created_at=created_at,
        started_at=now,
        updated_at=now + timedelta(seconds=1),
    )
    invalid_rows.append((reclaim, snapshot(future_old), "lease has not expired"))

    terminal_old = _job(
        id=4,
        state="succeeded",
        attempt_count=1,
        created_at=created_at,
        started_at=now,
        completed_at=now + timedelta(seconds=1),
        updated_at=now + timedelta(seconds=1),
    )
    terminal = _job(
        id=4,
        state="queued",
        attempt_count=1,
        created_at=created_at,
        started_at=now,
        updated_at=now + timedelta(seconds=2),
    )
    invalid_rows.append((terminal, snapshot(terminal_old), "terminal"))

    failed_without_error = _job(
        id=5,
        state="failed",
        attempt_count=1,
        created_at=created_at,
        updated_at=now + timedelta(seconds=1),
        started_at=now,
        completed_at=now + timedelta(seconds=1),
    )
    invalid_rows.append(
        (
            failed_without_error,
            snapshot(
                _job(
                    id=5,
                    state="running",
                    attempt_count=1,
                    lease_owner="worker-1",
                    lease_expires_at=now + timedelta(minutes=1),
                    created_at=created_at,
                    updated_at=now,
                    started_at=now,
                )
            ),
            "typed error",
        )
    )

    for job, old, message in invalid_rows:
        with pytest.raises(JobWorkflowError, match=message):
            validate_background_job_update(None, _Connection(old), job)  # type: ignore[arg-type]


def test_job_lifecycle_rejects_incoherent_leases_attempts_and_errors() -> None:
    from tamforge_backend.notifications.models import JobWorkflowError, validate_background_job

    now = datetime.now(UTC)
    for job in (
        _job(
            state="running",
            attempt_count=0,
            lease_owner="worker-1",
            lease_expires_at=now + timedelta(minutes=1),
            started_at=now,
        ),
        _job(state="queued", lease_owner="worker-1", lease_expires_at=now + timedelta(minutes=1)),
        _job(state="failed", attempt_count=1, started_at=now, completed_at=None),
        _job(last_error_category="internal_error", last_error_details=None),
        _job(last_error_category=None, last_error_details={"schema_version": 1, "attempt": 1}),
    ):
        with pytest.raises(JobWorkflowError):
            validate_background_job(None, None, job)


def test_outbox_publication_and_cursor_are_monotonic_and_write_once() -> None:
    from tamforge_backend.notifications.models import (
        DeliveryCursorWorkflowError,
        NotificationDeliveryCursor,
        OutboxEvent,
        OutboxWorkflowError,
    )

    now = datetime.now(UTC)
    event = OutboxEvent(
        owner_id=1,
        aggregate_type="activity",
        aggregate_id=1,
        event_type="activity.feedback_ready",
        payload_schema_version=1,
        payload={"schema_version": 1, "subject_id": 1},
        occurred_at=now,
        published_at=None,
        attempts=0,
        idempotency_key="event-1",
    )
    _detach(event)
    with pytest.raises(OutboxWorkflowError, match="provenance"):
        event.aggregate_id = 2
    event.attempts = 1
    event.published_at = now + timedelta(seconds=1)
    with pytest.raises(OutboxWorkflowError, match="write-once"):
        event.published_at = now + timedelta(seconds=2)
    with pytest.raises(OutboxWorkflowError, match="cannot decrease"):
        event.attempts = 0

    cursor = NotificationDeliveryCursor(
        owner_id=1,
        stream_key="status",
        last_event_id=10,
        created_at=now,
        updated_at=now,
    )
    _detach(cursor)
    cursor.updated_at = now + timedelta(seconds=1)
    cursor.last_event_id = 11
    with pytest.raises(DeliveryCursorWorkflowError, match="cannot decrease"):
        cursor.last_event_id = 9


def test_workflow_timestamp_and_provenance_mutations_are_rejected_at_orm_boundary() -> None:
    from tamforge_backend.notifications.models import BackgroundJob, JobWorkflowError
    from tamforge_backend.today.models import (
        ActivityProcessingStatus,
        Correction,
        CorrectionWorkflowError,
        ProcessingWorkflowError,
    )

    now = datetime.now(UTC)
    correction = Correction(
        owner_id=1,
        source_activity_id=1,
        source_evidence_event_id=1,
        priority=1,
        status="pending",
        due_date=date.today(),
        instruction="Use a one-sentence conclusion first.",
        attempt_b_activity_id=None,
        created_at=now,
        updated_at=now,
        completed_at=None,
    )
    _detach(correction)
    with pytest.raises(CorrectionWorkflowError, match="provenance"):
        correction.source_activity_id = 2
    with pytest.raises(CorrectionWorkflowError, match="provenance"):
        correction.due_date = correction.due_date + timedelta(days=1)
    correction.attempt_b_activity_id = 2
    with pytest.raises(CorrectionWorkflowError, match="write-once"):
        correction.attempt_b_activity_id = 3
    with pytest.raises(CorrectionWorkflowError, match="monotonic"):
        correction.updated_at = now - timedelta(seconds=1)

    processing = ActivityProcessingStatus(
        owner_id=1,
        activity_instance_id=1,
        state="uploaded",
        progress_label="uploaded",
        last_error_category=None,
        last_error_details=None,
        created_at=now,
        updated_at=now,
    )
    _detach(processing)
    with pytest.raises(ProcessingWorkflowError, match="monotonic"):
        processing.updated_at = now - timedelta(seconds=1)

    attention = ActivityProcessingStatus(
        owner_id=1,
        activity_instance_id=2,
        state="needs_attention",
        progress_label="action_required",
        last_error_category="processing_failure",
        last_error_details={"schema_version": 1, "attempt": 1},
        created_at=now,
        updated_at=now,
    )
    _detach(attention)
    with pytest.raises(ProcessingWorkflowError, match="same-state"):
        attention.last_error_details = {"schema_version": 1, "attempt": 2}

    job = _job()
    assert isinstance(job, BackgroundJob)
    _detach(job)
    with pytest.raises(JobWorkflowError, match="provenance"):
        job.owner_id = 2
    with pytest.raises(JobWorkflowError, match="monotonic"):
        job.updated_at = now - timedelta(seconds=1)

def test_offline_sql_contains_guards_search_path_indexes_and_reversible_downgrade() -> None:
    upgrade_sql = _offline_sql("upgrade", "20260825_0005_today_read_models")
    downgrade_sql = _offline_sql(
        "downgrade",
        "20260825_0005_today_read_models:20260825_0004_evidence_scoring",
    )
    lower_upgrade = upgrade_sql.lower()
    lower_downgrade = downgrade_sql.lower()

    for table_name in EXPECTED_TABLES:
        assert f"create table {table_name}" in lower_upgrade
        assert f"drop table {table_name}" in lower_downgrade
    assert lower_upgrade.count("set search_path = pg_catalog") >= 6
    assert "tamforge_validate_reference_payload_v1" in lower_upgrade
    assert "tamforge_validate_error_details_v1" in lower_upgrade
    assert "tamforge_guard_background_job_mutation" in lower_upgrade
    assert "tamforge_guard_processing_status_mutation" in lower_upgrade
    assert "tamforge_guard_outbox_event_mutation" in lower_upgrade
    assert "tamforge_guard_notification_cursor_mutation" in lower_upgrade
    assert "9223372036854775807" in lower_upgrade
    assert "new.due_date is distinct from old.due_date" in lower_upgrade
    assert "parent_attempt_id = source_attempt_id" in lower_upgrade
    assert "on delete cascade" not in lower_upgrade
    assert "postgresql://" not in lower_upgrade
    assert "https://" not in lower_upgrade

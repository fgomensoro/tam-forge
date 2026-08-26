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
    from tamforge_backend.today.service import CorrectionSlotLimitError, ensure_slot_available

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

    ensure_slot_available([1], candidate_priority=2)
    with pytest.raises(CorrectionSlotLimitError, match="two active corrections"):
        ensure_slot_available([1, 2], candidate_priority=1)
    with pytest.raises(CorrectionSlotLimitError, match="priority slot"):
        ensure_slot_available([1], candidate_priority=1)


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


def test_correction_source_evidence_must_belong_to_source_activity() -> None:
    from tamforge_backend.today.models import (
        Correction,
        CorrectionWorkflowError,
        validate_correction,
    )

    class _Result:
        def scalar_one_or_none(self) -> int:
            return 2

    class _Connection:
        def execute(self, statement: object) -> _Result:
            del statement
            return _Result()

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
        validate_correction(None, _Connection(), correction)  # type: ignore[arg-type]


def test_job_claim_retry_reclaim_heartbeat_and_terminal_guards() -> None:
    from tamforge_backend.notifications.models import JobWorkflowError, validate_background_job

    now = datetime.now(UTC)
    job = _job()
    _detach(job)
    job.updated_at = now + timedelta(seconds=1)
    job.state = "running"
    job.attempt_count = 1
    job.lease_owner = "worker-1"
    job.lease_expires_at = now + timedelta(minutes=1)
    job.started_at = now + timedelta(seconds=1)
    validate_background_job(None, None, job)

    job.updated_at = now + timedelta(seconds=2)
    job.lease_expires_at = now + timedelta(minutes=2)
    validate_background_job(None, None, job)

    job.updated_at = now + timedelta(seconds=3)
    job.state = "queued"
    job.lease_owner = None
    job.lease_expires_at = None
    job.available_at = now + timedelta(seconds=20)
    validate_background_job(None, None, job)

    with pytest.raises(JobWorkflowError, match="attempt count"):
        job.attempt_count = 3

    terminal = _job(
        state="succeeded",
        attempt_count=1,
        started_at=now,
        completed_at=now + timedelta(seconds=1),
        updated_at=now + timedelta(seconds=1),
    )
    _detach(terminal)
    with pytest.raises(JobWorkflowError, match="terminal"):
        terminal.state = "queued"


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

    running = _job(
        state="running",
        attempt_count=1,
        lease_owner="worker-1",
        lease_expires_at=now + timedelta(minutes=1),
        started_at=now,
    )
    _detach(running)
    with pytest.raises(JobWorkflowError, match="heartbeat"):
        running.lease_owner = "worker-2"
    with pytest.raises(JobWorkflowError, match="lease expiry"):
        running.lease_expires_at = now + timedelta(seconds=30)


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
    assert "on delete cascade" not in lower_upgrade
    assert "postgresql://" not in lower_upgrade
    assert "https://" not in lower_upgrade

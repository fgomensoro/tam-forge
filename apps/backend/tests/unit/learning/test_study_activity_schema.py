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

MIGRATION_PATH = Path("apps/backend/alembic/versions/20260825_0003_study_activities.py")
EXPECTED_TABLES = {
    "learner_settings",
    "study_days",
    "activity_instances",
    "activity_timer_sessions",
    "attempts",
    "artifacts",
    "activity_artifact_links",
    "self_reviews",
    "adaptive_changes",
    "daily_closes",
}


def _load_migration() -> object:
    assert MIGRATION_PATH.exists(), "study activity migration must exist"
    spec = importlib.util.spec_from_file_location("study_activity_migration", MIGRATION_PATH)
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
        password="offline-study-contract-password",
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


def _indexed_prefixes(table: sa.Table) -> set[tuple[str, ...]]:
    result = {tuple(column.name for column in index.columns) for index in table.indexes}
    result.update(
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, (sa.PrimaryKeyConstraint, sa.UniqueConstraint))
    )
    return result


def test_revision_contract_is_exact_and_linear() -> None:
    migration = _load_migration()

    assert migration.revision == "20260825_0003_study_activities"
    assert migration.down_revision == "20260825_0002_curriculum"
    assert migration.branch_labels is None
    assert migration.depends_on is None


def test_learning_models_register_lazily_without_import_cycles() -> None:
    result = _run_fresh_python(
        "from tamforge_backend.models import Base, load_all_models; "
        "assert not Base.metadata.tables; "
        "load_all_models(); "
        f"assert {EXPECTED_TABLES!r} <= set(Base.metadata.tables)"
    )

    assert result.returncode == 0, result.stderr


def test_models_expose_required_tables_columns_and_postgres_types() -> None:
    from tamforge_backend.models import Base, load_all_models

    load_all_models()
    expected_columns = {
        "learner_settings": {
            "id",
            "owner_id",
            "timezone",
            "study_start_date",
            "active_roadmap_version_id",
            "created_at",
            "updated_at",
        },
        "study_days": {
            "id",
            "owner_id",
            "roadmap_version_id",
            "local_date",
            "planned_minutes",
            "focused_minutes",
            "day_type",
            "status",
            "created_at",
            "started_at",
            "closed_at",
        },
        "activity_instances": {
            "id",
            "owner_id",
            "study_day_id",
            "roadmap_version_id",
            "task_definition_id",
            "task_stable_id_snapshot",
            "task_mapping_version_snapshot",
            "task_objective_snapshot",
            "task_timebox_minutes_snapshot",
            "roadmap_version_key_snapshot",
            "state",
            "attempt_kind",
            "assistance_mode",
            "classification",
            "timebox_minutes",
            "source_hidden",
            "optimistic_version",
            "replacement_version",
            "replaces_activity_id",
            "created_at",
            "started_at",
            "output_committed_at",
            "completed_at",
        },
        "activity_timer_sessions": {
            "id",
            "owner_id",
            "activity_instance_id",
            "idempotency_key",
            "started_at",
            "last_heartbeat_at",
            "paused_at",
            "ended_at",
            "counted_seconds",
        },
        "attempts": {
            "id",
            "owner_id",
            "activity_instance_id",
            "attempt_kind",
            "parent_attempt_id",
            "original_text",
            "original_markdown",
            "original_sql",
            "audience",
            "prompt",
            "assistance_mode",
            "commitment_hash",
            "committed_at",
            "created_at",
        },
        "artifacts": {
            "id",
            "owner_id",
            "object_key",
            "content_hash",
            "content_type",
            "original_filename",
            "byte_size",
            "artifact_class",
            "encryption_metadata",
            "derived_from_artifact_id",
            "immutable_version",
            "created_at",
        },
        "activity_artifact_links": {
            "id",
            "owner_id",
            "activity_instance_id",
            "attempt_id",
            "artifact_id",
            "link_role",
            "created_at",
        },
        "self_reviews": {
            "id",
            "owner_id",
            "activity_instance_id",
            "attempt_id",
            "main_answer",
            "did_well",
            "structure_weakness",
            "vague_points",
            "hesitation_points",
            "change_next",
            "self_score",
            "submitted_at",
        },
        "adaptive_changes": {
            "id",
            "owner_id",
            "roadmap_version_id",
            "study_day_id",
            "activity_instance_id",
            "what_changed",
            "why_changed",
            "evidence_manifest",
            "roadmap_objective",
            "coverage_impact",
            "affects_required_coverage",
            "time_impact",
            "planned_time_delta_minutes",
            "created_at",
        },
        "daily_closes": {
            "id",
            "owner_id",
            "roadmap_version_id",
            "study_day_id",
            "evidence_confirmed",
            "evidence_manifest",
            "strongest_output",
            "repeated_mistake",
            "unfinished_classification",
            "unfinished_requirement",
            "correction_count",
            "closed_at",
        },
    }

    assert EXPECTED_TABLES <= set(Base.metadata.tables)
    for table_name, columns in expected_columns.items():
        table = Base.metadata.tables[table_name]
        assert set(table.c.keys()) == columns
        assert isinstance(table.c.id.type, sa.BigInteger)
        assert table.c.id.identity is not None and table.c.id.identity.always is True

    for table_name, column_name in {
        "attempts": "commitment_hash",
        "artifacts": "content_hash",
    }.items():
        column = Base.metadata.tables[table_name].c[column_name]
        assert isinstance(column.type, sa.LargeBinary)
        assert column.type.length == 32

    for table_name, column_name in {
        "artifacts": "encryption_metadata",
        "adaptive_changes": "evidence_manifest",
        "daily_closes": "evidence_manifest",
    }.items():
        assert isinstance(Base.metadata.tables[table_name].c[column_name].type, postgresql.JSONB)


def test_named_constraints_restrict_history_and_index_every_foreign_key() -> None:
    from tamforge_backend.models import Base, load_all_models

    load_all_models()
    required = {
        "learner_settings": {
            "uq_learner_settings_owner_id",
            "ck_learner_settings_timezone_iana_shape",
        },
        "study_days": {
            "uq_study_days_owner_local_date",
            "uq_study_days_owner_version_id_id",
            "ck_study_days_minutes_bounded",
            "ck_study_days_status_allowed",
        },
        "activity_instances": {
            "uq_activity_instances_owner_study_task_replacement",
            "uq_activity_instances_owner_study_task_id",
            "ck_activity_instances_attempt_kind_allowed",
            "ck_activity_instances_replacement_coherent",
            "ck_activity_instances_optimistic_version_positive",
        },
        "activity_timer_sessions": {
            "uq_activity_timer_sessions_owner_idempotency",
            "ck_activity_timer_sessions_timestamps_coherent",
        },
        "attempts": {
            "uq_attempts_owner_activity_kind",
            "uq_attempts_owner_activity_id_id",
            "ck_attempts_attempt_kind_allowed",
            "ck_attempts_ab_relation_coherent",
            "ck_attempts_original_payload_present",
            "ck_attempts_commitment_hash_length",
        },
        "artifacts": {
            "uq_artifacts_owner_content_hash",
            "uq_artifacts_owner_id_id",
            "ck_artifacts_artifact_class_allowed",
            "ck_artifacts_content_hash_length",
            "ck_artifacts_encryption_metadata_object",
        },
        "activity_artifact_links": {
            "uq_activity_artifact_links_binding",
            "ck_activity_artifact_links_role_allowed",
        },
        "self_reviews": {
            "uq_self_reviews_owner_activity_attempt",
            "ck_self_reviews_score_range",
        },
        "adaptive_changes": {
            "ck_adaptive_changes_coverage_impact_allowed",
            "ck_adaptive_changes_time_impact_coherent",
        },
        "daily_closes": {
            "uq_daily_closes_owner_study_day",
            "ck_daily_closes_correction_count_range",
            "ck_daily_closes_unfinished_classification_allowed",
        },
    }
    for table_name, names in required.items():
        assert names <= _constraint_names(Base.metadata.tables[table_name])

    for table_name in EXPECTED_TABLES:
        table = Base.metadata.tables[table_name]
        indexed = _indexed_prefixes(table)
        for foreign_key in table.foreign_key_constraints:
            assert foreign_key.ondelete == "RESTRICT"
            constrained = tuple(column.name for column in foreign_key.columns)
            assert any(prefix[: len(constrained)] == constrained for prefix in indexed), (
                table_name,
                constrained,
                indexed,
            )


def test_partial_unique_enforces_one_open_timer_without_owner_global_activity_lock() -> None:
    from tamforge_backend.models import Base, load_all_models

    load_all_models()
    activities = Base.metadata.tables["activity_instances"]
    timers = Base.metadata.tables["activity_timer_sessions"]
    open_timer = next(
        item
        for item in timers.indexes
        if item.name == "uq_activity_timer_sessions_one_open_per_activity"
    )
    assert "uq_activity_instances_one_open_per_owner" not in {
        item.name for item in activities.indexes
    }
    assert open_timer.unique is True
    assert [column.name for column in open_timer.columns] == ["activity_instance_id"]
    assert str(open_timer.dialect_options["postgresql"]["where"]) == "ended_at IS NULL"


def test_attempt_c_is_unrepresentable_and_attempt_b_requires_attempt_a() -> None:
    from tamforge_backend.learning.models import (
        Attempt,
        AttemptWorkflowError,
        validate_attempt_workflow,
    )

    now = datetime.now(UTC)
    with pytest.raises(AttemptWorkflowError, match="attempt kind"):
        Attempt(
            owner_id=1,
            activity_instance_id=1,
            attempt_kind="attempt_c",
            parent_attempt_id=1,
            original_text="answer",
            original_markdown=None,
            original_sql=None,
            audience="hiring_manager",
            prompt="Explain the incident.",
            assistance_mode="none",
            commitment_hash=b"a" * 32,
            committed_at=now,
            created_at=now,
        )

    invalid_b = Attempt(
        owner_id=1,
        activity_instance_id=1,
        attempt_kind="attempt_b",
        parent_attempt_id=None,
        original_text="answer",
        original_markdown=None,
        original_sql=None,
        audience="hiring_manager",
        prompt="Explain the incident.",
        assistance_mode="none",
        commitment_hash=b"a" * 32,
        committed_at=now,
        created_at=now,
    )
    with pytest.raises(AttemptWorkflowError, match="relation"):
        validate_attempt_workflow(None, None, invalid_b)


def test_attempt_shape_validation_is_independent_of_constructor_assignment_order() -> None:
    from tamforge_backend.learning.models import (
        Attempt,
        AttemptWorkflowError,
        validate_attempt_workflow,
    )

    now = datetime.now(UTC)
    common = {
        "owner_id": 1,
        "activity_instance_id": 1,
        "original_text": "answer",
        "original_markdown": None,
        "original_sql": None,
        "audience": "hiring_manager",
        "prompt": "Explain the incident.",
        "assistance_mode": "none",
        "commitment_hash": b"a" * 32,
        "committed_at": now,
        "created_at": now,
    }
    invalid_a_parent_first = Attempt(
        parent_attempt_id=7,
        attempt_kind="attempt_a",
        **common,
    )
    invalid_a_kind_first = Attempt(
        attempt_kind="attempt_a",
        parent_attempt_id=7,
        **common,
    )
    invalid_b_parent_first = Attempt(
        parent_attempt_id=None,
        attempt_kind="attempt_b",
        **common,
    )

    for attempt in (invalid_a_parent_first, invalid_a_kind_first, invalid_b_parent_first):
        with pytest.raises(AttemptWorkflowError, match="relation"):
            validate_attempt_workflow(None, None, attempt)

    valid_a = Attempt(attempt_kind="attempt_a", parent_attempt_id=None, **common)
    valid_b_parent_first = Attempt(
        parent_attempt_id=7,
        attempt_kind="attempt_b",
        **common,
    )
    valid_b_kind_first = Attempt(
        attempt_kind="attempt_b",
        parent_attempt_id=7,
        **common,
    )
    validate_attempt_workflow(None, None, valid_a)
    validate_attempt_workflow(None, None, valid_b_parent_first)
    validate_attempt_workflow(None, None, valid_b_kind_first)

    assert sa.event.contains(Attempt, "before_insert", validate_attempt_workflow)
    assert sa.event.contains(Attempt, "before_update", validate_attempt_workflow)


def test_committed_attempt_artifact_and_link_are_orm_append_only() -> None:
    from tamforge_backend.learning.models import (
        ActivityArtifactLink,
        AppendOnlyLearningEvidenceError,
        Artifact,
        Attempt,
        reject_learning_evidence_delete,
    )

    now = datetime.now(UTC)
    attempt = Attempt(
        id=1,
        owner_id=1,
        activity_instance_id=1,
        attempt_kind="attempt_a",
        parent_attempt_id=None,
        original_text="original",
        original_markdown=None,
        original_sql=None,
        audience="customer",
        prompt="prompt",
        assistance_mode="none",
        commitment_hash=b"a" * 32,
        committed_at=now,
        created_at=now,
    )
    artifact = Artifact(
        id=1,
        owner_id=1,
        object_key="owners/1/original/audio/hash.wav",
        content_hash=b"b" * 32,
        content_type="audio/wav",
        original_filename="answer.wav",
        byte_size=123,
        artifact_class="original_audio",
        encryption_metadata={
            "schema_version": 1,
            "encrypted": False,
            "algorithm": None,
            "key_reference": None,
        },
        derived_from_artifact_id=None,
        immutable_version=1,
        created_at=now,
    )
    link = ActivityArtifactLink(
        id=1,
        owner_id=1,
        activity_instance_id=1,
        attempt_id=1,
        artifact_id=1,
        link_role="presentation_audio",
        created_at=now,
    )
    for item in (attempt, artifact, link):
        make_transient_to_detached(item)
        with pytest.raises(AppendOnlyLearningEvidenceError, match="immutable"):
            reject_learning_evidence_delete(None, None, item)

    with pytest.raises(AppendOnlyLearningEvidenceError, match="immutable"):
        attempt.original_text = "rewritten"
    with pytest.raises(AppendOnlyLearningEvidenceError, match="immutable"):
        artifact.object_key = "owners/1/changed"
    with pytest.raises(AppendOnlyLearningEvidenceError, match="immutable"):
        link.link_role = "analysis"


def test_activity_orm_rejects_invalid_transition_and_provenance_mutation() -> None:
    from tamforge_backend.learning.models import ActivityInstance, ActivityWorkflowError

    now = datetime.now(UTC)
    activity = ActivityInstance(
        id=1,
        owner_id=1,
        study_day_id=1,
        roadmap_version_id=1,
        task_definition_id=1,
        task_stable_id_snapshot="week1.sql.1",
        task_mapping_version_snapshot="v1",
        task_objective_snapshot="Solve SQL.",
        task_timebox_minutes_snapshot=45,
        roadmap_version_key_snapshot="month-1-v1",
        state="ready",
        attempt_kind="attempt_a",
        assistance_mode="none",
        classification="required",
        timebox_minutes=45,
        source_hidden=False,
        optimistic_version=1,
        replacement_version=1,
        replaces_activity_id=None,
        created_at=now,
        started_at=None,
        output_committed_at=None,
        completed_at=None,
    )
    make_transient_to_detached(activity)

    with pytest.raises(ActivityWorkflowError, match="transition"):
        activity.state = "feedback_ready"
    with pytest.raises(ActivityWorkflowError, match="provenance"):
        activity.task_definition_id = 2

    activity.state = "active"
    activity.started_at = now
    activity.optimistic_version = 2
    with pytest.raises(ActivityWorkflowError, match="write-once"):
        activity.started_at = datetime.now(UTC)


def test_study_day_orm_rejects_state_jumps_and_historical_scope_changes() -> None:
    from tamforge_backend.learning.models import StudyDay, StudyDayWorkflowError

    now = datetime.now(UTC)
    day = StudyDay(
        id=1,
        owner_id=1,
        roadmap_version_id=1,
        local_date=date(2026, 8, 25),
        planned_minutes=240,
        focused_minutes=0,
        day_type="weekday",
        status="planned",
        created_at=now,
        started_at=None,
        closed_at=None,
    )
    make_transient_to_detached(day)

    with pytest.raises(StudyDayWorkflowError, match="transition"):
        day.status = "closed"
    with pytest.raises(StudyDayWorkflowError, match="provenance"):
        day.local_date = date(2026, 8, 26)


def test_timer_orm_flush_guard_matches_monotonic_database_contract() -> None:
    from tamforge_backend.learning.models import (
        ActivityTimerSession,
        TimerWorkflowError,
        validate_timer_workflow,
    )

    now = datetime.now(UTC)

    def timer(*, ended: bool = False, paused: bool = False) -> ActivityTimerSession:
        item = ActivityTimerSession(
            id=1,
            owner_id=1,
            activity_instance_id=1,
            idempotency_key="timer-1",
            started_at=now,
            last_heartbeat_at=now,
            paused_at=now if paused else None,
            ended_at=now if ended else None,
            counted_seconds=30,
        )
        make_transient_to_detached(item)
        return item

    heartbeat_backwards = timer()
    heartbeat_backwards.last_heartbeat_at = now - timedelta(seconds=1)
    with pytest.raises(TimerWorkflowError, match="heartbeat"):
        validate_timer_workflow(None, None, heartbeat_backwards)

    counted_backwards = timer()
    counted_backwards.counted_seconds = 29
    with pytest.raises(TimerWorkflowError, match="counted seconds"):
        validate_timer_workflow(None, None, counted_backwards)

    changed_pause = timer(paused=True)
    changed_pause.paused_at = now + timedelta(seconds=1)
    with pytest.raises(TimerWorkflowError, match="paused_at"):
        validate_timer_workflow(None, None, changed_pause)

    terminal = timer(ended=True)
    terminal.counted_seconds = 31
    with pytest.raises(TimerWorkflowError, match="ended timer"):
        validate_timer_workflow(None, None, terminal)

    assert sa.event.contains(ActivityTimerSession, "before_update", validate_timer_workflow)


def test_offline_sql_contains_hardened_reversible_guards() -> None:
    upgrade_sql = _offline_sql("upgrade", "20260825_0003_study_activities")
    downgrade_sql = _offline_sql(
        "downgrade",
        "20260825_0003_study_activities:20260825_0002_curriculum",
    )

    assert "SET search_path = pg_catalog" in upgrade_sql
    assert "tamforge_reject_learning_evidence_mutation" in upgrade_sql
    assert "tamforge_guard_attempt_insert" in upgrade_sql
    assert "tamforge_guard_activity_mutation" in upgrade_sql
    assert "FOR UPDATE" in upgrade_sql
    assert "DROP FUNCTION IF EXISTS public.tamforge_reject_learning_evidence_mutation()" in (
        downgrade_sql
    )
    for table_name in EXPECTED_TABLES:
        assert f"DROP TABLE {table_name}" in downgrade_sql


def test_settings_and_dates_use_native_types() -> None:
    from tamforge_backend.learning.models import LearnerSetting, StudyDay

    setting = LearnerSetting(
        owner_id=1,
        timezone="America/Los_Angeles",
        study_start_date=date(2026, 8, 25),
        active_roadmap_version_id=None,
    )
    day = StudyDay(
        owner_id=1,
        roadmap_version_id=1,
        local_date=date(2026, 8, 25),
        planned_minutes=240,
        focused_minutes=0,
        day_type="weekday",
        status="planned",
    )
    assert setting.study_start_date == date(2026, 8, 25)
    assert day.local_date == date(2026, 8, 25)

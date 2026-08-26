from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
from io import StringIO
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import URL
from sqlalchemy.orm import make_transient_to_detached

MIGRATION_PATH = Path("apps/backend/alembic/versions/20260825_0002_curriculum.py")
EXPECTED_TABLES = {
    "roadmap_sources",
    "roadmap_imports",
    "roadmap_versions",
    "curriculum_nodes",
    "task_definitions",
    "resources",
    "pass_criteria",
    "exit_criteria",
    "month_exit_reviews",
}


def _load_migration() -> object:
    assert MIGRATION_PATH.exists(), "curriculum migration must exist"
    spec = importlib.util.spec_from_file_location("curriculum_migration", MIGRATION_PATH)
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
        password="offline-curriculum-contract-password",
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
    return {constraint.name for constraint in table.constraints if constraint.name is not None}


def _index_leading_columns(table: sa.Table) -> set[tuple[str, ...]]:
    indexed = {tuple(column.name for column in index.columns) for index in table.indexes}
    indexed.update(
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, (sa.PrimaryKeyConstraint, sa.UniqueConstraint))
    )
    return indexed


def test_revision_contract_is_exact_and_linear() -> None:
    migration = _load_migration()

    assert migration.revision == "20260825_0002_curriculum"
    assert migration.down_revision == "20260825_0001_identity_sessions"
    assert migration.branch_labels is None
    assert migration.depends_on is None


def test_roadmap_models_register_lazily_without_import_cycles() -> None:
    result = _run_fresh_python(
        "from tamforge_backend.models import Base, load_all_models; "
        "assert not Base.metadata.tables; "
        "load_all_models(); "
        f"assert {EXPECTED_TABLES!r} <= set(Base.metadata.tables)"
    )

    assert result.returncode == 0, result.stderr


def test_roadmap_models_expose_exact_tables_types_and_required_columns() -> None:
    from tamforge_backend.models import Base, load_all_models

    load_all_models()
    assert EXPECTED_TABLES <= set(Base.metadata.tables)

    expected_columns = {
        "roadmap_sources": {
            "id",
            "owner_id",
            "source_key",
            "name",
            "source_kind",
            "canonical_path",
            "created_at",
        },
        "roadmap_imports": {
            "id",
            "owner_id",
            "source_id",
            "package_hash",
            "object_key",
            "status",
            "validation_report",
            "semantic_diff",
            "idempotency_key",
            "failure_code",
            "failure_message",
            "created_at",
            "started_at",
            "completed_at",
        },
        "roadmap_versions": {
            "id",
            "owner_id",
            "source_id",
            "version_key",
            "version_number",
            "month_number",
            "predecessor_id",
            "content_hash",
            "object_key",
            "manifest",
            "raw_payload",
            "normalized_payload",
            "created_at",
            "approved_at",
            "activated_at",
            "superseded_at",
            "mirror_status",
            "mirror_ref",
            "mirror_error",
            "state",
        },
        "curriculum_nodes": {
            "id",
            "owner_id",
            "roadmap_version_id",
            "stable_id",
            "parent_id",
            "ordinal",
            "kind",
            "title",
            "source_path",
            "source_anchor",
        },
        "task_definitions": {
            "id",
            "owner_id",
            "roadmap_version_id",
            "curriculum_node_id",
            "stable_id",
            "exercise_type",
            "mapping_version",
            "objective",
            "timebox_minutes",
            "block",
            "required",
            "output_contract",
            "pass_contract",
            "evidence_contract",
            "source_references",
            "allowed_ai_role",
            "source_path",
            "source_anchor",
        },
        "resources": {
            "id",
            "owner_id",
            "roadmap_version_id",
            "stable_id",
            "curriculum_node_id",
            "task_definition_id",
            "kind",
            "title",
            "locator",
            "required",
            "source_path",
            "source_anchor",
            "ordinal",
        },
        "pass_criteria": {
            "id",
            "owner_id",
            "roadmap_version_id",
            "stable_id",
            "curriculum_node_id",
            "task_definition_id",
            "description",
            "rubric",
            "evidence",
            "ordinal",
        },
        "exit_criteria": {
            "id",
            "owner_id",
            "roadmap_version_id",
            "stable_id",
            "month_number",
            "description",
            "rubric",
            "evidence",
            "ordinal",
        },
        "month_exit_reviews": {
            "id",
            "owner_id",
            "roadmap_version_id",
            "review_number",
            "state",
            "decision",
            "evidence",
            "activation_eligible",
            "eligibility_evidence",
            "started_at",
            "completed_at",
        },
    }

    for table_name, columns in expected_columns.items():
        table = Base.metadata.tables[table_name]
        assert set(table.c.keys()) == columns
        assert isinstance(table.c.id.type, sa.BigInteger)
        assert table.c.id.identity is not None
        assert table.c.id.identity.always is True

    for table_name in {"roadmap_imports", "roadmap_versions"}:
        table = Base.metadata.tables[table_name]
        hash_column = "package_hash" if table_name == "roadmap_imports" else "content_hash"
        assert isinstance(table.c[hash_column].type, sa.LargeBinary)
        assert table.c[hash_column].type.length == 32

    json_objects = {
        "roadmap_imports": {"validation_report", "semantic_diff"},
        "roadmap_versions": {"manifest", "raw_payload", "normalized_payload"},
        "task_definitions": {
            "output_contract",
            "pass_contract",
            "evidence_contract",
        },
        "pass_criteria": {"rubric", "evidence"},
        "exit_criteria": {"rubric", "evidence"},
        "month_exit_reviews": {"evidence", "eligibility_evidence"},
    }
    for table_name, column_names in json_objects.items():
        for column_name in column_names:
            assert isinstance(
                Base.metadata.tables[table_name].c[column_name].type,
                postgresql.JSONB,
            )
    assert isinstance(
        Base.metadata.tables["task_definitions"].c.source_references.type,
        postgresql.JSONB,
    )

    timestamptz = {
        "roadmap_sources": {"created_at"},
        "roadmap_imports": {"created_at", "started_at", "completed_at"},
        "roadmap_versions": {
            "created_at",
            "approved_at",
            "activated_at",
            "superseded_at",
        },
        "month_exit_reviews": {"started_at", "completed_at"},
    }
    for table_name, columns in timestamptz.items():
        for column_name in columns:
            assert Base.metadata.tables[table_name].c[column_name].type.timezone is True


def test_models_name_checks_uniques_and_index_every_foreign_key() -> None:
    from tamforge_backend.models import Base, load_all_models

    load_all_models()
    required_names = {
        "roadmap_sources": {
            "pk_roadmap_sources",
            "uq_roadmap_sources_owner_source_key",
            "uq_roadmap_sources_owner_id_id",
            "ck_roadmap_sources_source_key_nonblank",
            "ck_roadmap_sources_name_nonblank",
            "ck_roadmap_sources_source_kind_allowed",
        },
        "roadmap_imports": {
            "pk_roadmap_imports",
            "uq_roadmap_imports_owner_idempotency",
            "uq_roadmap_imports_source_package_hash",
            "ck_roadmap_imports_status_allowed",
            "ck_roadmap_imports_package_hash_length",
            "ck_roadmap_imports_validation_report_object",
            "ck_roadmap_imports_semantic_diff_object",
            "ck_roadmap_imports_failure_fields_coherent",
        },
        "roadmap_versions": {
            "pk_roadmap_versions",
            "uq_roadmap_versions_owner_id_id",
            "uq_roadmap_versions_owner_source_id_id",
            "uq_roadmap_versions_source_content_hash",
            "uq_roadmap_versions_source_version_key",
            "uq_roadmap_versions_source_version_number",
            "ck_roadmap_versions_state_allowed",
            "ck_roadmap_versions_mirror_status_allowed",
            "ck_roadmap_versions_lifecycle_coherent",
            "ck_roadmap_versions_predecessor_not_self",
        },
        "task_definitions": {
            "pk_task_definitions",
            "uq_task_definitions_owner_version_id_id",
            "uq_task_definitions_version_stable_id",
            "ck_task_definitions_block_allowed",
            "ck_task_definitions_allowed_ai_role_allowed",
            "ck_task_definitions_timebox_positive",
        },
        "month_exit_reviews": {
            "pk_month_exit_reviews",
            "uq_month_exit_reviews_version_review_number",
            "ck_month_exit_reviews_state_allowed",
            "ck_month_exit_reviews_decision_allowed",
            "ck_month_exit_reviews_lifecycle_coherent",
        },
    }
    for table_name, names in required_names.items():
        assert names <= _constraint_names(Base.metadata.tables[table_name])

    for table_name in EXPECTED_TABLES:
        table = Base.metadata.tables[table_name]
        indexed = _index_leading_columns(table)
        for foreign_key in table.foreign_key_constraints:
            assert foreign_key.ondelete == "RESTRICT"
            constrained = tuple(column.name for column in foreign_key.columns)
            assert any(columns[: len(constrained)] == constrained for columns in indexed), (
                table_name,
                constrained,
                indexed,
            )

    versions = Base.metadata.tables["roadmap_versions"]
    active_index = next(
        index
        for index in versions.indexes
        if index.name == "uq_roadmap_versions_one_active_per_owner"
    )
    assert active_index.unique is True
    assert str(active_index.dialect_options["postgresql"]["where"]) == "state = 'active'"
    assert [column.name for column in active_index.columns] == ["owner_id"]


def test_models_have_explicit_nullability_and_only_intended_server_defaults() -> None:
    from tamforge_backend.models import Base, load_all_models

    load_all_models()
    nullable_columns = {
        "roadmap_sources": {"canonical_path"},
        "roadmap_imports": {
            "failure_code",
            "failure_message",
            "started_at",
            "completed_at",
        },
        "roadmap_versions": {
            "predecessor_id",
            "approved_at",
            "activated_at",
            "superseded_at",
            "mirror_ref",
            "mirror_error",
        },
        "curriculum_nodes": {"parent_id", "source_path", "source_anchor"},
        "task_definitions": {"source_path", "source_anchor"},
        "resources": {
            "curriculum_node_id",
            "task_definition_id",
            "source_path",
            "source_anchor",
        },
        "pass_criteria": {"curriculum_node_id", "task_definition_id"},
        "exit_criteria": set(),
        "month_exit_reviews": {"activation_eligible", "completed_at"},
    }
    server_default_columns = {
        "roadmap_sources": {"id", "created_at"},
        "roadmap_imports": {"id", "validation_report", "semantic_diff", "created_at"},
        "roadmap_versions": {"id", "created_at"},
        "curriculum_nodes": {"id"},
        "task_definitions": {"id"},
        "resources": {"id"},
        "pass_criteria": {"id"},
        "exit_criteria": {"id"},
        "month_exit_reviews": {"id", "started_at"},
    }

    for table_name in EXPECTED_TABLES:
        table = Base.metadata.tables[table_name]
        assert {column.name for column in table.c if column.nullable} == nullable_columns[
            table_name
        ]
        assert {
            column.name for column in table.c if column.server_default is not None
        } == server_default_columns[table_name]


def test_stable_ids_are_scoped_to_roadmap_version() -> None:
    from tamforge_backend.models import Base, load_all_models

    load_all_models()
    for table_name in {
        "curriculum_nodes",
        "task_definitions",
        "resources",
        "pass_criteria",
        "exit_criteria",
    }:
        unique_columns = {
            tuple(column.name for column in constraint.columns)
            for constraint in Base.metadata.tables[table_name].constraints
            if isinstance(constraint, sa.UniqueConstraint)
        }
        assert ("roadmap_version_id", "stable_id") in unique_columns
        assert ("stable_id",) not in unique_columns


def test_mirror_workflow_does_not_keep_stale_refs_or_errors() -> None:
    from tamforge_backend.models import Base, load_all_models

    load_all_models()
    versions = Base.metadata.tables["roadmap_versions"]
    mirror_check = next(
        constraint
        for constraint in versions.constraints
        if constraint.name == "ck_roadmap_versions_mirror_fields_coherent"
    )
    expression = str(mirror_check.sqltext)
    assert "mirror_status = 'pending' AND mirror_ref IS NULL" in expression
    assert "mirror_status = 'not_required' AND mirror_ref IS NULL" in expression
    assert "mirror_error IS NULL" in expression

    migration_source = MIGRATION_PATH.read_text()
    assert "OLD.mirror_status = 'pending' AND NEW.mirror_status" in migration_source
    assert "OLD.mirror_status = 'syncing' AND NEW.mirror_status" in migration_source
    assert "OLD.mirror_status = 'failed' AND NEW.mirror_status = 'syncing'" in migration_source
    assert "invalid roadmap mirror transition" in migration_source


def test_persisted_error_text_has_bounded_redaction_checks() -> None:
    from tamforge_backend.models import Base, load_all_models

    load_all_models()
    error_checks = {
        "roadmap_imports": "ck_roadmap_imports_failure_message_redacted",
        "roadmap_versions": "ck_roadmap_versions_mirror_error_redacted",
    }
    for table_name, constraint_name in error_checks.items():
        constraint = next(
            item
            for item in Base.metadata.tables[table_name].constraints
            if item.name == constraint_name
        )
        expression = str(constraint.sqltext).lower()
        assert "bearer" in expression
        assert "github_pat_" in expression
        assert "session" in expression


def test_roadmap_version_and_curriculum_orm_guards_reject_mutation() -> None:
    from tamforge_backend.roadmaps.models import (
        CurriculumContentImmutableError,
        CurriculumNode,
        RoadmapVersion,
        RoadmapVersionImmutableError,
        reject_curriculum_content_delete,
        reject_curriculum_content_update,
    )

    version = RoadmapVersion(
        id=1,
        owner_id=1,
        source_id=1,
        version_key="month-1-v1",
        version_number=1,
        month_number=1,
        content_hash=b"v" * 32,
        object_key="owners/1/roadmaps/month-1-v1.json",
        manifest={},
        normalized_payload={},
        mirror_status="pending",
        state="draft",
    )
    make_transient_to_detached(version)
    with pytest.raises(RoadmapVersionImmutableError, match="immutable"):
        version.content_hash = b"x" * 32

    node = CurriculumNode(
        owner_id=1,
        roadmap_version_id=1,
        stable_id="week-1",
        ordinal=0,
        kind="week",
        title="Week 1",
    )
    with pytest.raises(CurriculumContentImmutableError, match="immutable"):
        reject_curriculum_content_update(None, None, node)
    with pytest.raises(CurriculumContentImmutableError, match="immutable"):
        reject_curriculum_content_delete(None, None, node)


def test_migration_compiles_upgrade_and_exact_downgrade_without_credentials() -> None:
    upgrade_sql = _offline_sql("upgrade", "20260825_0002_curriculum")
    downgrade_sql = _offline_sql(
        "downgrade",
        "20260825_0002_curriculum:20260825_0001_identity_sessions",
    )

    for table_name in EXPECTED_TABLES:
        assert f"CREATE TABLE {table_name}" in upgrade_sql
        assert f"DROP TABLE {table_name}" in downgrade_sql
    assert "WHERE state = 'active'" in upgrade_sql
    assert "tamforge_guard_roadmap_version_update" in upgrade_sql
    assert "tamforge_reject_curriculum_mutation" in upgrade_sql
    assert "DROP TABLE owners" not in downgrade_sql
    assert "offline-curriculum-contract-password" not in upgrade_sql
    assert "offline-curriculum-contract-password" not in downgrade_sql
    assert "%(" not in upgrade_sql
    assert ":schema" not in upgrade_sql
    assert "NULL}'" not in upgrade_sql
    assert re.search(r"ck_[a-z0-9_]+_ck_[a-z0-9_]+", upgrade_sql) is None

    from tamforge_backend.models import Base, load_all_models

    load_all_models()
    for table_name in EXPECTED_TABLES:
        table = Base.metadata.tables[table_name]
        for constraint_name in _constraint_names(table):
            assert f"CONSTRAINT {constraint_name}" in upgrade_sql
        for index in table.indexes:
            assert index.name is not None
            assert index.name in upgrade_sql


def test_canonical_path_is_provenance_only() -> None:
    runtime_files = [
        path
        for path in Path("apps/backend/src/tamforge_backend").rglob("*.py")
        if path != Path("apps/backend/src/tamforge_backend/roadmaps/models.py")
    ]
    assert all("canonical_path" not in path.read_text() for path in runtime_files)


def test_alembic_has_exactly_one_curriculum_head() -> None:
    environment = os.environ.copy()
    environment.pop("DATABASE_URL", None)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "apps/backend/alembic.ini", "heads"],
        cwd=Path.cwd(),
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "20260825_0002_curriculum (head)"

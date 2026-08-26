from __future__ import annotations

import importlib.util
import os
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

MIGRATION_PATH = Path(
    "apps/backend/alembic/versions/20260825_0001_identity_sessions.py"
)
EXPECTED_TABLES = {"owners", "auth_sessions", "command_receipts", "audit_events"}


def _load_migration() -> object:
    spec = importlib.util.spec_from_file_location("identity_sessions_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _constraint_names(table: sa.Table) -> set[str]:
    return {constraint.name for constraint in table.constraints if constraint.name is not None}


def _run_fresh_python(source: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", source],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize(
    "statement",
    [
        "from tamforge_backend.auth.models import Owner",
        "from tamforge_backend.auth import Owner",
    ],
)
def test_auth_owner_imports_in_a_fresh_process(statement: str) -> None:
    result = _run_fresh_python(f"{statement}; assert Owner.__tablename__ == 'owners'")

    assert result.returncode == 0, result.stderr


def test_model_registry_is_lazy_cycle_free_and_explicit_in_a_fresh_process() -> None:
    result = _run_fresh_python(
        "from tamforge_backend.models import Base, load_all_models; "
        "assert not Base.metadata.tables; "
        "load_all_models(); "
        f"assert {EXPECTED_TABLES!r} <= set(Base.metadata.tables)"
    )

    assert result.returncode == 0, result.stderr


def test_alembic_registers_models_in_a_fresh_process() -> None:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = URL.create(
        "postgresql+psycopg",
        username="tamforge",
        password="offline-registry-contract",
        host="127.0.0.1",
        port=54329,
        database="tamforge_test",
    ).render_as_string(hide_password=False)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            "apps/backend/alembic.ini",
            "upgrade",
            "head",
            "--sql",
        ],
        cwd=Path.cwd(),
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "CREATE TABLE owners" in result.stdout
    assert "offline-registry-contract" not in result.stdout


def test_identity_models_register_exact_tables_and_postgresql_types() -> None:
    from tamforge_backend.models import Base, load_all_models

    load_all_models()
    assert EXPECTED_TABLES <= set(Base.metadata.tables)

    owners = Base.metadata.tables["owners"]
    assert isinstance(owners.c.id.type, sa.BigInteger)
    assert owners.c.id.identity is not None
    assert owners.c.id.identity.always is True
    assert isinstance(owners.c.github_user_id.type, sa.BigInteger)
    assert isinstance(owners.c.github_login.type, sa.Text)
    assert owners.c.github_user_id.nullable is False
    assert owners.c.github_login.nullable is False
    assert owners.c.created_at.type.timezone is True
    assert owners.c.updated_at.type.timezone is True

    sessions = Base.metadata.tables["auth_sessions"]
    assert isinstance(sessions.c.token_hash.type, sa.LargeBinary)
    assert sessions.c.token_hash.type.length == 32
    assert isinstance(sessions.c.csrf_hash.type, sa.LargeBinary)
    assert sessions.c.csrf_hash.type.length == 32
    assert sessions.c.expires_at.type.timezone is True
    assert sessions.c.revoked_at.type.timezone is True
    assert sessions.c.last_seen_at.type.timezone is True

    receipts = Base.metadata.tables["command_receipts"]
    assert isinstance(receipts.c.request_hash.type, sa.LargeBinary)
    assert receipts.c.request_hash.type.length == 32
    assert isinstance(receipts.c.result_payload.type, postgresql.JSONB)
    assert receipts.c.created_at.type.timezone is True
    assert receipts.c.expires_at.type.timezone is True

    events = Base.metadata.tables["audit_events"]
    assert isinstance(events.c.actor_subject_hash.type, sa.LargeBinary)
    assert events.c.actor_subject_hash.type.length == 32
    assert isinstance(events.c.request_correlation_hash.type, sa.LargeBinary)
    assert events.c.request_correlation_hash.type.length == 32
    assert isinstance(events.c.idempotency_correlation_hash.type, sa.LargeBinary)
    assert events.c.idempotency_correlation_hash.type.length == 32
    assert isinstance(events.c.redacted_metadata.type, postgresql.JSONB)
    assert events.c.occurred_at.type.timezone is True
    assert events.c.owner_id.nullable is True


def test_identity_models_expose_named_constraints_and_fk_indexes() -> None:
    from tamforge_backend.models import Base, load_all_models

    load_all_models()
    expected_constraints = {
        "owners": {
            "pk_owners",
            "uq_owners_github_user_id",
            "ck_owners_github_user_id_positive",
            "ck_owners_github_login_nonblank",
        },
        "auth_sessions": {
            "pk_auth_sessions",
            "fk_auth_sessions_owner_id_owners",
            "uq_auth_sessions_token_hash",
            "ck_auth_sessions_token_hash_length",
            "ck_auth_sessions_csrf_hash_length",
            "ck_auth_sessions_expires_after_creation",
            "ck_auth_sessions_revoked_after_creation",
            "ck_auth_sessions_last_seen_window",
        },
        "command_receipts": {
            "pk_command_receipts",
            "fk_command_receipts_owner_id_owners",
            "uq_command_receipts_owner_scope_idempotency",
            "ck_command_receipts_command_scope_nonblank",
            "ck_command_receipts_idempotency_key_nonblank",
            "ck_command_receipts_request_hash_length",
            "ck_command_receipts_status_nonblank",
            "ck_command_receipts_result_payload_object",
            "ck_command_receipts_expires_after_creation",
        },
        "audit_events": {
            "pk_audit_events",
            "fk_audit_events_owner_id_owners",
            "ck_audit_events_actor_kind_nonblank",
            "ck_audit_events_actor_subject_hash_length",
            "ck_audit_events_action_nonblank",
            "ck_audit_events_aggregate_type_nonblank",
            "ck_audit_events_aggregate_id_nonblank",
            "ck_audit_events_request_correlation_hash_length",
            "ck_audit_events_idempotency_correlation_hash_length",
            "ck_audit_events_actor_kind_safe",
            "ck_audit_events_action_safe",
            "ck_audit_events_aggregate_type_safe",
            "ck_audit_events_aggregate_id_safe",
            "ck_audit_events_redacted_metadata_v1",
        },
    }
    expected_indexes = {
        "owners": {"ix_owners_github_login"},
        "auth_sessions": {
            "ix_auth_sessions_owner_id",
            "ix_auth_sessions_expires_at",
            "ix_auth_sessions_revoked_at",
        },
        "command_receipts": {"ix_command_receipts_owner_id_expires_at"},
        "audit_events": {
            "ix_audit_events_owner_id_occurred_at",
            "ix_audit_events_aggregate_occurred_at",
            "ix_audit_events_request_correlation_hash",
            "ix_audit_events_idempotency_correlation_hash",
        },
    }

    for table_name, names in expected_constraints.items():
        table = Base.metadata.tables[table_name]
        assert names <= _constraint_names(table)
        for foreign_key in table.foreign_key_constraints:
            assert foreign_key.ondelete == "RESTRICT"

    for table_name, names in expected_indexes.items():
        assert names == {index.name for index in Base.metadata.tables[table_name].indexes}


def test_persisted_owner_github_id_is_immutable_but_login_can_change() -> None:
    from tamforge_backend.auth.models import ImmutableOwnerIdentityError, Owner

    owner = Owner(id=1, github_user_id=102269369, github_login="fgomensoro")
    make_transient_to_detached(owner)

    with pytest.raises(ImmutableOwnerIdentityError, match="immutable"):
        owner.github_user_id = 999

    owner.github_login = "current-login"
    assert owner.github_login == "current-login"


def test_audit_events_reject_orm_update_and_delete() -> None:
    from tamforge_backend.auth.audit import default_audit_metadata
    from tamforge_backend.auth.models import (
        AppendOnlyAuditEventError,
        AuditEvent,
        reject_audit_event_delete,
        reject_audit_event_update,
    )

    event = AuditEvent(
        actor_kind="owner",
        actor_subject_hash=b"a" * 32,
        action="session.created",
        aggregate_type="auth_session",
        aggregate_id="1",
        redacted_metadata=default_audit_metadata(),
    )

    with pytest.raises(AppendOnlyAuditEventError, match="append-only"):
        reject_audit_event_update(None, None, event)
    with pytest.raises(AppendOnlyAuditEventError, match="append-only"):
        reject_audit_event_delete(None, None, event)


def test_revision_contract_and_cluster_safe_extension_downgrade() -> None:
    migration = _load_migration()

    assert migration.revision == "20260825_0001_identity_sessions"
    assert migration.down_revision is None
    source = MIGRATION_PATH.read_text()
    assert "CREATE EXTENSION IF NOT EXISTS pgcrypto" in source
    assert 'CREATE EXTENSION IF NOT EXISTS vector' in source
    assert "DROP EXTENSION" not in source.upper()
    assert "trg_owners_immutable_github_user_id" in source
    assert "trg_audit_events_append_only" in source
    assert "BEFORE TRUNCATE ON audit_events" in source
    assert "tamforge_validate_audit_metadata_v1" in source
    assert "tamforge_is_safe_audit_machine_value" in source
    assert "trg_audit_events_validate_insert" in source


def test_revision_renders_complete_offline_sql_without_url_leakage() -> None:
    output = StringIO()
    config = Config("apps/backend/alembic.ini", output_buffer=output)
    secret = "offline-contract-password"
    offline_url = URL.create(
        "postgresql+psycopg",
        username="tamforge",
        password=secret,
        host="127.0.0.1",
        port=54329,
        database="tamforge_test",
    ).render_as_string(hide_password=False)
    config.attributes["database_url"] = offline_url

    command.upgrade(config, "head", sql=True)

    sql = output.getvalue()
    assert secret not in sql
    assert 'CREATE TABLE owners' in sql
    assert 'CREATE TABLE auth_sessions' in sql
    assert 'CREATE TABLE command_receipts' in sql
    assert 'CREATE TABLE audit_events' in sql
    assert 'CREATE TRIGGER trg_owners_immutable_github_user_id' in sql
    assert 'CREATE TRIGGER trg_audit_events_append_only' in sql
    assert 'CREATE TRIGGER trg_audit_events_append_only_truncate' in sql
    assert 'CREATE TRIGGER trg_audit_events_validate_insert' in sql

    downgrade_output = StringIO()
    downgrade_config = Config("apps/backend/alembic.ini", output_buffer=downgrade_output)
    downgrade_config.attributes["database_url"] = offline_url
    command.downgrade(
        downgrade_config,
        "20260825_0001_identity_sessions:base",
        sql=True,
    )

    downgrade_sql = downgrade_output.getvalue()
    assert secret not in downgrade_sql
    audit_truncate_trigger = downgrade_sql.index(
        "DROP TRIGGER IF EXISTS trg_audit_events_append_only_truncate"
    )
    audit_row_trigger = downgrade_sql.index(
        "DROP TRIGGER IF EXISTS trg_audit_events_append_only ON"
    )
    audit_function = downgrade_sql.index(
        "DROP FUNCTION IF EXISTS public.tamforge_reject_audit_event_mutation"
    )
    audit_insert_trigger = downgrade_sql.index(
        "DROP TRIGGER IF EXISTS trg_audit_events_validate_insert"
    )
    audit_insert_function = downgrade_sql.index(
        "DROP FUNCTION IF EXISTS public.tamforge_validate_audit_event_insert"
    )
    audit_table = downgrade_sql.index("DROP TABLE audit_events")
    metadata_function = downgrade_sql.index(
        "DROP FUNCTION IF EXISTS public.tamforge_validate_audit_metadata_v1"
    )
    machine_function = downgrade_sql.index(
        "DROP FUNCTION IF EXISTS public.tamforge_is_safe_audit_machine_value"
    )
    owner_trigger = downgrade_sql.index(
        "DROP TRIGGER IF EXISTS trg_owners_immutable_github_user_id"
    )
    owner_function = downgrade_sql.index(
        "DROP FUNCTION IF EXISTS public.tamforge_reject_owner_github_id_change"
    )
    owner_table = downgrade_sql.index("DROP TABLE owners")
    assert audit_truncate_trigger < audit_function
    assert audit_row_trigger < audit_function < audit_table
    assert audit_insert_trigger < audit_insert_function < audit_table
    assert audit_table < metadata_function
    assert audit_table < machine_function
    assert owner_trigger < owner_function < owner_table

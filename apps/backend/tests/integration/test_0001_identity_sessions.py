from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

pytestmark = pytest.mark.integration


def test_identity_session_schema_contract_and_round_trip(test_database_url: str) -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect, text
    from sqlalchemy.dialects.postgresql import BYTEA, JSONB
    from sqlalchemy.exc import DBAPIError, IntegrityError
    from tamforge_backend.database import database_url_to_sync

    config = Config("apps/backend/alembic.ini")
    config.attributes["database_url"] = test_database_url
    engine = create_engine(database_url_to_sync(test_database_url))
    revision_tables = {"owners", "auth_sessions", "command_receipts", "audit_events"}
    valid_audit_metadata = (
        '{"schema_version":1,"outcome":"succeeded","reason_code":"none",'
        '"changed_fields":[],"counts":{},"flags":{}}'
    )

    def execute(statement: str, parameters: Mapping[str, Any] | None = None) -> Any:
        with engine.begin() as connection:
            return connection.execute(text(statement), parameters or {})

    def rejects_integrity(statement: str, parameters: Mapping[str, Any]) -> None:
        with pytest.raises(IntegrityError):
            execute(statement, parameters)

    try:
        command.downgrade(config, "base")
        command.upgrade(config, "20260825_0001_identity_sessions")
        inspector = inspect(engine)
        assert set(inspector.get_table_names()) == revision_tables | {"alembic_version"}

        expected_columns = {
            "owners": {
                "id",
                "github_user_id",
                "github_login",
                "created_at",
                "updated_at",
            },
            "auth_sessions": {
                "id",
                "owner_id",
                "token_hash",
                "csrf_hash",
                "expires_at",
                "revoked_at",
                "last_seen_at",
                "created_at",
            },
            "command_receipts": {
                "id",
                "owner_id",
                "command_scope",
                "idempotency_key",
                "request_hash",
                "status",
                "result_payload",
                "created_at",
                "expires_at",
            },
            "audit_events": {
                "id",
                "owner_id",
                "actor_kind",
                "actor_subject_hash",
                "action",
                "aggregate_type",
                "aggregate_id",
                "request_correlation_hash",
                "idempotency_correlation_hash",
                "redacted_metadata",
                "occurred_at",
            },
        }
        timestamptz_columns = {
            "owners": {"created_at", "updated_at"},
            "auth_sessions": {"expires_at", "revoked_at", "last_seen_at", "created_at"},
            "command_receipts": {"created_at", "expires_at"},
            "audit_events": {"occurred_at"},
        }
        for table_name, names in expected_columns.items():
            columns = {column["name"]: column for column in inspector.get_columns(table_name)}
            assert set(columns) == names
            assert columns["id"]["identity"]["always"] is True
            for column_name in timestamptz_columns[table_name]:
                assert columns[column_name]["type"].timezone is True
                if column_name in {"created_at", "updated_at", "occurred_at"}:
                    assert columns[column_name]["default"] is not None

        expected_nullable = {
            "owners": {"id": False, "github_user_id": False, "github_login": False},
            "auth_sessions": {
                "id": False,
                "owner_id": False,
                "token_hash": False,
                "csrf_hash": False,
                "expires_at": False,
                "revoked_at": True,
                "last_seen_at": True,
                "created_at": False,
            },
            "command_receipts": {
                "id": False,
                "owner_id": False,
                "command_scope": False,
                "idempotency_key": False,
                "request_hash": False,
                "status": False,
                "result_payload": False,
                "created_at": False,
                "expires_at": False,
            },
            "audit_events": {
                "id": False,
                "owner_id": True,
                "actor_kind": False,
                "actor_subject_hash": False,
                "action": False,
                "aggregate_type": False,
                "aggregate_id": False,
                "request_correlation_hash": True,
                "idempotency_correlation_hash": True,
                "redacted_metadata": False,
                "occurred_at": False,
            },
        }
        for table_name, expected in expected_nullable.items():
            actual = {
                column["name"]: column["nullable"]
                for column in inspector.get_columns(table_name)
            }
            assert actual == expected

        audit_columns = {
            column["name"]: column for column in inspector.get_columns("audit_events")
        }
        assert isinstance(audit_columns["actor_subject_hash"]["type"], BYTEA)
        assert isinstance(audit_columns["request_correlation_hash"]["type"], BYTEA)
        assert isinstance(
            audit_columns["idempotency_correlation_hash"]["type"],
            BYTEA,
        )
        assert isinstance(audit_columns["redacted_metadata"]["type"], JSONB)
        assert audit_columns["redacted_metadata"]["default"] is not None

        for table_name in revision_tables:
            primary_key = inspector.get_pk_constraint(table_name)
            assert primary_key["name"] == f"pk_{table_name}"
            assert primary_key["constrained_columns"] == ["id"]

        auth_column_names = set(expected_columns["auth_sessions"])
        assert "token" not in auth_column_names
        assert "csrf_token" not in auth_column_names
        assert all("raw" not in name for names in expected_columns.values() for name in names)
        audit_column_names = expected_columns["audit_events"]
        assert "request_id" not in audit_column_names
        assert "idempotency_key" not in audit_column_names
        assert all(
            not name.endswith("token") and not name.endswith("credential")
            for name in audit_column_names
        )

        expected_unique = {
            "owners": {"uq_owners_github_user_id"},
            "auth_sessions": {"uq_auth_sessions_token_hash"},
            "command_receipts": {"uq_command_receipts_owner_scope_idempotency"},
        }
        for table_name, names in expected_unique.items():
            assert names <= {
                constraint["name"] for constraint in inspector.get_unique_constraints(table_name)
            }

        expected_checks = {
            "owners": {
                "ck_owners_github_user_id_positive",
                "ck_owners_github_login_nonblank",
            },
            "auth_sessions": {
                "ck_auth_sessions_token_hash_length",
                "ck_auth_sessions_csrf_hash_length",
                "ck_auth_sessions_expires_after_creation",
                "ck_auth_sessions_revoked_after_creation",
                "ck_auth_sessions_last_seen_window",
            },
            "command_receipts": {
                "ck_command_receipts_command_scope_nonblank",
                "ck_command_receipts_idempotency_key_nonblank",
                "ck_command_receipts_request_hash_length",
                "ck_command_receipts_status_nonblank",
                "ck_command_receipts_result_payload_object",
                "ck_command_receipts_expires_after_creation",
            },
            "audit_events": {
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
        for table_name, names in expected_checks.items():
            actual_checks = {
                constraint["name"]
                for constraint in inspector.get_check_constraints(table_name)
            }
            assert names <= actual_checks

        expected_indexes = {
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
        for table_name, names in expected_indexes.items():
            assert names <= {index["name"] for index in inspector.get_indexes(table_name)}

        for table_name in {"auth_sessions", "command_receipts", "audit_events"}:
            owner_fk = next(
                foreign_key
                for foreign_key in inspector.get_foreign_keys(table_name)
                if foreign_key["constrained_columns"] == ["owner_id"]
            )
            assert owner_fk["referred_table"] == "owners"
            assert owner_fk["name"] == f"fk_{table_name}_owner_id_owners"
            assert owner_fk["options"].get("ondelete") == "RESTRICT"

        owner_id = execute(
            "INSERT INTO owners (github_user_id, github_login) "
            "VALUES (:github_user_id, :github_login) RETURNING id",
            {"github_user_id": 102269369, "github_login": "fgomensoro"},
        ).scalar_one()
        rejects_integrity(
            "INSERT INTO owners (github_user_id, github_login) VALUES (:id, :login)",
            {"id": 102269369, "login": "duplicate"},
        )
        rejects_integrity(
            "INSERT INTO owners (github_user_id, github_login) VALUES (:id, :login)",
            {"id": 0, "login": "invalid"},
        )
        rejects_integrity(
            "INSERT INTO auth_sessions "
            "(owner_id, token_hash, csrf_hash, expires_at) "
            "VALUES (:owner_id, :token_hash, :csrf_hash, now() + interval '1 hour')",
            {"owner_id": owner_id, "token_hash": b"short", "csrf_hash": b"c" * 32},
        )
        rejects_integrity(
            "INSERT INTO auth_sessions "
            "(owner_id, token_hash, csrf_hash, expires_at) "
            "VALUES (:owner_id, :token_hash, :csrf_hash, now() + interval '1 hour')",
            {"owner_id": owner_id, "token_hash": b"v" * 32, "csrf_hash": b"short"},
        )
        execute(
            "INSERT INTO auth_sessions "
            "(owner_id, token_hash, csrf_hash, expires_at) "
            "VALUES (:owner_id, :token_hash, :csrf_hash, now() + interval '1 hour')",
            {"owner_id": owner_id, "token_hash": b"t" * 32, "csrf_hash": b"c" * 32},
        )
        rejects_integrity(
            "INSERT INTO auth_sessions "
            "(owner_id, token_hash, csrf_hash, expires_at) "
            "VALUES (:owner_id, :token_hash, :csrf_hash, now() + interval '1 hour')",
            {"owner_id": owner_id, "token_hash": b"t" * 32, "csrf_hash": b"d" * 32},
        )
        rejects_integrity(
            "INSERT INTO auth_sessions "
            "(owner_id, token_hash, csrf_hash, expires_at) "
            "VALUES (:owner_id, :token_hash, :csrf_hash, now() - interval '1 hour')",
            {"owner_id": owner_id, "token_hash": b"u" * 32, "csrf_hash": b"e" * 32},
        )

        receipt_parameters = {
            "owner_id": owner_id,
            "scope": "activity.start",
            "key": "request-1",
            "request_hash": b"r" * 32,
        }
        execute(
            "INSERT INTO command_receipts "
            "(owner_id, command_scope, idempotency_key, request_hash, status, "
            "result_payload, expires_at) VALUES "
            "(:owner_id, :scope, :key, :request_hash, 'completed', '{}'::jsonb, "
            "now() + interval '1 day')",
            receipt_parameters,
        )
        rejects_integrity(
            "INSERT INTO command_receipts "
            "(owner_id, command_scope, idempotency_key, request_hash, status, "
            "result_payload, expires_at) VALUES "
            "(:owner_id, :scope, :key, :request_hash, 'completed', '{}'::jsonb, "
            "now() + interval '1 day')",
            {**receipt_parameters, "request_hash": b"x" * 32},
        )
        rejects_integrity(
            "INSERT INTO command_receipts "
            "(owner_id, command_scope, idempotency_key, request_hash, status, "
            "result_payload, expires_at) VALUES "
            "(:owner_id, 'other', 'short-hash', :request_hash, 'completed', "
            "'{}'::jsonb, now() + interval '1 day')",
            {"owner_id": owner_id, "request_hash": b"short"},
        )
        rejects_integrity(
            "INSERT INTO command_receipts "
            "(owner_id, command_scope, idempotency_key, request_hash, status, "
            "result_payload, expires_at) VALUES "
            "(:owner_id, 'other', 'expired', :request_hash, 'completed', "
            "'{}'::jsonb, now() - interval '1 day')",
            {"owner_id": owner_id, "request_hash": b"e" * 32},
        )
        rejects_integrity(
            "INSERT INTO command_receipts "
            "(owner_id, command_scope, idempotency_key, request_hash, status, "
            "result_payload, expires_at) VALUES "
            "(:owner_id, 'other', 'other', :request_hash, 'completed', '[]'::jsonb, "
            "now() + interval '1 day')",
            {"owner_id": owner_id, "request_hash": b"q" * 32},
        )

        audit_id = execute(
            "INSERT INTO audit_events "
            "(owner_id, actor_kind, actor_subject_hash, action, aggregate_type, "
            "aggregate_id, request_correlation_hash, idempotency_correlation_hash, "
            "redacted_metadata) VALUES "
            "(:owner_id, 'owner', :subject_hash, 'session.created', 'auth_session', "
            "'1', :request_hash, :idempotency_hash, CAST(:metadata AS jsonb)) RETURNING id",
            {
                "owner_id": owner_id,
                "subject_hash": b"a" * 32,
                "request_hash": b"r" * 32,
                "idempotency_hash": b"i" * 32,
                "metadata": valid_audit_metadata,
            },
        ).scalar_one()
        with pytest.raises(IntegrityError) as missing_metadata_error:
            execute(
                "INSERT INTO audit_events "
                "(owner_id, actor_kind, actor_subject_hash, action, aggregate_type, "
                "aggregate_id) VALUES "
                "(:owner_id, 'owner', :subject_hash, 'session.observed', "
                "'auth_session', '2')",
                {"owner_id": owner_id, "subject_hash": b"d" * 32},
            )
        assert missing_metadata_error.value.orig.sqlstate == "23502"
        secret_candidate = "raw-customer-secret-candidate"
        with pytest.raises(IntegrityError) as invalid_metadata_error:
            execute(
                "INSERT INTO audit_events "
                "(owner_id, actor_kind, actor_subject_hash, action, aggregate_type, "
                "aggregate_id, redacted_metadata) VALUES "
                "(:owner_id, 'owner', :subject_hash, 'invalid', 'owner', '1', "
                "CAST(:metadata AS jsonb))",
                {
                    "owner_id": owner_id,
                    "subject_hash": b"b" * 32,
                    "metadata": (
                        '{"schema_version":1,"notes":"'
                        f"{secret_candidate}"
                        '"}'
                    ),
                },
            )
        assert secret_candidate not in str(invalid_metadata_error.value.orig)
        rejects_integrity(
            "INSERT INTO audit_events "
            "(owner_id, actor_kind, actor_subject_hash, action, aggregate_type, "
            "aggregate_id, request_correlation_hash, redacted_metadata) VALUES "
            "(:owner_id, 'owner', :subject_hash, 'invalid', 'owner', '2', "
            ":request_hash, CAST(:metadata AS jsonb))",
            {
                "owner_id": owner_id,
                "subject_hash": b"b" * 32,
                "request_hash": b"short",
                "metadata": valid_audit_metadata,
            },
        )
        rejects_integrity(
            "INSERT INTO audit_events "
            "(owner_id, actor_kind, actor_subject_hash, action, aggregate_type, "
            "aggregate_id, redacted_metadata) VALUES "
            "(:owner_id, 'owner', :subject_hash, :action, 'owner', '3', "
            "CAST(:metadata AS jsonb))",
            {
                "owner_id": owner_id,
                "subject_hash": b"b" * 32,
                "action": "ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "metadata": valid_audit_metadata,
            },
        )
        with pytest.raises(DBAPIError):
            execute(
                "UPDATE owners SET github_user_id = :new_id WHERE id = :owner_id",
                {"new_id": 1, "owner_id": owner_id},
            )
        with pytest.raises(DBAPIError):
            execute(
                "UPDATE audit_events SET action = 'changed' WHERE id = :audit_id",
                {"audit_id": audit_id},
            )
        with pytest.raises(DBAPIError):
            execute("DELETE FROM audit_events WHERE id = :audit_id", {"audit_id": audit_id})
        with pytest.raises(DBAPIError):
            execute("TRUNCATE audit_events")
        assert execute("SELECT count(*) FROM audit_events").scalar_one() == 1
        with pytest.raises(IntegrityError):
            execute("DELETE FROM owners WHERE id = :owner_id", {"owner_id": owner_id})

        command.downgrade(config, "base")
        inspector = inspect(engine)
        assert revision_tables.isdisjoint(inspector.get_table_names())
        remaining_functions = execute(
            "SELECT proname FROM pg_proc WHERE proname IN "
            "('tamforge_reject_owner_github_id_change', "
            "'tamforge_reject_audit_event_mutation', "
            "'tamforge_validate_audit_event_insert', "
            "'tamforge_validate_audit_metadata_v1', "
            "'tamforge_is_safe_audit_machine_value')"
        ).scalars()
        assert list(remaining_functions) == []
        command.upgrade(config, "head")
        assert revision_tables <= set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

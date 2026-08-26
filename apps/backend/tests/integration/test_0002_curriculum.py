from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

pytestmark = pytest.mark.integration

REVISION_TABLES = {
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


def test_curriculum_schema_contract_invariants_and_round_trip(
    test_database_url: str,
) -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect, text
    from sqlalchemy.exc import DBAPIError, IntegrityError
    from tamforge_backend.database import database_url_to_sync

    config = Config("apps/backend/alembic.ini")
    config.attributes["database_url"] = test_database_url
    engine = create_engine(database_url_to_sync(test_database_url))

    def execute(statement: str, parameters: Mapping[str, Any] | None = None) -> Any:
        with engine.begin() as connection:
            return connection.execute(text(statement), parameters or {})

    def rejects_integrity(statement: str, parameters: Mapping[str, Any]) -> None:
        with pytest.raises((IntegrityError, DBAPIError)):
            execute(statement, parameters)

    try:
        command.downgrade(config, "base")
        command.upgrade(config, "20260825_0002_curriculum")
        inspector = inspect(engine)
        assert REVISION_TABLES <= set(inspector.get_table_names())

        owner_1 = execute(
            "INSERT INTO owners (github_user_id, github_login) "
            "VALUES (102269369, 'fgomensoro') RETURNING id"
        ).scalar_one()
        owner_2 = execute(
            "INSERT INTO owners (github_user_id, github_login) "
            "VALUES (102269370, 'restore-scope') RETURNING id"
        ).scalar_one()
        source_1 = execute(
            "INSERT INTO roadmap_sources "
            "(owner_id, source_key, name, source_kind, canonical_path) "
            "VALUES (:owner, 'obsidian-main', 'TAM Roadmap', 'obsidian', "
            "'/historical/provenance/only') RETURNING id",
            {"owner": owner_1},
        ).scalar_one()
        source_2 = execute(
            "INSERT INTO roadmap_sources "
            "(owner_id, source_key, name, source_kind) "
            "VALUES (:owner, 'restore', 'Restore Roadmap', 'package') RETURNING id",
            {"owner": owner_2},
        ).scalar_one()
        rejects_integrity(
            "INSERT INTO roadmap_sources "
            "(owner_id, source_key, name, source_kind) "
            "VALUES (:owner, 'obsidian-main', 'Duplicate', 'obsidian')",
            {"owner": owner_1},
        )

        import_values = {
            "owner": owner_1,
            "source": source_1,
            "hash": b"p" * 32,
            "key": "import-1",
        }
        import_id = execute(
            "INSERT INTO roadmap_imports "
            "(owner_id, source_id, package_hash, object_key, status, "
            "validation_report, semantic_diff, idempotency_key) VALUES "
            "(:owner, :source, :hash, 'private/roadmaps/package-1.tar', 'staged', "
            "'{}'::jsonb, '{}'::jsonb, :key) RETURNING id",
            import_values,
        ).scalar_one()
        rejects_integrity(
            "UPDATE roadmap_imports SET package_hash = :hash WHERE id = :import_id",
            {"hash": b"u" * 32, "import_id": import_id},
        )
        rejects_integrity(
            "INSERT INTO roadmap_imports "
            "(owner_id, source_id, package_hash, object_key, status, "
            "validation_report, semantic_diff, idempotency_key) VALUES "
            "(:owner, :source, :hash, 'private/roadmaps/duplicate.tar', 'staged', "
            "'{}'::jsonb, '{}'::jsonb, 'other-key')",
            import_values,
        )
        rejects_integrity(
            "INSERT INTO roadmap_imports "
            "(owner_id, source_id, package_hash, object_key, status, "
            "validation_report, semantic_diff, idempotency_key) VALUES "
            "(:owner, :source, :hash, 'private/roadmaps/other.tar', 'staged', "
            "'{}'::jsonb, '{}'::jsonb, :key)",
            {**import_values, "hash": b"q" * 32},
        )
        rejects_integrity(
            "INSERT INTO roadmap_imports "
            "(owner_id, source_id, package_hash, object_key, status, "
            "validation_report, semantic_diff, idempotency_key) VALUES "
            "(:owner, :source, :hash, 'private/roadmaps/cross-owner.tar', 'staged', "
            "'{}'::jsonb, '{}'::jsonb, 'cross-owner')",
            {"owner": owner_1, "source": source_2, "hash": b"x" * 32},
        )
        rejects_integrity(
            "INSERT INTO roadmap_imports "
            "(owner_id, source_id, package_hash, object_key, status, "
            "validation_report, semantic_diff, idempotency_key, failure_code, "
            "failure_message, completed_at) VALUES "
            "(:owner, :source, :hash, 'private/roadmaps/failed.tar', 'failed', "
            "'{}'::jsonb, '{}'::jsonb, 'failed-secret', 'validation_failed', "
            "'Bearer secret-value', now())",
            {"owner": owner_1, "source": source_1, "hash": b"f" * 32},
        )

        version_1 = execute(
            "INSERT INTO roadmap_versions "
            "(owner_id, source_id, version_key, version_number, month_number, "
            "content_hash, object_key, manifest, raw_payload, normalized_payload, "
            "mirror_status, state) "
            "VALUES (:owner, :source, 'month-1-v1', 1, 1, :hash, "
            "'private/roadmaps/month-1-v1.json', '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, "
            "'pending', 'draft') RETURNING id",
            {"owner": owner_1, "source": source_1, "hash": b"a" * 32},
        ).scalar_one()
        rejects_integrity(
            "INSERT INTO roadmap_versions "
            "(owner_id, source_id, version_key, version_number, month_number, "
            "content_hash, object_key, manifest, raw_payload, normalized_payload, "
            "mirror_status, state) "
            "VALUES (:owner, :source, 'duplicate-hash', 2, 1, :hash, "
            "'private/roadmaps/duplicate.json', '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, "
            "'pending', 'draft')",
            {"owner": owner_1, "source": source_1, "hash": b"a" * 32},
        )
        version_2 = execute(
            "INSERT INTO roadmap_versions "
            "(owner_id, source_id, version_key, version_number, month_number, "
            "predecessor_id, content_hash, object_key, manifest, raw_payload, "
            "normalized_payload, "
            "mirror_status, state) VALUES "
            "(:owner, :source, 'month-2-v1', 2, 2, :predecessor, :hash, "
            "'private/roadmaps/month-2-v1.json', '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, "
            "'pending', 'draft') RETURNING id",
            {
                "owner": owner_1,
                "source": source_1,
                "predecessor": version_1,
                "hash": b"b" * 32,
            },
        ).scalar_one()
        rejects_integrity(
            "UPDATE roadmap_versions SET mirror_status = 'failed', "
            "mirror_error = 'Bearer secret-value' WHERE id = :version",
            {"version": version_2},
        )
        execute(
            "UPDATE roadmap_versions SET mirror_status = 'failed', "
            "mirror_error = 'mirror_unavailable' WHERE id = :version",
            {"version": version_2},
        )
        rejects_integrity(
            "UPDATE roadmap_versions SET mirror_status = 'synced', "
            "mirror_ref = 'commit-1', mirror_error = NULL WHERE id = :version",
            {"version": version_2},
        )
        execute(
            "UPDATE roadmap_versions SET mirror_status = 'syncing', mirror_error = NULL "
            "WHERE id = :version",
            {"version": version_2},
        )
        execute(
            "UPDATE roadmap_versions SET mirror_status = 'synced', mirror_ref = 'commit-1' "
            "WHERE id = :version",
            {"version": version_2},
        )
        rejects_integrity(
            "UPDATE roadmap_versions SET predecessor_id = id WHERE id = :version",
            {"version": version_2},
        )
        other_version = execute(
            "INSERT INTO roadmap_versions "
            "(owner_id, source_id, version_key, version_number, month_number, "
            "content_hash, object_key, manifest, raw_payload, normalized_payload, "
            "mirror_status, state) "
            "VALUES (:owner, :source, 'restore-v1', 1, 1, :hash, "
            "'private/roadmaps/restore-v1.json', '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, "
            "'pending', 'draft') RETURNING id",
            {"owner": owner_2, "source": source_2, "hash": b"c" * 32},
        ).scalar_one()
        execute(
            "UPDATE roadmap_versions SET state = 'approved', approved_at = now() "
            "WHERE id = :version",
            {"version": other_version},
        )
        execute(
            "UPDATE roadmap_versions SET state = 'active', activated_at = now() "
            "WHERE id = :version",
            {"version": other_version},
        )
        rejects_integrity(
            "INSERT INTO roadmap_versions "
            "(owner_id, source_id, version_key, version_number, month_number, "
            "predecessor_id, content_hash, object_key, manifest, raw_payload, "
            "normalized_payload, "
            "mirror_status, state) VALUES "
            "(:owner, :source, 'bad-predecessor', 3, 3, :predecessor, :hash, "
            "'private/roadmaps/bad.json', '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, "
            "'pending', 'draft')",
            {
                "owner": owner_1,
                "source": source_1,
                "predecessor": other_version,
                "hash": b"d" * 32,
            },
        )

        execute(
            "UPDATE roadmap_versions SET state = 'approved', approved_at = now() "
            "WHERE id = :version",
            {"version": version_1},
        )
        execute(
            "UPDATE roadmap_versions SET state = 'active', activated_at = now() "
            "WHERE id = :version",
            {"version": version_1},
        )
        execute(
            "UPDATE roadmap_versions SET state = 'approved', approved_at = now() "
            "WHERE id = :version",
            {"version": version_2},
        )
        rejects_integrity(
            "UPDATE roadmap_versions SET state = 'active', activated_at = now() "
            "WHERE id = :version",
            {"version": version_2},
        )
        rejects_integrity(
            "UPDATE roadmap_versions SET content_hash = :hash WHERE id = :version",
            {"hash": b"z" * 32, "version": version_1},
        )
        rejects_integrity(
            "UPDATE roadmap_versions SET raw_payload = '{\"changed\":true}'::jsonb "
            "WHERE id = :version",
            {"version": version_1},
        )
        rejects_integrity(
            "UPDATE roadmap_versions SET normalized_payload = '{\"changed\":true}'::jsonb "
            "WHERE id = :version",
            {"version": version_1},
        )
        rejects_integrity(
            "UPDATE roadmap_versions SET approved_at = approved_at + interval '1 second' "
            "WHERE id = :version",
            {"version": version_1},
        )

        node_1 = execute(
            "INSERT INTO curriculum_nodes "
            "(owner_id, roadmap_version_id, stable_id, ordinal, kind, title) "
            "VALUES (:owner, :version, 'week-1', 0, 'week', 'Week 1') RETURNING id",
            {"owner": owner_1, "version": version_1},
        ).scalar_one()
        node_2 = execute(
            "INSERT INTO curriculum_nodes "
            "(owner_id, roadmap_version_id, stable_id, ordinal, kind, title) "
            "VALUES (:owner, :version, 'week-1', 0, 'week', "
            "'Week 1 repeated') RETURNING id",
            {"owner": owner_1, "version": version_2},
        ).scalar_one()
        rejects_integrity(
            "INSERT INTO curriculum_nodes "
            "(owner_id, roadmap_version_id, stable_id, ordinal, kind, title) "
            "VALUES (:owner, :version, 'week-1', 1, 'week', 'Duplicate')",
            {"owner": owner_1, "version": version_1},
        )
        rejects_integrity(
            "INSERT INTO curriculum_nodes "
            "(owner_id, roadmap_version_id, stable_id, parent_id, ordinal, kind, title) "
            "VALUES (:owner, :version, 'cross-version-child', :parent, 0, 'day', 'Bad')",
            {"owner": owner_1, "version": version_2, "parent": node_1},
        )

        task_1 = execute(
            "INSERT INTO task_definitions "
            "(owner_id, roadmap_version_id, curriculum_node_id, stable_id, exercise_type, "
            "mapping_version, objective, timebox_minutes, block, required, output_contract, "
            "pass_contract, evidence_contract, source_references, allowed_ai_role) VALUES "
            "(:owner, :version, :node, 'sql-1', 'sql', 'v1', 'Solve independently', "
            "45, 'sql', true, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, '[]'::jsonb, "
            "'reviewer') RETURNING id",
            {"owner": owner_1, "version": version_1, "node": node_1},
        ).scalar_one()
        task_2 = execute(
            "INSERT INTO task_definitions "
            "(owner_id, roadmap_version_id, curriculum_node_id, stable_id, exercise_type, "
            "mapping_version, objective, timebox_minutes, block, required, output_contract, "
            "pass_contract, evidence_contract, source_references, allowed_ai_role) VALUES "
            "(:owner, :version, :node, 'sql-1', 'sql', 'v1', 'Repeated in v2', "
            "45, 'sql', true, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, '[]'::jsonb, "
            "'reviewer') RETURNING id",
            {"owner": owner_1, "version": version_2, "node": node_2},
        ).scalar_one()
        rejects_integrity(
            "INSERT INTO task_definitions "
            "(owner_id, roadmap_version_id, curriculum_node_id, stable_id, exercise_type, "
            "mapping_version, objective, timebox_minutes, block, required, output_contract, "
            "pass_contract, evidence_contract, source_references, allowed_ai_role) VALUES "
            "(:owner, :version, :node, 'sql-1', 'sql', 'v1', 'Duplicate', 45, 'sql', "
            "true, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, '[]'::jsonb, 'reviewer')",
            {"owner": owner_1, "version": version_1, "node": node_1},
        )
        rejects_integrity(
            "INSERT INTO task_definitions "
            "(owner_id, roadmap_version_id, curriculum_node_id, stable_id, exercise_type, "
            "mapping_version, objective, timebox_minutes, block, required, output_contract, "
            "pass_contract, evidence_contract, source_references, allowed_ai_role) VALUES "
            "(:owner, :version, :node, 'bad-role', 'sql', 'v1', 'Bad', 45, 'sql', true, "
            "'{}'::jsonb, '{}'::jsonb, '{}'::jsonb, '[]'::jsonb, 'answer_writer')",
            {"owner": owner_1, "version": version_1, "node": node_1},
        )

        execute(
            "INSERT INTO resources "
            "(owner_id, roadmap_version_id, stable_id, curriculum_node_id, "
            "task_definition_id, kind, title, locator, required, ordinal) VALUES "
            "(:owner, :version, 'resource-1', :node, :task, 'documentation', "
            "'Assigned docs', 'roadmap://docs/http', true, 0)",
            {"owner": owner_1, "version": version_1, "node": node_1, "task": task_1},
        )
        execute(
            "INSERT INTO resources "
            "(owner_id, roadmap_version_id, stable_id, curriculum_node_id, "
            "task_definition_id, kind, title, locator, required, ordinal) VALUES "
            "(:owner, :version, 'resource-1', :node, :task, 'documentation', "
            "'Assigned docs v2', 'roadmap://docs/http-v2', true, 0)",
            {"owner": owner_1, "version": version_2, "node": node_2, "task": task_2},
        )
        rejects_integrity(
            "INSERT INTO resources "
            "(owner_id, roadmap_version_id, stable_id, kind, title, locator, required, "
            "ordinal) VALUES (:owner, :version, 'resource-1', 'documentation', "
            "'Duplicate', 'roadmap://duplicate', true, 1)",
            {"owner": owner_1, "version": version_1},
        )
        rejects_integrity(
            "INSERT INTO resources "
            "(owner_id, roadmap_version_id, stable_id, curriculum_node_id, "
            "task_definition_id, kind, title, locator, required, ordinal) VALUES "
            "(:owner, :version, 'bad-resource', :node, :task, 'documentation', "
            "'Bad', 'roadmap://bad', true, 0)",
            {"owner": owner_1, "version": version_2, "node": node_1, "task": task_1},
        )
        execute(
            "INSERT INTO pass_criteria "
            "(owner_id, roadmap_version_id, stable_id, task_definition_id, description, "
            "rubric, evidence, ordinal) VALUES "
            "(:owner, :version, 'pass-sql-1', :task, 'Independent result', "
            "'{}'::jsonb, '{}'::jsonb, 0)",
            {"owner": owner_1, "version": version_1, "task": task_1},
        )
        execute(
            "INSERT INTO pass_criteria "
            "(owner_id, roadmap_version_id, stable_id, task_definition_id, description, "
            "rubric, evidence, ordinal) VALUES "
            "(:owner, :version, 'pass-sql-1', :task, 'Independent result v2', "
            "'{}'::jsonb, '{}'::jsonb, 0)",
            {"owner": owner_1, "version": version_2, "task": task_2},
        )
        rejects_integrity(
            "INSERT INTO pass_criteria "
            "(owner_id, roadmap_version_id, stable_id, task_definition_id, description, "
            "rubric, evidence, ordinal) VALUES "
            "(:owner, :version, 'pass-sql-1', :task, 'Duplicate', "
            "'{}'::jsonb, '{}'::jsonb, 1)",
            {"owner": owner_1, "version": version_1, "task": task_1},
        )
        rejects_integrity(
            "INSERT INTO pass_criteria "
            "(owner_id, roadmap_version_id, stable_id, task_definition_id, description, "
            "rubric, evidence, ordinal) VALUES "
            "(:owner, :version, 'bad-pass', :task, 'Bad', '{}'::jsonb, '{}'::jsonb, 0)",
            {"owner": owner_1, "version": version_2, "task": task_1},
        )
        execute(
            "INSERT INTO exit_criteria "
            "(owner_id, roadmap_version_id, stable_id, month_number, description, "
            "rubric, evidence, ordinal) VALUES "
            "(:owner, :version, 'month-1-exit', 1, 'Pass Month 1', "
            "'{}'::jsonb, '{}'::jsonb, 0)",
            {"owner": owner_1, "version": version_1},
        )
        execute(
            "INSERT INTO exit_criteria "
            "(owner_id, roadmap_version_id, stable_id, month_number, description, "
            "rubric, evidence, ordinal) VALUES "
            "(:owner, :version, 'month-1-exit', 2, 'Pass Month 2', "
            "'{}'::jsonb, '{}'::jsonb, 0)",
            {"owner": owner_1, "version": version_2},
        )
        rejects_integrity(
            "INSERT INTO exit_criteria "
            "(owner_id, roadmap_version_id, stable_id, month_number, description, "
            "rubric, evidence, ordinal) VALUES "
            "(:owner, :version, 'month-1-exit', 1, 'Duplicate', "
            "'{}'::jsonb, '{}'::jsonb, 1)",
            {"owner": owner_1, "version": version_1},
        )

        review_id = execute(
            "INSERT INTO month_exit_reviews "
            "(owner_id, roadmap_version_id, review_number, state, decision, evidence, "
            "activation_eligible, eligibility_evidence, completed_at) VALUES "
            "(:owner, :version, 1, 'completed', 'advance', '{}'::jsonb, true, "
            "'{}'::jsonb, now()) RETURNING id",
            {"owner": owner_1, "version": version_1},
        ).scalar_one()
        rejects_integrity(
            "INSERT INTO month_exit_reviews "
            "(owner_id, roadmap_version_id, review_number, state, decision, evidence, "
            "activation_eligible, eligibility_evidence, completed_at) VALUES "
            "(:owner, :version, 1, 'completed', 'advance', '{}'::jsonb, true, "
            "'{}'::jsonb, now())",
            {"owner": owner_1, "version": version_1},
        )
        rejects_integrity(
            "INSERT INTO month_exit_reviews "
            "(owner_id, roadmap_version_id, review_number, state, decision, evidence, "
            "eligibility_evidence, completed_at) VALUES "
            "(:owner, :version, 2, 'completed', 'advance', '{}'::jsonb, "
            "'{}'::jsonb, now())",
            {"owner": owner_1, "version": version_1},
        )
        rejects_integrity(
            "DELETE FROM month_exit_reviews WHERE id = :review",
            {"review": review_id},
        )
        rejects_integrity(
            "DELETE FROM roadmap_versions WHERE id = :version",
            {"version": version_1},
        )
        rejects_integrity("DELETE FROM roadmap_sources WHERE id = :source", {"source": source_1})
        rejects_integrity("DELETE FROM owners WHERE id = :owner", {"owner": owner_1})

        command.downgrade(config, "20260825_0001_identity_sessions")
        assert REVISION_TABLES.isdisjoint(inspect(engine).get_table_names())
        assert {"owners", "auth_sessions", "command_receipts", "audit_events"} <= set(
            inspect(engine).get_table_names()
        )
        command.upgrade(config, "head")
        assert REVISION_TABLES <= set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

pytestmark = pytest.mark.integration


def test_task_definition_exercise_mapping_shape_is_enforced(
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

    def insert_task(
        connection: Any,
        *,
        stable_id: str,
        block: str,
        exercise_type: str | None,
        mapping_version: str | None,
    ) -> None:
        connection.execute(
            text(
                "INSERT INTO task_definitions "
                "(owner_id, roadmap_version_id, curriculum_node_id, stable_id, exercise_type, "
                "mapping_version, objective, timebox_minutes, block, required, output_contract, "
                "pass_contract, evidence_contract, source_references, allowed_ai_role) VALUES "
                "(:owner, :version, :node, :stable_id, :exercise_type, :mapping_version, "
                "'Task', 10, :block, false, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, "
                "'[]'::jsonb, 'none')"
            ),
            {
                "owner": owner_id,
                "version": version_id,
                "node": node_id,
                "stable_id": stable_id,
                "exercise_type": exercise_type,
                "mapping_version": mapping_version,
                "block": block,
            },
        )

    try:
        command.downgrade(config, "base")
        command.upgrade(config, "head")
        columns = {
            column["name"]: column for column in inspect(engine).get_columns("task_definitions")
        }
        assert columns["exercise_type"]["nullable"] is True
        assert columns["mapping_version"]["nullable"] is True
        assert "ck_task_definitions_exercise_mapping_coherent" in {
            item["name"] for item in inspect(engine).get_check_constraints("task_definitions")
        }

        owner_id = execute(
            "INSERT INTO owners (github_user_id, github_login) "
            "VALUES (102269369, 'fgomensoro') RETURNING id"
        ).scalar_one()
        source_id = execute(
            "INSERT INTO roadmap_sources "
            "(owner_id, source_key, name, source_kind) "
            "VALUES (:owner, 'obsidian-main', 'TAM Roadmap', 'obsidian') RETURNING id",
            {"owner": owner_id},
        ).scalar_one()
        version_id = execute(
            "INSERT INTO roadmap_versions "
            "(owner_id, source_id, version_key, version_number, month_number, "
            "content_hash, object_key, manifest, raw_payload, normalized_payload, "
            "mirror_status, state) VALUES "
            "(:owner, :source, 'month-1-v1', 1, 1, :hash, "
            "'private/roadmaps/month-1-v1.json', '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, "
            "'pending', 'draft') RETURNING id",
            {"owner": owner_id, "source": source_id, "hash": b"a" * 32},
        ).scalar_one()
        node_id = execute(
            "INSERT INTO curriculum_nodes "
            "(owner_id, roadmap_version_id, stable_id, ordinal, kind, title) "
            "VALUES (:owner, :version, 'day-1', 0, 'day', 'Day 1') RETURNING id",
            {"owner": owner_id, "version": version_id},
        ).scalar_one()

        with engine.connect() as connection:
            transaction = connection.begin()
            insert_task(
                connection,
                stable_id="correction-valid",
                block="correction_warmup",
                exercise_type=None,
                mapping_version=None,
            )
            insert_task(
                connection,
                stable_id="sql-valid",
                block="sql",
                exercise_type="sql_guided_lesson",
                mapping_version="seed-v1",
            )
            transaction.rollback()

        invalid = (
            ("correction-half-null", "correction_warmup", None, "seed-v1"),
            ("correction-with-refs", "correction_warmup", "official_reading", "seed-v1"),
            ("ordinary-null-refs", "sql", None, None),
            ("ordinary-half-null", "sql", "sql_guided_lesson", None),
        )
        for stable_id, block, exercise_type, mapping_version in invalid:
            with engine.connect() as connection:
                transaction = connection.begin()
                with pytest.raises((IntegrityError, DBAPIError)):
                    insert_task(
                        connection,
                        stable_id=stable_id,
                        block=block,
                        exercise_type=exercise_type,
                        mapping_version=mapping_version,
                    )
                transaction.rollback()
    finally:
        engine.dispose()
        command.downgrade(config, "base")

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

pytestmark = pytest.mark.integration

REVISION_TABLES = {
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


def test_study_activity_contract_and_round_trip(test_database_url: str) -> None:
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

    def rejects(statement: str, parameters: Mapping[str, Any] | None = None) -> None:
        with pytest.raises((IntegrityError, DBAPIError)):
            execute(statement, parameters)

    try:
        command.downgrade(config, "base")
        command.upgrade(config, "20260825_0003_study_activities")
        assert REVISION_TABLES <= set(inspect(engine).get_table_names())

        owner = execute(
            "INSERT INTO owners (github_user_id, github_login) "
            "VALUES (102269369, 'fgomensoro') RETURNING id"
        ).scalar_one()
        source = execute(
            "INSERT INTO roadmap_sources (owner_id, source_key, name, source_kind) "
            "VALUES (:owner, 'main', 'Roadmap', 'obsidian') RETURNING id",
            {"owner": owner},
        ).scalar_one()
        version = execute(
            "INSERT INTO roadmap_versions "
            "(owner_id, source_id, version_key, version_number, month_number, content_hash, "
            "object_key, manifest, raw_payload, normalized_payload, mirror_status, state) "
            "VALUES (:owner, :source, 'month-1-v1', 1, 1, :hash, "
            "'owners/1/roadmaps/month-1.json', '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, "
            "'not_required', 'draft') RETURNING id",
            {"owner": owner, "source": source, "hash": b"r" * 32},
        ).scalar_one()
        node = execute(
            "INSERT INTO curriculum_nodes "
            "(owner_id, roadmap_version_id, stable_id, ordinal, kind, title) "
            "VALUES (:owner, :version, 'week-1', 0, 'week', 'Week 1') RETURNING id",
            {"owner": owner, "version": version},
        ).scalar_one()
        task = execute(
            "INSERT INTO task_definitions "
            "(owner_id, roadmap_version_id, curriculum_node_id, stable_id, exercise_type, "
            "mapping_version, objective, timebox_minutes, block, required, output_contract, "
            "pass_contract, evidence_contract, source_references, allowed_ai_role) VALUES "
            "(:owner, :version, :node, 'sql-1', 'sql', 'v1', 'Solve SQL', 45, 'sql', true, "
            "'{}'::jsonb, '{}'::jsonb, '{}'::jsonb, '[]'::jsonb, 'reviewer') RETURNING id",
            {"owner": owner, "version": version, "node": node},
        ).scalar_one()
        execute(
            "INSERT INTO learner_settings "
            "(owner_id, timezone, study_start_date, active_roadmap_version_id) "
            "VALUES (:owner, 'America/Los_Angeles', DATE '2026-08-25', :version)",
            {"owner": owner, "version": version},
        )
        day = execute(
            "INSERT INTO study_days "
            "(owner_id, roadmap_version_id, local_date, planned_minutes, focused_minutes, "
            "day_type, status) VALUES (:owner, :version, DATE '2026-08-25', 240, 0, "
            "'weekday', 'planned') RETURNING id",
            {"owner": owner, "version": version},
        ).scalar_one()
        execute(
            "UPDATE study_days SET status = 'in_progress', started_at = now(), "
            "focused_minutes = 10 WHERE id = :day",
            {"day": day},
        )
        execute(
            "UPDATE study_days SET focused_minutes = 20 WHERE id = :day",
            {"day": day},
        )
        rejects(
            "UPDATE study_days SET focused_minutes = 19 WHERE id = :day",
            {"day": day},
        )
        activity = execute(
            "INSERT INTO activity_instances "
            "(owner_id, study_day_id, roadmap_version_id, task_definition_id, "
            "task_stable_id_snapshot, task_mapping_version_snapshot, task_objective_snapshot, "
            "task_timebox_minutes_snapshot, roadmap_version_key_snapshot, state, attempt_kind, "
            "assistance_mode, classification, timebox_minutes, source_hidden, optimistic_version, "
            "replacement_version) VALUES (:owner, :day, :version, :task, 'sql-1', 'v1', "
            "'Solve SQL', 45, 'month-1-v1', 'ready', 'attempt_a', 'none', 'required', "
            "45, false, 1, 1) RETURNING id",
            {"owner": owner, "day": day, "version": version, "task": task},
        ).scalar_one()
        rejects(
            "INSERT INTO activity_instances "
            "(owner_id, study_day_id, roadmap_version_id, task_definition_id, "
            "task_stable_id_snapshot, task_mapping_version_snapshot, task_objective_snapshot, "
            "task_timebox_minutes_snapshot, roadmap_version_key_snapshot, state, attempt_kind, "
            "assistance_mode, classification, timebox_minutes, source_hidden, optimistic_version, "
            "replacement_version) VALUES (:owner, :day, :version, :task, 'sql-1', 'v1', "
            "'Solve SQL', 45, 'month-1-v1', 'ready', 'attempt_a', 'none', 'required', "
            "45, false, 1, 1)",
            {"owner": owner, "day": day, "version": version, "task": task},
        )
        rejects(
            "UPDATE activity_instances SET state = 'feedback_ready', optimistic_version = 2 "
            "WHERE id = :activity",
            {"activity": activity},
        )
        execute(
            "UPDATE activity_instances SET state = 'active', started_at = now(), "
            "optimistic_version = 2 WHERE id = :activity",
            {"activity": activity},
        )
        rejects(
            "INSERT INTO activity_instances "
            "(owner_id, study_day_id, roadmap_version_id, task_definition_id, "
            "task_stable_id_snapshot, task_mapping_version_snapshot, task_objective_snapshot, "
            "task_timebox_minutes_snapshot, roadmap_version_key_snapshot, state, attempt_kind, "
            "assistance_mode, classification, timebox_minutes, source_hidden, optimistic_version, "
            "replacement_version) VALUES (:owner, :day, :version, :task, 'sql-1', 'v1', "
            "'Solve SQL', 45, 'month-1-v1', 'active', 'attempt_a', 'none', 'required', "
            "45, false, 1, 2)",
            {"owner": owner, "day": day, "version": version, "task": task},
        )

        timer = execute(
            "INSERT INTO activity_timer_sessions "
            "(owner_id, activity_instance_id, idempotency_key, started_at, "
            "last_heartbeat_at, counted_seconds) VALUES "
            "(:owner, :activity, 'timer-start-1', now(), now(), 0) RETURNING id",
            {"owner": owner, "activity": activity},
        ).scalar_one()
        rejects(
            "INSERT INTO activity_timer_sessions "
            "(owner_id, activity_instance_id, idempotency_key, started_at, "
            "last_heartbeat_at, counted_seconds) VALUES "
            "(:owner, :activity, 'timer-start-2', now(), now(), 0)",
            {"owner": owner, "activity": activity},
        )
        rejects(
            "INSERT INTO activity_timer_sessions "
            "(owner_id, activity_instance_id, idempotency_key, started_at, "
            "last_heartbeat_at, counted_seconds, ended_at) VALUES "
            "(:owner, :activity, 'timer-start-1', now(), now(), 0, now())",
            {"owner": owner, "activity": activity},
        )
        execute(
            "UPDATE activity_timer_sessions SET ended_at = now() WHERE id = :timer",
            {"timer": timer},
        )

        attempt_a = execute(
            "INSERT INTO attempts "
            "(owner_id, activity_instance_id, attempt_kind, original_text, audience, prompt, "
            "assistance_mode, commitment_hash, committed_at) VALUES "
            "(:owner, :activity, 'attempt_a', 'Original answer', 'hiring_manager', "
            "'Explain the incident', 'none', :hash, now()) RETURNING id",
            {"owner": owner, "activity": activity, "hash": b"a" * 32},
        ).scalar_one()
        rejects(
            "INSERT INTO attempts "
            "(owner_id, activity_instance_id, attempt_kind, parent_attempt_id, original_text, "
            "audience, prompt, assistance_mode, commitment_hash, committed_at) VALUES "
            "(:owner, :activity, 'attempt_c', :parent, 'C', 'manager', 'prompt', 'none', "
            ":hash, now())",
            {"owner": owner, "activity": activity, "parent": attempt_a, "hash": b"c" * 32},
        )
        rejects(
            "UPDATE attempts SET original_text = 'rewritten' WHERE id = :attempt",
            {"attempt": attempt_a},
        )
        rejects("DELETE FROM attempts WHERE id = :attempt", {"attempt": attempt_a})

        artifact = execute(
            "INSERT INTO artifacts "
            "(owner_id, object_key, content_hash, content_type, original_filename, byte_size, "
            "artifact_class, encryption_metadata, immutable_version) VALUES "
            "(:owner, 'owners/1/audio/a.wav', :hash, 'audio/wav', 'answer.wav', 100, "
            "'original_audio', jsonb_build_object("
            "'schema_version', 1, 'encrypted', false, 'algorithm', NULL, "
            "'key_reference', NULL), 1) RETURNING id",
            {"owner": owner, "hash": b"o" * 32},
        ).scalar_one()
        execute(
            "INSERT INTO activity_artifact_links "
            "(owner_id, activity_instance_id, attempt_id, artifact_id, link_role) VALUES "
            "(:owner, :activity, :attempt, :artifact, 'presentation_audio')",
            {"owner": owner, "activity": activity, "attempt": attempt_a, "artifact": artifact},
        )
        rejects(
            "INSERT INTO activity_artifact_links "
            "(owner_id, activity_instance_id, attempt_id, artifact_id, link_role) VALUES "
            "(:owner, :activity, :attempt, :artifact, 'presentation_audio')",
            {"owner": owner, "activity": activity, "attempt": attempt_a, "artifact": artifact},
        )
        execute(
            "INSERT INTO activity_artifact_links "
            "(owner_id, activity_instance_id, attempt_id, artifact_id, link_role) VALUES "
            "(:owner, :activity, NULL, :artifact, 'supporting')",
            {"owner": owner, "activity": activity, "artifact": artifact},
        )
        rejects(
            "INSERT INTO activity_artifact_links "
            "(owner_id, activity_instance_id, attempt_id, artifact_id, link_role) VALUES "
            "(:owner, :activity, NULL, :artifact, 'supporting')",
            {"owner": owner, "activity": activity, "artifact": artifact},
        )
        second_day = execute(
            "INSERT INTO study_days "
            "(owner_id, roadmap_version_id, local_date, planned_minutes, focused_minutes, "
            "day_type, status) VALUES (:owner, :version, DATE '2026-08-26', 240, 0, "
            "'weekday', 'planned') RETURNING id",
            {"owner": owner, "version": version},
        ).scalar_one()
        replacement = execute(
            "INSERT INTO activity_instances "
            "(owner_id, study_day_id, roadmap_version_id, task_definition_id, "
            "task_stable_id_snapshot, task_mapping_version_snapshot, task_objective_snapshot, "
            "task_timebox_minutes_snapshot, roadmap_version_key_snapshot, state, attempt_kind, "
            "assistance_mode, classification, timebox_minutes, source_hidden, optimistic_version, "
            "replacement_version) VALUES (:owner, :day, :version, :task, 'sql-1', 'v1', "
            "'Solve SQL', 45, 'month-1-v1', 'ready', 'attempt_b', 'none', 'required', "
            "10, false, 1, 1) RETURNING id",
            {"owner": owner, "day": second_day, "version": version, "task": task},
        ).scalar_one()
        rejects(
            "INSERT INTO attempts "
            "(owner_id, activity_instance_id, attempt_kind, original_text, audience, prompt, "
            "assistance_mode, commitment_hash, committed_at) VALUES "
            "(:owner, :activity, 'attempt_a', 'Wrong activity kind', 'hiring_manager', "
            "'Explain the incident', 'none', :hash, now())",
            {"owner": owner, "activity": replacement, "hash": b"m" * 32},
        )
        rejects(
            "INSERT INTO attempts "
            "(owner_id, activity_instance_id, attempt_kind, parent_attempt_id, original_text, "
            "audience, prompt, assistance_mode, commitment_hash, committed_at) VALUES "
            "(:owner, :activity, 'attempt_b', :parent, 'Different prompt', 'hiring_manager', "
            "'A different prompt', 'none', :hash, now())",
            {"owner": owner, "activity": replacement, "parent": attempt_a, "hash": b"d" * 32},
        )
        attempt_b = execute(
            "INSERT INTO attempts "
            "(owner_id, activity_instance_id, attempt_kind, parent_attempt_id, original_text, "
            "audience, prompt, assistance_mode, commitment_hash, committed_at) VALUES "
            "(:owner, :activity, 'attempt_b', :parent, 'Improved answer', 'hiring_manager', "
            "'Explain the incident', 'none', :hash, now()) RETURNING id",
            {"owner": owner, "activity": replacement, "parent": attempt_a, "hash": b"b" * 32},
        ).scalar_one()
        execute(
            "INSERT INTO activity_artifact_links "
            "(owner_id, activity_instance_id, attempt_id, artifact_id, link_role) VALUES "
            "(:owner, :activity, :attempt, :artifact, 'presentation_audio')",
            {"owner": owner, "activity": replacement, "attempt": attempt_b, "artifact": artifact},
        )
        artifact_links = execute(
            "SELECT activity_instance_id, attempt_id, link_role "
            "FROM activity_artifact_links WHERE artifact_id = :artifact",
            {"artifact": artifact},
        ).all()
        assert len(artifact_links) == 3
        assert {
            (row.activity_instance_id, row.attempt_id, row.link_role) for row in artifact_links
        } == {
            (activity, attempt_a, "presentation_audio"),
            (activity, None, "supporting"),
            (replacement, attempt_b, "presentation_audio"),
        }
        rejects("UPDATE artifacts SET byte_size = 101 WHERE id = :artifact", {"artifact": artifact})

        command.downgrade(config, "20260825_0002_curriculum")
        assert not (REVISION_TABLES & set(inspect(engine).get_table_names()))
    finally:
        engine.dispose()

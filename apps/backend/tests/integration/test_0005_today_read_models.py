from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

pytestmark = pytest.mark.integration

REVISION_TABLES = {
    "corrections",
    "interviews",
    "activity_processing_statuses",
    "notifications",
    "outbox_events",
    "background_jobs",
    "notification_delivery_cursor",
}


def test_today_notification_contract_and_round_trip(test_database_url: str) -> None:
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
        command.upgrade(config, "20260825_0005_today_read_models")
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
            "(:owner, :version, :node, 'case-1', 'troubleshooting_case', 'seed-v1', "
            "'Solve a case', 60, 'tam_case', true, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, "
            "'[]'::jsonb, 'interviewer') RETURNING id",
            {"owner": owner, "version": version, "node": node},
        ).scalar_one()
        day = execute(
            "INSERT INTO study_days "
            "(owner_id, roadmap_version_id, local_date, planned_minutes, focused_minutes, "
            "day_type, status) VALUES (:owner, :version, DATE '2026-08-26', 240, 0, "
            "'weekday', 'planned') RETURNING id",
            {"owner": owner, "version": version},
        ).scalar_one()
        activity_a = execute(
            "INSERT INTO activity_instances "
            "(owner_id, study_day_id, roadmap_version_id, task_definition_id, "
            "task_stable_id_snapshot, task_mapping_version_snapshot, task_objective_snapshot, "
            "task_timebox_minutes_snapshot, roadmap_version_key_snapshot, state, attempt_kind, "
            "assistance_mode, classification, timebox_minutes, source_hidden, optimistic_version, "
            "replacement_version) VALUES (:owner, :day, :version, :task, 'case-1', 'seed-v1', "
            "'Solve a case', 60, 'month-1-v1', 'ready', 'attempt_a', 'none', 'required', "
            "60, false, 1, 1) RETURNING id",
            {"owner": owner, "day": day, "version": version, "task": task},
        ).scalar_one()
        activity_b = execute(
            "INSERT INTO activity_instances "
            "(owner_id, study_day_id, roadmap_version_id, task_definition_id, "
            "task_stable_id_snapshot, task_mapping_version_snapshot, task_objective_snapshot, "
            "task_timebox_minutes_snapshot, roadmap_version_key_snapshot, state, attempt_kind, "
            "assistance_mode, classification, timebox_minutes, source_hidden, optimistic_version, "
            "replacement_version, replaces_activity_id) VALUES "
            "(:owner, :day, :version, :task, 'case-1', 'seed-v1', 'Solve a case', 60, "
            "'month-1-v1', 'ready', 'attempt_b', 'none', 'required', 10, false, 1, 2, "
            ":activity_a) RETURNING id",
            {
                "owner": owner,
                "day": day,
                "version": version,
                "task": task,
                "activity_a": activity_a,
            },
        ).scalar_one()

        correction = execute(
            "INSERT INTO corrections "
            "(owner_id, source_activity_id, priority, status, due_date, instruction) "
            "VALUES (:owner, :activity, 1, 'pending', DATE '2026-08-27', "
            "'Lead with the conclusion.') RETURNING id",
            {"owner": owner, "activity": activity_a},
        ).scalar_one()
        execute(
            "UPDATE corrections SET status = 'scheduled', attempt_b_activity_id = :attempt_b, "
            "updated_at = now() WHERE owner_id = :owner AND id = :correction",
            {"owner": owner, "correction": correction, "attempt_b": activity_b},
        )
        rejects(
            "UPDATE corrections SET source_activity_id = :attempt_b "
            "WHERE owner_id = :owner AND id = :correction",
            {"owner": owner, "correction": correction, "attempt_b": activity_b},
        )

        execute(
            "INSERT INTO interviews "
            "(owner_id, company, role, stage, starts_at, expected_duration_minutes, status, "
            "privacy_permission_code) VALUES "
            "(:owner, 'Example Co', 'TAM', 'hiring_manager', now() + interval '1 day', "
            "60, 'scheduled', 'permission_not_requested')",
            {"owner": owner},
        )

        processing = execute(
            "INSERT INTO activity_processing_statuses "
            "(owner_id, activity_instance_id, state, progress_label) "
            "VALUES (:owner, :activity, 'uploaded', 'uploaded') RETURNING id",
            {"owner": owner, "activity": activity_a},
        ).scalar_one()
        rejects(
            "UPDATE activity_processing_statuses SET state = 'ready', "
            "progress_label = 'ready', updated_at = now() "
            "WHERE owner_id = :owner AND id = :processing",
            {"owner": owner, "processing": processing},
        )
        execute(
            "UPDATE activity_processing_statuses SET state = 'needs_attention', "
            "progress_label = 'action_required', last_error_category = 'processing_failure', "
            "last_error_details = '{\"schema_version\": 1, \"attempt\": 1}'::jsonb, "
            "updated_at = now() WHERE owner_id = :owner AND id = :processing",
            {"owner": owner, "processing": processing},
        )
        rejects(
            "UPDATE activity_processing_statuses SET "
            "last_error_details = '{\"schema_version\": 1, \"message\": \"raw excerpt\"}'::jsonb "
            "WHERE owner_id = :owner AND id = :processing",
            {"owner": owner, "processing": processing},
        )

        for notification_type in (
            "feedback_ready",
            "correction_due",
            "upcoming_real_interview",
            "saturday_assessment",
            "processing_failure_requires_action",
        ):
            execute(
                "INSERT INTO notifications "
                "(owner_id, notification_type, subject_kind, subject_id) "
                "VALUES (:owner, :notification_type, 'activity', :activity)",
                {
                    "owner": owner,
                    "notification_type": notification_type,
                    "activity": activity_a,
                },
            )
        rejects(
            "INSERT INTO notifications "
            "(owner_id, notification_type, subject_kind, subject_id) "
            "VALUES (:owner, 'study_streak', 'activity', :activity)",
            {"owner": owner, "activity": activity_a},
        )

        outbox = execute(
            "INSERT INTO outbox_events "
            "(owner_id, aggregate_type, aggregate_id, event_type, payload_schema_version, "
            "payload, idempotency_key) VALUES "
            "(:owner, 'activity', :activity, 'activity.feedback_ready', 1, "
            "jsonb_build_object('schema_version', 1, 'subject_id', :activity), 'event-1') "
            "RETURNING id",
            {"owner": owner, "activity": activity_a},
        ).scalar_one()
        rejects(
            "INSERT INTO outbox_events "
            "(owner_id, aggregate_type, aggregate_id, event_type, payload_schema_version, "
            "payload, idempotency_key) VALUES "
            "(:owner, 'activity', :activity, 'activity.feedback_ready', 1, "
            "jsonb_build_object('schema_version', 1, 'subject_id', :activity), 'event-1')",
            {"owner": owner, "activity": activity_a},
        )
        execute(
            "UPDATE outbox_events SET attempts = 1, published_at = now() "
            "WHERE owner_id = :owner AND id = :outbox",
            {"owner": owner, "outbox": outbox},
        )
        rejects(
            "UPDATE outbox_events SET attempts = 2 "
            "WHERE owner_id = :owner AND id = :outbox",
            {"owner": owner, "outbox": outbox},
        )

        job = execute(
            "INSERT INTO background_jobs "
            "(owner_id, kind, payload_schema_version, payload, priority, state, "
            "idempotency_key, available_at, attempt_count, max_attempts) VALUES "
            "(:owner, 'transcribe_activity', 1, "
            "jsonb_build_object('schema_version', 1, 'subject_id', :activity), 50, "
            "'queued', 'job-1', now(), 0, 3) RETURNING id",
            {"owner": owner, "activity": activity_a},
        ).scalar_one()
        rejects(
            "INSERT INTO background_jobs "
            "(owner_id, kind, payload_schema_version, payload, priority, state, "
            "idempotency_key, available_at, attempt_count, max_attempts) VALUES "
            "(:owner, 'transcribe_activity', 1, "
            "jsonb_build_object('schema_version', 1, 'subject_id', :activity), 50, "
            "'queued', 'job-1', now(), 0, 3)",
            {"owner": owner, "activity": activity_a},
        )
        execute(
            "UPDATE background_jobs SET state = 'running', attempt_count = 1, "
            "lease_owner = 'worker-1', lease_expires_at = now() + interval '5 minutes', "
            "started_at = now(), updated_at = now() "
            "WHERE owner_id = :owner AND id = :job",
            {"owner": owner, "job": job},
        )
        execute(
            "UPDATE background_jobs SET lease_expires_at = now() + interval '10 minutes', "
            "updated_at = now() WHERE owner_id = :owner AND id = :job",
            {"owner": owner, "job": job},
        )
        execute(
            "UPDATE background_jobs SET state = 'queued', lease_owner = NULL, "
            "lease_expires_at = NULL, available_at = now() + interval '1 minute', "
            "last_error_category = 'transient_dependency', "
            "last_error_details = '{\"schema_version\": 1, \"attempt\": 1}'::jsonb, "
            "updated_at = now() WHERE owner_id = :owner AND id = :job",
            {"owner": owner, "job": job},
        )
        execute(
            "UPDATE background_jobs SET state = 'running', attempt_count = 2, "
            "lease_owner = 'worker-2', lease_expires_at = now() + interval '5 minutes', "
            "last_error_category = NULL, last_error_details = NULL, updated_at = now() "
            "WHERE owner_id = :owner AND id = :job",
            {"owner": owner, "job": job},
        )
        execute(
            "UPDATE background_jobs SET state = 'succeeded', lease_owner = NULL, "
            "lease_expires_at = NULL, completed_at = now(), updated_at = now() "
            "WHERE owner_id = :owner AND id = :job",
            {"owner": owner, "job": job},
        )
        rejects(
            "UPDATE background_jobs SET state = 'queued', completed_at = NULL "
            "WHERE owner_id = :owner AND id = :job",
            {"owner": owner, "job": job},
        )
        rejects(
            "INSERT INTO background_jobs "
            "(owner_id, kind, payload_schema_version, payload, priority, state, "
            "idempotency_key, available_at, attempt_count, max_attempts) VALUES "
            "(:owner, 'transcribe_activity', 1, "
            "'{\"schema_version\": 1, \"subject_id\": 1, \"url\": \"secret\"}'::jsonb, "
            "50, 'queued', 'job-bad', now(), 0, 3)",
            {"owner": owner},
        )

        cursor = execute(
            "INSERT INTO notification_delivery_cursor "
            "(owner_id, stream_key, last_event_id) VALUES (:owner, 'status', 5) RETURNING id",
            {"owner": owner},
        ).scalar_one()
        execute(
            "UPDATE notification_delivery_cursor SET last_event_id = 6, updated_at = now() "
            "WHERE owner_id = :owner AND id = :cursor",
            {"owner": owner, "cursor": cursor},
        )
        rejects(
            "UPDATE notification_delivery_cursor SET last_event_id = 4, updated_at = now() "
            "WHERE owner_id = :owner AND id = :cursor",
            {"owner": owner, "cursor": cursor},
        )

        rejects(
            "DELETE FROM activity_instances WHERE owner_id = :owner AND id = :activity",
            {"owner": owner, "activity": activity_a},
        )

        command.downgrade(config, "base")
        assert not REVISION_TABLES.intersection(inspect(engine).get_table_names())
        assert "tamforge_validate_reference_payload_v1" not in {
            row[0]
            for row in execute(
                "SELECT proname FROM pg_proc JOIN pg_namespace n ON n.oid = pronamespace "
                "WHERE n.nspname = 'public'"
            )
        }
    finally:
        engine.dispose()

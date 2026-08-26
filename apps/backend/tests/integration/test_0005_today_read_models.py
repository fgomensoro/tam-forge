from __future__ import annotations

from collections.abc import Mapping
from datetime import date
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

        future_day = execute(
            "INSERT INTO study_days "
            "(owner_id, roadmap_version_id, local_date, planned_minutes, focused_minutes, "
            "day_type, status) VALUES (:owner, :version, DATE '2026-08-27', 240, 0, "
            "'weekday', 'planned') RETURNING id",
            {"owner": owner, "version": version},
        ).scalar_one()
        activity_b_correct = execute(
            "INSERT INTO activity_instances "
            "(owner_id, study_day_id, roadmap_version_id, task_definition_id, "
            "task_stable_id_snapshot, task_mapping_version_snapshot, task_objective_snapshot, "
            "task_timebox_minutes_snapshot, roadmap_version_key_snapshot, state, attempt_kind, "
            "assistance_mode, classification, timebox_minutes, source_hidden, optimistic_version, "
            "replacement_version) VALUES (:owner, :day, :version, :task, 'case-1', 'seed-v1', "
            "'Solve a case', 60, 'month-1-v1', 'ready', 'attempt_b', 'none', 'required', "
            "10, false, 1, 1) RETURNING id",
            {"owner": owner, "day": future_day, "version": version, "task": task},
        ).scalar_one()

        other_task = execute(
            "INSERT INTO task_definitions "
            "(owner_id, roadmap_version_id, curriculum_node_id, stable_id, exercise_type, "
            "mapping_version, objective, timebox_minutes, block, required, output_contract, "
            "pass_contract, evidence_contract, source_references, allowed_ai_role) VALUES "
            "(:owner, :version, :node, 'case-2', 'troubleshooting_case', 'seed-v1', "
            "'Solve another case', 60, 'tam_case', true, '{}'::jsonb, '{}'::jsonb, "
            "'{}'::jsonb, '[]'::jsonb, 'interviewer') RETURNING id",
            {"owner": owner, "version": version, "node": node},
        ).scalar_one()
        other_activity_a = execute(
            "INSERT INTO activity_instances "
            "(owner_id, study_day_id, roadmap_version_id, task_definition_id, "
            "task_stable_id_snapshot, task_mapping_version_snapshot, task_objective_snapshot, "
            "task_timebox_minutes_snapshot, roadmap_version_key_snapshot, state, attempt_kind, "
            "assistance_mode, classification, timebox_minutes, source_hidden, optimistic_version, "
            "replacement_version) VALUES (:owner, :day, :version, :task, 'case-2', 'seed-v1', "
            "'Solve another case', 60, 'month-1-v1', 'ready', 'attempt_a', 'none', "
            "'required', 60, false, 1, 1) RETURNING id",
            {"owner": owner, "day": day, "version": version, "task": other_task},
        ).scalar_one()

        attempt = execute(
            "INSERT INTO attempts "
            "(owner_id, activity_instance_id, attempt_kind, original_text, audience, prompt, "
            "assistance_mode, commitment_hash, committed_at) VALUES "
            "(:owner, :activity, 'attempt_a', 'Answer', 'hiring_manager', 'Solve', 'none', "
            ":hash, now()) RETURNING id",
            {"owner": owner, "activity": activity_a, "hash": b"a" * 32},
        ).scalar_one()
        other_attempt_a = execute(
            "INSERT INTO attempts "
            "(owner_id, activity_instance_id, attempt_kind, original_text, audience, prompt, "
            "assistance_mode, commitment_hash, committed_at) VALUES "
            "(:owner, :activity, 'attempt_a', 'Other answer', 'hiring_manager', 'Solve', "
            "'none', :hash, now()) RETURNING id",
            {"owner": owner, "activity": other_activity_a, "hash": b"o" * 32},
        ).scalar_one()
        config_seed = execute(
            "INSERT INTO config_seed_versions "
            "(owner_id, version_key, schema_version, content_hash) "
            "VALUES (:owner, 'seed-v1', 1, :hash) RETURNING id",
            {"owner": owner, "hash": b"s" * 32},
        ).scalar_one()
        competency = execute(
            "INSERT INTO competencies "
            "(owner_id, config_seed_version_id, slug, name, baseline_level, "
            "month_one_target, final_target) VALUES "
            "(:owner, :config, 'structured_troubleshooting', 'Structured troubleshooting', "
            "2, 3, 4) RETURNING id",
            {"owner": owner, "config": config_seed},
        ).scalar_one()
        exercise = execute(
            "INSERT INTO exercise_type_versions "
            "(owner_id, config_seed_version_id, exercise_type, mapping_version, evidence_mode, "
            "condition_code, tags) VALUES "
            "(:owner, :config, 'troubleshooting_case', 'seed-v1', 'independent_practice', "
            "'always', '[\"observability\"]'::jsonb) RETURNING id",
            {"owner": owner, "config": config_seed},
        ).scalar_one()
        execute(
            "INSERT INTO exercise_skill_mappings "
            "(owner_id, config_seed_version_id, exercise_type_version_id, competency_id, "
            "impact, condition_code) VALUES "
            "(:owner, :config, :exercise, :competency, 1, 'always')",
            {
                "owner": owner,
                "config": config_seed,
                "exercise": exercise,
                "competency": competency,
            },
        )
        rubric = execute(
            "INSERT INTO rubric_versions "
            "(owner_id, config_seed_version_id, rubric_key, version_key, name, scope_code, "
            "scale_min, scale_max) VALUES "
            "(:owner, :config, 'tam-case', 'v1', 'TAM case', 'tam', 0, 4) RETURNING id",
            {"owner": owner, "config": config_seed},
        ).scalar_one()
        dimension = execute(
            "INSERT INTO rubric_dimensions "
            "(owner_id, config_seed_version_id, rubric_version_id, dimension_key, name, "
            "weight, max_score, ordinal, availability_rule_code) VALUES "
            "(:owner, :config, :rubric, 'diagnosis', 'Diagnosis', 1, 4, 0, 'always') "
            "RETURNING id",
            {"owner": owner, "config": config_seed, "rubric": rubric},
        ).scalar_one()
        evaluation = execute(
            "INSERT INTO rubric_evaluations "
            "(owner_id, config_seed_version_id, activity_instance_id, attempt_id, "
            "rubric_version_id, evaluator_kind, evaluation_schema_version, input_manifest, "
            "evaluated_at) VALUES (:owner, :config, :activity, :attempt, :rubric, "
            "'ai_rubric_reviewer', 1, jsonb_build_object('schema_version', 1, "
            "'artifact_ids', '[]'::jsonb), now()) RETURNING id",
            {
                "owner": owner,
                "config": config_seed,
                "activity": activity_a,
                "attempt": attempt,
                "rubric": rubric,
            },
        ).scalar_one()
        dimension_score = execute(
            "INSERT INTO rubric_dimension_scores "
            "(owner_id, config_seed_version_id, rubric_evaluation_id, rubric_version_id, "
            "rubric_dimension_id, availability, score, weight_used, evidence_manifest) "
            "VALUES (:owner, :config, :evaluation, :rubric, :dimension, 'scored', 3, 1, "
            "jsonb_build_object('schema_version', 1, 'artifact_ids', '[]'::jsonb, "
            "'observation_ids', '[]'::jsonb)) RETURNING id",
            {
                "owner": owner,
                "config": config_seed,
                "evaluation": evaluation,
                "rubric": rubric,
                "dimension": dimension,
            },
        ).scalar_one()
        evidence = execute(
            "INSERT INTO skill_evidence_events "
            "(owner_id, config_seed_version_id, activity_instance_id, attempt_id, "
            "rubric_evaluation_id, rubric_version_id, exercise_type_version_id, competency_id, "
            "formula_version, practice_mode, assistance_code, evaluator_kind, difficulty_code, "
            "raw_dimension_scores, raw_score_numerator, raw_score_denominator, "
            "performance_score, exercise_skill_impact, practice_mode_factor, "
            "ai_independence_factor, evaluator_confidence_factor, difficulty_factor, "
            "effective_weight, qualifying_for_level, qualification_reason_code, explanation, "
            "occurred_at) VALUES (:owner, :config, :activity, :attempt, :evaluation, :rubric, "
            ":exercise, :competency, 'skill-v1', 'independent_practice', 'no_ai', "
            "'ai_rubric_reviewer', 'standard', jsonb_build_object('schema_version', 1, "
            "'scores', jsonb_build_array(jsonb_build_object("
            "'dimension_score_id', :dimension_score, 'score', 3, 'weight', 1))), "
            "3, 1, 3, 1, 0.65, 1, 0.75, 1, 0.4875, true, 'qualifies', "
            "jsonb_build_object('schema_version', 1, "
            "'summary_code', 'independent_scored_evidence', "
            "'dimension_score_ids', jsonb_build_array(:dimension_score), "
            "'discount_codes', '[]'::jsonb), now()) RETURNING id",
            {
                "owner": owner,
                "config": config_seed,
                "activity": activity_a,
                "attempt": attempt,
                "evaluation": evaluation,
                "rubric": rubric,
                "exercise": exercise,
                "competency": competency,
                "dimension_score": dimension_score,
            },
        ).scalar_one()

        from tamforge_backend.today.service import (
            CorrectionSlotLimitError,
            create_correction_with_slot_reservation,
        )

        with engine.begin() as connection:
            correction = create_correction_with_slot_reservation(
                connection,
                owner_id=owner,
                source_activity_id=activity_a,
                source_evidence_event_id=evidence,
                priority=1,
                due_date=date(2026, 8, 27),
                instruction="Lead with the conclusion.",
            )
            second_correction = create_correction_with_slot_reservation(
                connection,
                owner_id=owner,
                source_activity_id=activity_a,
                source_evidence_event_id=evidence,
                priority=2,
                due_date=date(2026, 8, 27),
                instruction="Name the evidence before the implementation detail.",
            )
            with pytest.raises(CorrectionSlotLimitError, match="two active corrections"):
                create_correction_with_slot_reservation(
                    connection,
                    owner_id=owner,
                    source_activity_id=activity_a,
                    source_evidence_event_id=evidence,
                    priority=1,
                    due_date=date(2026, 8, 27),
                    instruction="This third correction must not be inserted.",
                )
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
        rejects(
            "UPDATE corrections SET due_date = DATE '2026-08-28' "
            "WHERE owner_id = :owner AND id = :correction",
            {"owner": owner, "correction": correction},
        )
        execute(
            "INSERT INTO attempts "
            "(owner_id, activity_instance_id, attempt_kind, parent_attempt_id, original_text, "
            "audience, prompt, assistance_mode, commitment_hash, committed_at) VALUES "
            "(:owner, :activity, 'attempt_b', :parent, 'Wrong lineage', 'hiring_manager', "
            "'Solve', 'none', :hash, now())",
            {
                "owner": owner,
                "activity": activity_b,
                "parent": other_attempt_a,
                "hash": b"w" * 32,
            },
        )
        rejects(
            "UPDATE corrections SET status = 'completed', completed_at = now(), "
            "updated_at = now() WHERE owner_id = :owner AND id = :correction",
            {"owner": owner, "correction": correction},
        )
        execute(
            "UPDATE corrections SET status = 'superseded', completed_at = now(), "
            "updated_at = now() WHERE owner_id = :owner AND id = :correction",
            {"owner": owner, "correction": correction},
        )
        with engine.begin() as connection:
            rescheduled_correction = create_correction_with_slot_reservation(
                connection,
                owner_id=owner,
                source_activity_id=activity_a,
                source_evidence_event_id=evidence,
                priority=1,
                due_date=date(2026, 8, 28),
                instruction="Lead with the conclusion.",
            )
        assert rescheduled_correction != correction
        execute(
            "UPDATE corrections SET status = 'scheduled', attempt_b_activity_id = :attempt_b, "
            "updated_at = now() WHERE owner_id = :owner AND id = :correction",
            {
                "owner": owner,
                "correction": second_correction,
                "attempt_b": activity_b_correct,
            },
        )
        execute(
            "INSERT INTO attempts "
            "(owner_id, activity_instance_id, attempt_kind, parent_attempt_id, original_text, "
            "audience, prompt, assistance_mode, commitment_hash, committed_at) VALUES "
            "(:owner, :activity, 'attempt_b', :parent, 'Corrected answer', 'hiring_manager', "
            "'Solve', 'none', :hash, now())",
            {
                "owner": owner,
                "activity": activity_b_correct,
                "parent": attempt,
                "hash": b"b" * 32,
            },
        )
        execute(
            "UPDATE corrections SET status = 'completed', completed_at = now(), "
            "updated_at = now() WHERE owner_id = :owner AND id = :correction",
            {"owner": owner, "correction": second_correction},
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
        rejects(
            "UPDATE background_jobs SET state = 'queued', lease_owner = NULL, "
            "lease_expires_at = NULL, available_at = now() + interval '1 minute', "
            "last_error_category = 'transient_dependency', "
            "last_error_details = '{\"schema_version\": 1, \"attempt\": 1}'::jsonb, "
            "updated_at = now() WHERE owner_id = :owner AND id = :job",
            {"owner": owner, "job": job},
        )
        expired_job = execute(
            "INSERT INTO background_jobs "
            "(owner_id, kind, payload_schema_version, payload, priority, state, "
            "idempotency_key, available_at, attempt_count, max_attempts, lease_owner, "
            "lease_expires_at, created_at, updated_at, started_at) VALUES "
            "(:owner, 'transcribe_activity', 1, "
            "jsonb_build_object('schema_version', 1, 'subject_id', :activity), 50, "
            "'running', 'job-expired', now() - interval '2 minutes', 1, 3, 'worker-old', "
            "now() - interval '1 minute', now() - interval '2 minutes', "
            "now() - interval '2 minutes', now() - interval '2 minutes') RETURNING id",
            {"owner": owner, "activity": activity_a},
        ).scalar_one()
        execute(
            "UPDATE background_jobs SET state = 'queued', lease_owner = NULL, "
            "lease_expires_at = NULL, available_at = now() + interval '1 minute', "
            "last_error_category = 'transient_dependency', "
            "last_error_details = '{\"schema_version\": 1, \"attempt\": 1}'::jsonb, "
            "updated_at = now() WHERE owner_id = :owner AND id = :job",
            {"owner": owner, "job": expired_job},
        )
        execute(
            "UPDATE background_jobs SET state = 'running', attempt_count = 2, "
            "lease_owner = 'worker-2', lease_expires_at = now() + interval '5 minutes', "
            "last_error_category = NULL, last_error_details = NULL, updated_at = now() "
            "WHERE owner_id = :owner AND id = :job",
            {"owner": owner, "job": expired_job},
        )
        execute(
            "UPDATE background_jobs SET state = 'succeeded', lease_owner = NULL, "
            "lease_expires_at = NULL, completed_at = now(), updated_at = now() "
            "WHERE owner_id = :owner AND id = :job",
            {"owner": owner, "job": expired_job},
        )
        rejects(
            "UPDATE background_jobs SET state = 'queued', completed_at = NULL "
            "WHERE owner_id = :owner AND id = :job",
            {"owner": owner, "job": expired_job},
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
        rejects(
            "INSERT INTO background_jobs "
            "(owner_id, kind, payload_schema_version, payload, priority, state, "
            "idempotency_key, available_at, attempt_count, max_attempts) VALUES "
            "(:owner, 'transcribe_activity', 1, "
            "'{\"schema_version\": 1, \"subject_id\": 9223372036854775808}'::jsonb, "
            "50, 'queued', 'job-bigint-overflow', now(), 0, 3)",
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

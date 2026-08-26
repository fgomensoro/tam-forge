from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

pytestmark = pytest.mark.integration

REVISION_TABLES = {
    "config_seed_versions",
    "competencies",
    "exercise_type_versions",
    "exercise_skill_mappings",
    "rubric_versions",
    "rubric_dimensions",
    "rubric_evaluations",
    "rubric_dimension_scores",
    "skill_evidence_events",
    "skill_snapshots",
    "portfolio_judgment_scores",
}
COMPETENCIES = (
    ("api_integration_architecture", "API and integration architecture", "3", "3", "3.25"),
    ("structured_troubleshooting", "Structured troubleshooting", "2", "2.5", "3"),
    ("sql_reconciliation", "SQL and reconciliation", "1", "2", "2.75"),
    ("distributed_systems_reliability", "Distributed systems and reliability", "2", "2.5", "3"),
    ("payments_fintech_systems", "Payments and fintech systems", "2", "2.5", "3"),
    ("technical_discovery", "Technical discovery", "2", "2.5", "3"),
    ("incident_escalation_management", "Incident and escalation management", "2", "2.5", "3"),
    (
        "implementation_project_management",
        "Implementation and project management",
        "2",
        "2.5",
        "2.75",
    ),
    ("proactive_account_strategy", "Proactive account strategy", "2", "2.5", "2.75"),
    ("executive_communication", "Executive communication", "1", "2", "3"),
    ("cross_functional_influence", "Cross-functional influence", "2", "2.5", "2.75"),
    ("business_value_framing", "Business and value framing", "1", "2", "3"),
    ("technical_writing", "Technical writing", "1", "2", "2.75"),
    ("tam_english", "TAM English", "1", "2", "2.75"),
)


def test_evidence_scoring_contract_and_round_trip(test_database_url: str) -> None:
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
        command.upgrade(config, "20260825_0004_evidence_scoring")
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
        execute(
            "UPDATE study_days SET status = 'in_progress', started_at = now(), "
            "focused_minutes = 60 WHERE owner_id = :owner AND id = :day",
            {"owner": owner, "day": day},
        )
        activity = execute(
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
        attempt = execute(
            "INSERT INTO attempts "
            "(owner_id, activity_instance_id, attempt_kind, original_text, audience, prompt, "
            "assistance_mode, commitment_hash, committed_at) VALUES "
            "(:owner, :activity, 'attempt_a', 'Answer', 'hiring_manager', 'Solve', 'none', "
            ":hash, now()) RETURNING id",
            {"owner": owner, "activity": activity, "hash": b"a" * 32},
        ).scalar_one()

        config_seed = execute(
            "INSERT INTO config_seed_versions "
            "(owner_id, version_key, schema_version, content_hash) "
            "VALUES (:owner, 'seed-v1', 1, :hash) RETURNING id",
            {"owner": owner, "hash": b"s" * 32},
        ).scalar_one()
        competency_ids: dict[str, int] = {}
        for slug, name, baseline, month_target, final_target in COMPETENCIES:
            competency_ids[slug] = execute(
                "INSERT INTO competencies "
                "(owner_id, config_seed_version_id, slug, name, baseline_level, "
                "month_one_target, final_target) VALUES "
                "(:owner, :config, :slug, :name, :baseline, :month_target, :final_target) "
                "RETURNING id",
                {
                    "owner": owner,
                    "config": config_seed,
                    "slug": slug,
                    "name": name,
                    "baseline": baseline,
                    "month_target": month_target,
                    "final_target": final_target,
                },
            ).scalar_one()
        assert len(competency_ids) == 14

        exercise = execute(
            "INSERT INTO exercise_type_versions "
            "(owner_id, config_seed_version_id, exercise_type, mapping_version, evidence_mode, "
            "condition_code, tags) VALUES "
            "(:owner, :config, 'troubleshooting_case', 'seed-v1', 'independent_practice', "
            "'always', '[\"observability\"]'::jsonb) RETURNING id",
            {"owner": owner, "config": config_seed},
        ).scalar_one()
        for slug, impact in (("structured_troubleshooting", "1"), ("tam_english", "0.4")):
            execute(
                "INSERT INTO exercise_skill_mappings "
                "(owner_id, config_seed_version_id, exercise_type_version_id, competency_id, "
                "impact, condition_code) VALUES "
                "(:owner, :config, :exercise, :competency, :impact, 'always')",
                {
                    "owner": owner,
                    "config": config_seed,
                    "exercise": exercise,
                    "competency": competency_ids[slug],
                    "impact": impact,
                },
            )

        rubric = execute(
            "INSERT INTO rubric_versions "
            "(owner_id, config_seed_version_id, rubric_key, version_key, name, scope_code, "
            "scale_min, scale_max) VALUES "
            "(:owner, :config, 'tam-case', 'v1', 'TAM case', 'tam', 0, 4) RETURNING id",
            {"owner": owner, "config": config_seed},
        ).scalar_one()
        dimensions = []
        for key, name, weight in (
            ("diagnosis", "Diagnosis", "0.6"),
            ("communication", "Communication", "0.4"),
        ):
            dimensions.append(
                execute(
                    "INSERT INTO rubric_dimensions "
                    "(owner_id, config_seed_version_id, rubric_version_id, dimension_key, name, "
                    "weight, max_score, ordinal, availability_rule_code) VALUES "
                    "(:owner, :config, :rubric, :key, :name, :weight, 4, :ordinal, 'always') "
                    "RETURNING id",
                    {
                        "owner": owner,
                        "config": config_seed,
                        "rubric": rubric,
                        "key": key,
                        "name": name,
                        "weight": weight,
                        "ordinal": len(dimensions),
                    },
                ).scalar_one()
            )
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
                "activity": activity,
                "attempt": attempt,
                "rubric": rubric,
            },
        ).scalar_one()
        rejects(
            "INSERT INTO rubric_dimension_scores "
            "(owner_id, config_seed_version_id, rubric_evaluation_id, rubric_version_id, "
            "rubric_dimension_id, availability, score, weight_used, evidence_manifest) "
            "VALUES (:owner, :config, :evaluation, :rubric, :dimension, 'scored', "
            "5, 0.6, jsonb_build_object('schema_version', 1, "
            "'artifact_ids', '[]'::jsonb))",
            {
                "owner": owner,
                "config": config_seed,
                "evaluation": evaluation,
                "rubric": rubric,
                "dimension": dimensions[0],
            },
        )
        dimension_scores = []
        for dimension, score, weight in zip(dimensions, ("3", "2"), ("0.6", "0.4"), strict=True):
            dimension_scores.append(
                execute(
                    "INSERT INTO rubric_dimension_scores "
                    "(owner_id, config_seed_version_id, rubric_evaluation_id, rubric_version_id, "
                    "rubric_dimension_id, availability, score, weight_used, evidence_manifest) "
                    "VALUES (:owner, :config, :evaluation, :rubric, :dimension, 'scored', "
                    ":score, :weight, jsonb_build_object('schema_version', 1, "
                    "'artifact_ids', '[]'::jsonb, 'observation_ids', '[]'::jsonb)) RETURNING id",
                    {
                        "owner": owner,
                        "config": config_seed,
                        "evaluation": evaluation,
                        "rubric": rubric,
                        "dimension": dimension,
                        "score": score,
                        "weight": weight,
                    },
                ).scalar_one()
            )

        raw_scores = (
            "jsonb_build_object('schema_version', 1, 'scores', jsonb_build_array("
            "jsonb_build_object('dimension_score_id', :score_1, 'score', 3, 'weight', 0.6), "
            "jsonb_build_object('dimension_score_id', :score_2, 'score', 2, 'weight', 0.4)))"
        )
        explanation = (
            "jsonb_build_object('schema_version', 1, "
            "'summary_code', 'independent_scored_evidence', "
            "'dimension_score_ids', jsonb_build_array(:score_1, :score_2), "
            "'discount_codes', '[]'::jsonb)"
        )
        events = []
        for slug, impact, weight in (
            ("structured_troubleshooting", "1", "0.4875"),
            ("tam_english", "0.4", "0.195"),
        ):
            events.append(
                execute(
                    "INSERT INTO skill_evidence_events "
                    "(owner_id, config_seed_version_id, activity_instance_id, attempt_id, "
                    "rubric_evaluation_id, rubric_version_id, exercise_type_version_id, "
                    "competency_id, formula_version, practice_mode, assistance_code, "
                    "evaluator_kind, difficulty_code, raw_dimension_scores, "
                    "raw_score_numerator, raw_score_denominator, performance_score, "
                    "exercise_skill_impact, practice_mode_factor, ai_independence_factor, "
                    "evaluator_confidence_factor, difficulty_factor, effective_weight, "
                    "qualifying_for_level, qualification_reason_code, explanation, occurred_at) "
                    f"VALUES (:owner, :config, :activity, :attempt, :evaluation, :rubric, "
                    f":exercise, :competency, 'skill-v1', 'independent_practice', 'no_ai', "
                    f"'ai_rubric_reviewer', 'standard', {raw_scores}, 2.6, 1, 2.6, :impact, "
                    f"0.65, 1, 0.75, 1, :effective_weight, true, 'qualifies', {explanation}, "
                    "now()) RETURNING id",
                    {
                        "owner": owner,
                        "config": config_seed,
                        "activity": activity,
                        "attempt": attempt,
                        "evaluation": evaluation,
                        "rubric": rubric,
                        "exercise": exercise,
                        "competency": competency_ids[slug],
                        "score_1": dimension_scores[0],
                        "score_2": dimension_scores[1],
                        "impact": impact,
                        "effective_weight": weight,
                    },
                ).scalar_one()
            )
        assert len(events) == 2

        mismatched_exercise = execute(
            "INSERT INTO exercise_type_versions "
            "(owner_id, config_seed_version_id, exercise_type, mapping_version, evidence_mode, "
            "condition_code, tags) VALUES "
            "(:owner, :config, 'sql_production_lab', 'seed-v1', 'independent_practice', "
            "'always', '[\"data_quality\"]'::jsonb) RETURNING id",
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
                "exercise": mismatched_exercise,
                "competency": competency_ids["structured_troubleshooting"],
            },
        )
        rejects(
            "INSERT INTO skill_evidence_events "
            "(owner_id, config_seed_version_id, activity_instance_id, attempt_id, "
            "rubric_evaluation_id, rubric_version_id, exercise_type_version_id, "
            "competency_id, formula_version, practice_mode, assistance_code, evaluator_kind, "
            "difficulty_code, raw_dimension_scores, raw_score_numerator, raw_score_denominator, "
            "performance_score, exercise_skill_impact, practice_mode_factor, "
            "ai_independence_factor, evaluator_confidence_factor, difficulty_factor, "
            "effective_weight, qualifying_for_level, qualification_reason_code, explanation, "
            f"occurred_at) VALUES (:owner, :config, :activity, :attempt, :evaluation, :rubric, "
            f":exercise, :competency, 'skill-lineage-v1', 'independent_practice', 'no_ai', "
            f"'ai_rubric_reviewer', 'standard', {raw_scores}, 2.6, 1, 2.6, 1, 0.65, 1, "
            f"0.75, 1, 0.4875, true, 'qualifies', {explanation}, now())",
            {
                "owner": owner,
                "config": config_seed,
                "activity": activity,
                "attempt": attempt,
                "evaluation": evaluation,
                "rubric": rubric,
                "exercise": mismatched_exercise,
                "competency": competency_ids["structured_troubleshooting"],
                "score_1": dimension_scores[0],
                "score_2": dimension_scores[1],
            },
        )
        rejects(
            "INSERT INTO skill_evidence_events "
            "(owner_id, config_seed_version_id, activity_instance_id, attempt_id, "
            "rubric_evaluation_id, rubric_version_id, exercise_type_version_id, "
            "competency_id, formula_version, practice_mode, assistance_code, evaluator_kind, "
            "difficulty_code, raw_dimension_scores, raw_score_numerator, raw_score_denominator, "
            "performance_score, exercise_skill_impact, practice_mode_factor, "
            "ai_independence_factor, evaluator_confidence_factor, difficulty_factor, "
            "effective_weight, qualifying_for_level, qualification_reason_code, explanation, "
            f"occurred_at) VALUES (:owner, :config, :activity, :attempt, :evaluation, :rubric, "
            f":exercise, :competency, 'skill-reason-v1', 'independent_practice', 'no_ai', "
            f"'ai_rubric_reviewer', 'standard', {raw_scores}, 2.6, 1, 2.6, 1, 0.65, 1, "
            f"0.75, 1, 0.4875, false, 'attempt_b', {explanation}, now())",
            {
                "owner": owner,
                "config": config_seed,
                "activity": activity,
                "attempt": attempt,
                "evaluation": evaluation,
                "rubric": rubric,
                "exercise": exercise,
                "competency": competency_ids["structured_troubleshooting"],
                "score_1": dimension_scores[0],
                "score_2": dimension_scores[1],
            },
        )

        execute(
            "INSERT INTO skill_snapshots "
            "(owner_id, config_seed_version_id, competency_id, formula_version, snapshot_date, "
            "snapshot_sequence, estimated_level, confidence_code, trend_code, recency_code, "
            "baseline_target_gap, month_one_target_gap, final_target_gap, "
            "total_effective_weight, qualifying_event_count, exercise_type_count, "
            "last_strong_evidence_date, contributing_event_manifest, confidence_basis, "
            "trend_basis) VALUES (:owner, :config, :competency, 'skill-v1', "
            "DATE '2026-08-26', 1, 2.118, 'low', 'insufficient_evidence', 'fresh', "
            "-0.118, 0.382, 0.882, 0.4875, 1, 1, DATE '2026-08-26', "
            "jsonb_build_object('schema_version', 1, 'events', jsonb_build_array("
            "jsonb_build_object('event_id', :event, 'effective_weight', 0.4875, "
            "'inclusion_code', 'included'))), "
            "jsonb_build_object('schema_version', 1, 'basis_code', 'low_weight'), "
            "jsonb_build_object('schema_version', 1, 'basis_code', 'too_few_events', "
            "'event_ids', jsonb_build_array(:event)))",
            {
                "owner": owner,
                "config": config_seed,
                "competency": competency_ids["structured_troubleshooting"],
                "event": events[0],
            },
        )
        rejects(
            "INSERT INTO skill_snapshots "
            "(owner_id, config_seed_version_id, competency_id, formula_version, snapshot_date, "
            "snapshot_sequence, estimated_level, confidence_code, trend_code, recency_code, "
            "baseline_target_gap, month_one_target_gap, final_target_gap, "
            "total_effective_weight, qualifying_event_count, exercise_type_count, "
            "last_strong_evidence_date, contributing_event_manifest, confidence_basis, "
            "trend_basis) VALUES (:owner, :config, :competency, 'skill-v1', "
            "DATE '2026-08-26', 2, 2.118, 'low', 'insufficient_evidence', 'fresh', "
            "-0.118, 0.382, 0.882, 0.4875, 1, 1, DATE '2026-08-26', "
            "jsonb_build_object('schema_version', 1, 'events', jsonb_build_array("
            "jsonb_build_object('event_id', :event, 'effective_weight', 0.4875, "
            "'inclusion_code', 'included'))), "
            "jsonb_build_object('schema_version', 1, 'basis_code', 'low_weight', "
            "'event_ids', jsonb_build_array(:foreign_event)), "
            "jsonb_build_object('schema_version', 1, 'basis_code', 'too_few_events', "
            "'event_ids', jsonb_build_array(:event)))",
            {
                "owner": owner,
                "config": config_seed,
                "competency": competency_ids["structured_troubleshooting"],
                "event": events[0],
                "foreign_event": events[1],
            },
        )

        portfolio_rubric = execute(
            "INSERT INTO rubric_versions "
            "(owner_id, config_seed_version_id, rubric_key, version_key, name, scope_code, "
            "scale_min, scale_max) VALUES "
            "(:owner, :config, 'portfolio-judgment', 'v1', 'Portfolio judgment', "
            "'portfolio', 0, 20) RETURNING id",
            {"owner": owner, "config": config_seed},
        ).scalar_one()
        portfolio_evaluation = execute(
            "INSERT INTO rubric_evaluations "
            "(owner_id, config_seed_version_id, activity_instance_id, attempt_id, "
            "rubric_version_id, evaluator_kind, evaluation_schema_version, input_manifest, "
            "evaluated_at) VALUES (:owner, :config, :activity, :attempt, :rubric, "
            "'ai_rubric_reviewer', 1, jsonb_build_object('schema_version', 1, "
            "'artifact_ids', '[]'::jsonb), now()) RETURNING id",
            {
                "owner": owner,
                "config": config_seed,
                "activity": activity,
                "attempt": attempt,
                "rubric": portfolio_rubric,
            },
        ).scalar_one()
        portfolio = execute(
            "INSERT INTO portfolio_judgment_scores "
            "(owner_id, config_seed_version_id, activity_instance_id, attempt_id, "
            "rubric_evaluation_id, rubric_version_id, formula_version, "
            "impact_risk_assessment, explicit_prioritization, delegation_ownership, "
            "communication_control, proactive_work_protection, evidence_based_reprioritization, "
            "english_clarity, total_score, trend_basis, scored_at) VALUES "
            "(:owner, :config, :activity, :attempt, :evaluation, :rubric, 'portfolio-v1', "
            "3, 2, 2, 2, 1, 2, 1, 13, "
            "jsonb_build_object('schema_version', 1, 'basis_code', 'first_score', "
            "'event_ids', '[]'::jsonb), now()) RETURNING id",
            {
                "owner": owner,
                "config": config_seed,
                "activity": activity,
                "attempt": attempt,
                "evaluation": portfolio_evaluation,
                "rubric": portfolio_rubric,
            },
        ).scalar_one()

        portfolio_evaluation_history = execute(
            "INSERT INTO rubric_evaluations "
            "(owner_id, config_seed_version_id, activity_instance_id, attempt_id, "
            "rubric_version_id, evaluator_kind, evaluation_schema_version, input_manifest, "
            "evaluated_at) VALUES (:owner, :config, :activity, :attempt, :rubric, "
            "'human_coach', 1, jsonb_build_object('schema_version', 1, "
            "'artifact_ids', '[]'::jsonb), now()) RETURNING id",
            {
                "owner": owner,
                "config": config_seed,
                "activity": activity,
                "attempt": attempt,
                "rubric": portfolio_rubric,
            },
        ).scalar_one()
        execute(
            "INSERT INTO portfolio_judgment_scores "
            "(owner_id, config_seed_version_id, activity_instance_id, attempt_id, "
            "rubric_evaluation_id, rubric_version_id, formula_version, "
            "impact_risk_assessment, explicit_prioritization, delegation_ownership, "
            "communication_control, proactive_work_protection, evidence_based_reprioritization, "
            "english_clarity, total_score, trend_basis, scored_at) VALUES "
            "(:owner, :config, :activity, :attempt, :evaluation, :rubric, 'portfolio-v1', "
            "3, 2, 2, 2, 1, 2, 1, 13, "
            "jsonb_build_object('schema_version', 1, 'basis_code', 'stable', "
            "'event_ids', jsonb_build_array(:prior)), now())",
            {
                "owner": owner,
                "config": config_seed,
                "activity": activity,
                "attempt": attempt,
                "evaluation": portfolio_evaluation_history,
                "rubric": portfolio_rubric,
                "prior": portfolio,
            },
        )
        rejects(
            "INSERT INTO portfolio_judgment_scores "
            "(owner_id, config_seed_version_id, activity_instance_id, attempt_id, "
            "rubric_evaluation_id, rubric_version_id, formula_version, "
            "impact_risk_assessment, explicit_prioritization, delegation_ownership, "
            "communication_control, proactive_work_protection, evidence_based_reprioritization, "
            "english_clarity, total_score, trend_basis, scored_at) VALUES "
            "(:owner, :config, :activity, :attempt, :evaluation, :rubric, 'portfolio-v2', "
            "3, 2, 2, 2, 1, 2, 1, 13, "
            "jsonb_build_object('schema_version', 1, 'basis_code', 'stable', "
            "'event_ids', jsonb_build_array(:prior)), now())",
            {
                "owner": owner,
                "config": config_seed,
                "activity": activity,
                "attempt": attempt,
                "evaluation": portfolio_evaluation_history,
                "rubric": portfolio_rubric,
                "prior": portfolio,
            },
        )

        foreign_owner = execute(
            "INSERT INTO owners (github_user_id, github_login) "
            "VALUES (102269370, 'foreign-owner') RETURNING id"
        ).scalar_one()
        foreign_source = execute(
            "INSERT INTO roadmap_sources (owner_id, source_key, name, source_kind) "
            "VALUES (:owner, 'main', 'Foreign roadmap', 'obsidian') RETURNING id",
            {"owner": foreign_owner},
        ).scalar_one()
        foreign_version = execute(
            "INSERT INTO roadmap_versions "
            "(owner_id, source_id, version_key, version_number, month_number, content_hash, "
            "object_key, manifest, raw_payload, normalized_payload, mirror_status, state) "
            "VALUES (:owner, :source, 'month-1-v1', 1, 1, :hash, "
            "'owners/foreign/roadmaps/month-1.json', '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, "
            "'not_required', 'draft') RETURNING id",
            {"owner": foreign_owner, "source": foreign_source, "hash": b"f" * 32},
        ).scalar_one()
        foreign_node = execute(
            "INSERT INTO curriculum_nodes "
            "(owner_id, roadmap_version_id, stable_id, ordinal, kind, title) "
            "VALUES (:owner, :version, 'week-1', 0, 'week', 'Week 1') RETURNING id",
            {"owner": foreign_owner, "version": foreign_version},
        ).scalar_one()
        foreign_task = execute(
            "INSERT INTO task_definitions "
            "(owner_id, roadmap_version_id, curriculum_node_id, stable_id, exercise_type, "
            "mapping_version, objective, timebox_minutes, block, required, output_contract, "
            "pass_contract, evidence_contract, source_references, allowed_ai_role) VALUES "
            "(:owner, :version, :node, 'portfolio-1', 'portfolio_case', 'seed-v1', "
            "'Prioritize accounts', 60, 'tam_case', true, '{}'::jsonb, '{}'::jsonb, "
            "'{}'::jsonb, '[]'::jsonb, 'interviewer') RETURNING id",
            {"owner": foreign_owner, "version": foreign_version, "node": foreign_node},
        ).scalar_one()
        foreign_day = execute(
            "INSERT INTO study_days "
            "(owner_id, roadmap_version_id, local_date, planned_minutes, focused_minutes, "
            "day_type, status) VALUES (:owner, :version, DATE '2026-08-25', 240, 0, "
            "'weekday', 'planned') RETURNING id",
            {"owner": foreign_owner, "version": foreign_version},
        ).scalar_one()
        execute(
            "UPDATE study_days SET status = 'in_progress', started_at = now(), "
            "focused_minutes = 60 WHERE owner_id = :owner AND id = :day",
            {"owner": foreign_owner, "day": foreign_day},
        )
        foreign_activity = execute(
            "INSERT INTO activity_instances "
            "(owner_id, study_day_id, roadmap_version_id, task_definition_id, "
            "task_stable_id_snapshot, task_mapping_version_snapshot, task_objective_snapshot, "
            "task_timebox_minutes_snapshot, roadmap_version_key_snapshot, state, attempt_kind, "
            "assistance_mode, classification, timebox_minutes, source_hidden, optimistic_version, "
            "replacement_version) VALUES (:owner, :day, :version, :task, 'portfolio-1', "
            "'seed-v1', 'Prioritize accounts', 60, 'month-1-v1', 'ready', 'attempt_a', "
            "'none', 'required', 60, false, 1, 1) RETURNING id",
            {
                "owner": foreign_owner,
                "day": foreign_day,
                "version": foreign_version,
                "task": foreign_task,
            },
        ).scalar_one()
        foreign_attempt = execute(
            "INSERT INTO attempts "
            "(owner_id, activity_instance_id, attempt_kind, original_text, audience, prompt, "
            "assistance_mode, commitment_hash, committed_at) VALUES "
            "(:owner, :activity, 'attempt_a', 'Answer', 'hiring_manager', 'Prioritize', "
            "'none', :hash, now()) RETURNING id",
            {"owner": foreign_owner, "activity": foreign_activity, "hash": b"q" * 32},
        ).scalar_one()
        foreign_config = execute(
            "INSERT INTO config_seed_versions "
            "(owner_id, version_key, schema_version, content_hash) "
            "VALUES (:owner, 'seed-v1', 1, :hash) RETURNING id",
            {"owner": foreign_owner, "hash": b"c" * 32},
        ).scalar_one()
        foreign_rubric = execute(
            "INSERT INTO rubric_versions "
            "(owner_id, config_seed_version_id, rubric_key, version_key, name, scope_code, "
            "scale_min, scale_max) VALUES "
            "(:owner, :config, 'portfolio-judgment', 'v1', 'Portfolio judgment', "
            "'portfolio', 0, 20) RETURNING id",
            {"owner": foreign_owner, "config": foreign_config},
        ).scalar_one()
        foreign_evaluation = execute(
            "INSERT INTO rubric_evaluations "
            "(owner_id, config_seed_version_id, activity_instance_id, attempt_id, "
            "rubric_version_id, evaluator_kind, evaluation_schema_version, input_manifest, "
            "evaluated_at) VALUES (:owner, :config, :activity, :attempt, :rubric, "
            "'ai_rubric_reviewer', 1, jsonb_build_object('schema_version', 1, "
            "'artifact_ids', '[]'::jsonb), now()) RETURNING id",
            {
                "owner": foreign_owner,
                "config": foreign_config,
                "activity": foreign_activity,
                "attempt": foreign_attempt,
                "rubric": foreign_rubric,
            },
        ).scalar_one()
        foreign_portfolio = execute(
            "INSERT INTO portfolio_judgment_scores "
            "(owner_id, config_seed_version_id, activity_instance_id, attempt_id, "
            "rubric_evaluation_id, rubric_version_id, formula_version, "
            "impact_risk_assessment, explicit_prioritization, delegation_ownership, "
            "communication_control, proactive_work_protection, evidence_based_reprioritization, "
            "english_clarity, total_score, trend_basis, scored_at) VALUES "
            "(:owner, :config, :activity, :attempt, :evaluation, :rubric, 'portfolio-v1', "
            "3, 2, 2, 2, 1, 2, 1, 13, "
            "jsonb_build_object('schema_version', 1, 'basis_code', 'first_score', "
            "'event_ids', '[]'::jsonb), now()) RETURNING id",
            {
                "owner": foreign_owner,
                "config": foreign_config,
                "activity": foreign_activity,
                "attempt": foreign_attempt,
                "evaluation": foreign_evaluation,
                "rubric": foreign_rubric,
            },
        ).scalar_one()
        wrong_owner_evaluation = execute(
            "INSERT INTO rubric_evaluations "
            "(owner_id, config_seed_version_id, activity_instance_id, attempt_id, "
            "rubric_version_id, evaluator_kind, evaluation_schema_version, input_manifest, "
            "evaluated_at) VALUES (:owner, :config, :activity, :attempt, :rubric, "
            "'peer', 1, jsonb_build_object('schema_version', 1, "
            "'artifact_ids', '[]'::jsonb), now()) RETURNING id",
            {
                "owner": owner,
                "config": config_seed,
                "activity": activity,
                "attempt": attempt,
                "rubric": portfolio_rubric,
            },
        ).scalar_one()
        rejects(
            "INSERT INTO portfolio_judgment_scores "
            "(owner_id, config_seed_version_id, activity_instance_id, attempt_id, "
            "rubric_evaluation_id, rubric_version_id, formula_version, "
            "impact_risk_assessment, explicit_prioritization, delegation_ownership, "
            "communication_control, proactive_work_protection, evidence_based_reprioritization, "
            "english_clarity, total_score, trend_basis, scored_at) VALUES "
            "(:owner, :config, :activity, :attempt, :evaluation, :rubric, 'portfolio-v1', "
            "3, 2, 2, 2, 1, 2, 1, 13, "
            "jsonb_build_object('schema_version', 1, 'basis_code', 'stable', "
            "'event_ids', jsonb_build_array(:prior)), now())",
            {
                "owner": owner,
                "config": config_seed,
                "activity": activity,
                "attempt": attempt,
                "evaluation": wrong_owner_evaluation,
                "rubric": portfolio_rubric,
                "prior": foreign_portfolio,
            },
        )
        rejects(
            "INSERT INTO portfolio_judgment_scores "
            "(owner_id, config_seed_version_id, activity_instance_id, attempt_id, "
            "rubric_evaluation_id, rubric_version_id, formula_version, "
            "impact_risk_assessment, explicit_prioritization, delegation_ownership, "
            "communication_control, proactive_work_protection, evidence_based_reprioritization, "
            "english_clarity, total_score, trend_basis, scored_at) VALUES "
            "(:owner, :config, :activity, :attempt, :evaluation, :rubric, 'portfolio-v3', "
            "3, 2, 2, 2, 1, 2, 1, 13, "
            "jsonb_build_object('schema_version', 1, 'basis_code', 'stable', "
            "'event_ids', jsonb_build_array(9223372036854775807)), now())",
            {
                "owner": owner,
                "config": config_seed,
                "activity": activity,
                "attempt": attempt,
                "evaluation": portfolio_evaluation_history,
                "rubric": portfolio_rubric,
            },
        )

        alternate_config = execute(
            "INSERT INTO config_seed_versions "
            "(owner_id, version_key, schema_version, content_hash) "
            "VALUES (:owner, 'seed-v2', 1, :hash) RETURNING id",
            {"owner": owner, "hash": b"t" * 32},
        ).scalar_one()
        alternate_portfolio_rubric = execute(
            "INSERT INTO rubric_versions "
            "(owner_id, config_seed_version_id, rubric_key, version_key, name, scope_code, "
            "scale_min, scale_max) VALUES "
            "(:owner, :config, 'portfolio-judgment', 'v2', 'Portfolio judgment v2', "
            "'portfolio', 0, 20) RETURNING id",
            {"owner": owner, "config": alternate_config},
        ).scalar_one()
        alternate_config_evaluation = execute(
            "INSERT INTO rubric_evaluations "
            "(owner_id, config_seed_version_id, activity_instance_id, attempt_id, "
            "rubric_version_id, evaluator_kind, evaluation_schema_version, input_manifest, "
            "evaluated_at) VALUES (:owner, :config, :activity, :attempt, :rubric, "
            "'ai_rubric_reviewer', 1, jsonb_build_object('schema_version', 1, "
            "'artifact_ids', '[]'::jsonb), now()) RETURNING id",
            {
                "owner": owner,
                "config": alternate_config,
                "activity": activity,
                "attempt": attempt,
                "rubric": alternate_portfolio_rubric,
            },
        ).scalar_one()
        rejects(
            "INSERT INTO portfolio_judgment_scores "
            "(owner_id, config_seed_version_id, activity_instance_id, attempt_id, "
            "rubric_evaluation_id, rubric_version_id, formula_version, "
            "impact_risk_assessment, explicit_prioritization, delegation_ownership, "
            "communication_control, proactive_work_protection, evidence_based_reprioritization, "
            "english_clarity, total_score, trend_basis, scored_at) VALUES "
            "(:owner, :config, :activity, :attempt, :evaluation, :rubric, 'portfolio-v1', "
            "3, 2, 2, 2, 1, 2, 1, 13, "
            "jsonb_build_object('schema_version', 1, 'basis_code', 'stable', "
            "'event_ids', jsonb_build_array(:prior)), now())",
            {
                "owner": owner,
                "config": alternate_config,
                "activity": activity,
                "attempt": attempt,
                "evaluation": alternate_config_evaluation,
                "rubric": alternate_portfolio_rubric,
                "prior": portfolio,
            },
        )
        rejects(
            "INSERT INTO portfolio_judgment_scores "
            "(owner_id, config_seed_version_id, activity_instance_id, attempt_id, "
            "rubric_evaluation_id, rubric_version_id, formula_version, "
            "impact_risk_assessment, explicit_prioritization, delegation_ownership, "
            "communication_control, proactive_work_protection, evidence_based_reprioritization, "
            "english_clarity, total_score, trend_basis, scored_at) VALUES "
            "(:owner, :config, :activity, :attempt, :evaluation, :rubric, 'portfolio-v2', "
            "4, 3, 3, 3, 2, 3, 2, 21, "
            "jsonb_build_object('schema_version', 1, 'basis_code', 'first_score', "
            "'event_ids', '[]'::jsonb), now())",
            {
                "owner": owner,
                "config": config_seed,
                "activity": activity,
                "attempt": attempt,
                "evaluation": portfolio_evaluation,
                "rubric": portfolio_rubric,
            },
        )

        rejects(
            "UPDATE competencies SET slug = 'rewritten' WHERE id = :id",
            {"id": competency_ids["tam_english"]},
        )
        rejects(
            "UPDATE skill_evidence_events SET performance_score = 4 WHERE id = :id",
            {"id": events[0]},
        )
        rejects(
            "DELETE FROM skill_snapshots WHERE competency_id = :id",
            {"id": competency_ids["structured_troubleshooting"]},
        )
        rejects(
            "UPDATE portfolio_judgment_scores SET total_score = 14 WHERE id = :id",
            {"id": portfolio},
        )

        command.downgrade(config, "20260825_0003_study_activities")
        assert not (REVISION_TABLES & set(inspect(engine).get_table_names()))
    finally:
        engine.dispose()

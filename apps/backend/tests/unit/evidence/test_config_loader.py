from __future__ import annotations

import shutil
from decimal import Decimal
from pathlib import Path

import pytest
import yaml
from tamforge_backend.evidence.config_loader import (
    ConfigError,
    load_config_bundle,
    load_config_payload,
)

CONFIG_DIR = Path(__file__).parents[5] / "config"

EXPECTED_SKILLS = {
    "api_integration_architecture": ("3.0", "3.0", "3.25"),
    "structured_troubleshooting": ("2.0", "2.5", "3.0"),
    "sql_reconciliation": ("1.0", "2.0", "2.75"),
    "distributed_systems_reliability": ("2.0", "2.5", "3.0"),
    "payments_fintech_systems": ("2.0", "2.5", "3.0"),
    "technical_discovery": ("2.0", "2.5", "3.0"),
    "incident_escalation_management": ("2.0", "2.5", "3.0"),
    "implementation_project_management": ("2.0", "2.5", "2.75"),
    "proactive_account_strategy": ("2.0", "2.5", "2.75"),
    "executive_communication": ("1.0", "2.0", "3.0"),
    "cross_functional_influence": ("2.0", "2.5", "2.75"),
    "business_value_framing": ("1.0", "2.0", "3.0"),
    "technical_writing": ("1.0", "2.0", "2.75"),
    "tam_english": ("1.0", "2.0", "2.75"),
}

EXPECTED_EXERCISES = {
    "official_reading",
    "sql_guided_lesson",
    "sql_production_lab",
    "sql_no_ai_timed_assessment",
    "integration_diagram_and_explanation",
    "architecture_design_case",
    "api_failure_mode_analysis",
    "webhook_reliability_design",
    "troubleshooting_case",
    "oauth_security_troubleshooting",
    "technical_discovery_roleplay",
    "payment_lifecycle_case",
    "payment_reconciliation_case",
    "incident_simulation",
    "customer_incident_update",
    "internal_engineering_escalation",
    "postmortem_rca",
    "observability_health_dashboard",
    "implementation_plan",
    "project_kickoff_followup",
    "launch_readiness_decision",
    "account_plan_90_day",
    "technical_health_review_qbr",
    "audience_switching_explanation",
    "architecture_presentation",
    "customer_pushback_or_bad_news",
    "cross_functional_conflict_case",
    "behavioral_story_practice",
    "tell_me_about_yourself",
    "portfolio_triage",
    "technical_writing_timed",
    "full_tam_gauntlet",
    "company_product_research",
    "application_or_outreach",
    "correction_warmup",
}
EXPECTED_IMPACTS = {
    "official_reading": {},
    "sql_guided_lesson": {"sql_reconciliation": "0.35"},
    "sql_production_lab": {
        "sql_reconciliation": "1.00",
        "structured_troubleshooting": "0.25",
        "business_value_framing": "0.10",
    },
    "sql_no_ai_timed_assessment": {"sql_reconciliation": "1.00", "tam_english": "0.15"},
    "integration_diagram_and_explanation": {
        "api_integration_architecture": "1.00",
        "distributed_systems_reliability": "0.50",
        "technical_discovery": "0.40",
        "business_value_framing": "0.40",
        "tam_english": "0.40",
    },
    "architecture_design_case": {
        "api_integration_architecture": "1.00",
        "distributed_systems_reliability": "0.80",
        "technical_discovery": "0.60",
        "business_value_framing": "0.40",
        "implementation_project_management": "0.30",
        "executive_communication": "0.30",
        "tam_english": "0.40",
    },
    "api_failure_mode_analysis": {
        "distributed_systems_reliability": "1.00",
        "api_integration_architecture": "0.80",
        "structured_troubleshooting": "0.60",
        "technical_writing": "0.20",
        "sql_reconciliation": "0.20",
    },
    "webhook_reliability_design": {
        "api_integration_architecture": "1.00",
        "distributed_systems_reliability": "1.00",
        "structured_troubleshooting": "0.40",
        "incident_escalation_management": "0.30",
        "sql_reconciliation": "0.20",
    },
    "troubleshooting_case": {
        "structured_troubleshooting": "1.00",
        "distributed_systems_reliability": "0.50",
        "api_integration_architecture": "0.50",
        "incident_escalation_management": "0.40",
        "business_value_framing": "0.30",
        "tam_english": "0.40",
    },
    "oauth_security_troubleshooting": {
        "structured_troubleshooting": "1.00",
        "api_integration_architecture": "0.80",
        "distributed_systems_reliability": "0.30",
        "incident_escalation_management": "0.30",
        "executive_communication": "0.30",
        "tam_english": "0.30",
    },
    "technical_discovery_roleplay": {
        "technical_discovery": "1.00",
        "business_value_framing": "0.70",
        "api_integration_architecture": "0.50",
        "executive_communication": "0.40",
        "tam_english": "0.70",
    },
    "payment_lifecycle_case": {
        "payments_fintech_systems": "1.00",
        "distributed_systems_reliability": "0.50",
        "business_value_framing": "0.50",
        "sql_reconciliation": "0.30",
        "tam_english": "0.40",
    },
    "payment_reconciliation_case": {
        "payments_fintech_systems": "1.00",
        "sql_reconciliation": "1.00",
        "structured_troubleshooting": "0.50",
        "business_value_framing": "0.60",
        "technical_writing": "0.30",
    },
    "incident_simulation": {
        "incident_escalation_management": "1.00",
        "structured_troubleshooting": "0.80",
        "executive_communication": "0.70",
        "cross_functional_influence": "0.60",
        "business_value_framing": "0.60",
        "tam_english": "0.70",
    },
    "customer_incident_update": {
        "technical_writing": "1.00",
        "incident_escalation_management": "0.80",
        "executive_communication": "0.60",
        "business_value_framing": "0.50",
        "tam_english": "0.60",
    },
    "internal_engineering_escalation": {
        "technical_writing": "1.00",
        "incident_escalation_management": "0.80",
        "cross_functional_influence": "0.80",
        "business_value_framing": "0.50",
        "structured_troubleshooting": "0.40",
    },
    "postmortem_rca": {
        "incident_escalation_management": "1.00",
        "technical_writing": "1.00",
        "structured_troubleshooting": "0.60",
        "distributed_systems_reliability": "0.60",
        "business_value_framing": "0.50",
        "implementation_project_management": "0.30",
    },
    "observability_health_dashboard": {
        "proactive_account_strategy": "0.80",
        "structured_troubleshooting": "0.70",
        "business_value_framing": "0.70",
        "distributed_systems_reliability": "0.60",
        "incident_escalation_management": "0.60",
        "executive_communication": "0.50",
    },
    "implementation_plan": {
        "implementation_project_management": "1.00",
        "technical_writing": "0.70",
        "technical_discovery": "0.60",
        "cross_functional_influence": "0.50",
        "business_value_framing": "0.40",
        "proactive_account_strategy": "0.30",
    },
    "project_kickoff_followup": {
        "technical_writing": "1.00",
        "implementation_project_management": "0.80",
        "cross_functional_influence": "0.40",
        "technical_discovery": "0.30",
        "tam_english": "0.50",
    },
    "launch_readiness_decision": {
        "implementation_project_management": "1.00",
        "incident_escalation_management": "0.80",
        "cross_functional_influence": "0.80",
        "executive_communication": "0.80",
        "business_value_framing": "0.80",
        "tam_english": "0.60",
        "proactive_account_strategy": "0.40",
    },
    "account_plan_90_day": {
        "proactive_account_strategy": "1.00",
        "business_value_framing": "0.90",
        "technical_writing": "0.70",
        "executive_communication": "0.60",
        "cross_functional_influence": "0.50",
        "implementation_project_management": "0.40",
    },
    "technical_health_review_qbr": {
        "proactive_account_strategy": "1.00",
        "executive_communication": "1.00",
        "business_value_framing": "1.00",
        "tam_english": "0.80",
        "technical_writing": "0.60",
        "incident_escalation_management": "0.30",
    },
    "audience_switching_explanation": {
        "executive_communication": "1.00",
        "tam_english": "0.90",
        "business_value_framing": "0.80",
    },
    "architecture_presentation": {
        "executive_communication": "0.70",
        "tam_english": "0.80",
        "api_integration_architecture": "0.60",
        "business_value_framing": "0.50",
    },
    "customer_pushback_or_bad_news": {
        "cross_functional_influence": "0.80",
        "tam_english": "0.80",
        "executive_communication": "0.70",
        "incident_escalation_management": "0.50",
        "business_value_framing": "0.40",
    },
    "cross_functional_conflict_case": {
        "cross_functional_influence": "1.00",
        "business_value_framing": "0.80",
        "tam_english": "0.70",
        "executive_communication": "0.60",
        "proactive_account_strategy": "0.50",
        "incident_escalation_management": "0.30",
    },
    "behavioral_story_practice": {
        "tam_english": "0.70",
        "executive_communication": "0.40",
        "business_value_framing": "0.30",
    },
    "tell_me_about_yourself": {
        "tam_english": "1.00",
        "executive_communication": "0.50",
        "business_value_framing": "0.50",
    },
    "portfolio_triage": {
        "proactive_account_strategy": "0.90",
        "cross_functional_influence": "0.90",
        "incident_escalation_management": "0.80",
        "business_value_framing": "0.80",
        "executive_communication": "0.60",
        "tam_english": "0.60",
        "structured_troubleshooting": "0.40",
    },
    "technical_writing_timed": {
        "technical_writing": "1.00",
        "executive_communication": "0.50",
        "business_value_framing": "0.50",
        "tam_english": "0.50",
    },
    "full_tam_gauntlet": {},
    "company_product_research": {},
    "application_or_outreach": {},
    "correction_warmup": {},
}


@pytest.fixture(scope="module")
def config_bundle():
    return load_config_bundle(CONFIG_DIR)


def test_normative_skill_contract(config_bundle) -> None:
    assert len(config_bundle.skills) == 14
    assert {
        skill.slug: (
            str(skill.baseline),
            str(skill.month_one_target),
            str(skill.final_target),
        )
        for skill in config_bundle.skills
    } == EXPECTED_SKILLS


def test_complete_normative_exercise_mapping(config_bundle) -> None:
    assert {exercise.slug for exercise in config_bundle.exercise_types} == EXPECTED_EXERCISES
    assert {
        exercise.slug: {
            slug: str(impact.weight) for slug, impact in exercise.skill_impacts.items()
        }
        for exercise in config_bundle.exercise_types
    } == EXPECTED_IMPACTS
    assert config_bundle.exercise("official_reading").skill_impacts == {}
    assert config_bundle.exercise("company_product_research").skill_impacts == {}
    assert config_bundle.exercise("application_or_outreach").skill_impacts == {}
    assert config_bundle.exercise("sql_production_lab").skill_impacts[
        "sql_reconciliation"
    ].weight == Decimal("1.00")


def test_english_and_dynamic_impacts_are_conditional(config_bundle) -> None:
    for exercise in config_bundle.exercise_types:
        english = exercise.skill_impacts.get("tam_english")
        if english is not None:
            assert english.condition in {
                "spoken_or_written_english",
                "explained_aloud_in_english",
            }

    audience = config_bundle.exercise("audience_switching_explanation")
    assert audience.required_precommit_field == "domain_competency_slug"
    assert audience.selected_impact == Decimal("0.30")
    assert audience.allowed_selected_competencies
    behavioral = config_bundle.exercise("behavioral_story_practice")
    assert behavioral.required_precommit_field == "story_competency_slug"
    assert behavioral.selected_impact == Decimal("0.40")


def test_gauntlet_children_are_fully_linked(config_bundle) -> None:
    gauntlet = config_bundle.exercise("full_tam_gauntlet")
    assert gauntlet.component_scoring_required is True
    assert len(gauntlet.child_exercise_type_refs) == 9
    assert all(
        config_bundle.exercise(child.exercise_type).mapping_version == child.mapping_version
        for child in gauntlet.child_exercise_type_refs
    )


def test_portfolio_and_formula_match_approved_contract(config_bundle) -> None:
    assert sum(item.maximum for item in config_bundle.portfolio.dimensions) == Decimal("20")
    assert config_bundle.formula.prior_weight == Decimal("2.0")
    assert config_bundle.formula.latest_qualifying_events == 12
    assert config_bundle.formula.full_weight_same_day_limit == 2
    assert config_bundle.formula.practice_mode_factors.model_dump() == {
        "exposure_only": Decimal("0.00"),
        "guided_practice": Decimal("0.35"),
        "independent_practice": Decimal("0.65"),
        "timed_assessment": Decimal("0.90"),
        "mock_interview": Decimal("1.00"),
        "real_interview": Decimal("1.00"),
    }
    assert config_bundle.formula.assistance_factors.model_dump() == {
        "no_ai": Decimal("1.00"),
        "ai_after_committed_attempt": Decimal("1.00"),
        "ai_hints_during_attempt": Decimal("0.75"),
        "ai_co_created": Decimal("0.40"),
        "ai_generated": Decimal("0.10"),
    }
    assert config_bundle.formula.evaluator_factors.model_dump() == {
        "self": Decimal("0.60"),
        "ai_rubric_reviewer": Decimal("0.75"),
        "peer": Decimal("0.85"),
        "human_coach": Decimal("0.95"),
        "explicit_interviewer_feedback": Decimal("1.00"),
    }
    assert config_bundle.formula.difficulty_factors.model_dump() == {
        "introductory": Decimal("0.80"),
        "standard": Decimal("1.00"),
        "advanced": Decimal("1.15"),
    }
    assert config_bundle.formula.qualifying_modes == {
        "independent_practice",
        "timed_assessment",
        "mock_interview",
        "real_interview",
    }
    assert config_bundle.formula.qualifying_assistance == {
        "no_ai",
        "ai_after_committed_attempt",
    }
    assert config_bundle.formula.independent_practice_requires_attempt_a is True
    assert config_bundle.formula.attempt_b_qualifies is False


def test_month_one_task_map_is_explicit_and_time_bounded(config_bundle) -> None:
    assert len(config_bundle.roadmap_tasks) == 158
    assert len({task.stable_id for task in config_bundle.roadmap_tasks}) == 158
    weekdays = {(task.week, task.day) for task in config_bundle.roadmap_tasks if task.day % 6}
    saturdays = {(task.week, task.day) for task in config_bundle.roadmap_tasks if task.day % 6 == 0}
    assert all(
        sum(
            task.timebox_minutes
            for task in config_bundle.roadmap_tasks
            if (task.week, task.day) == key
        )
        == 240
        for key in weekdays
    )
    assert all(
        sum(
            task.timebox_minutes
            for task in config_bundle.roadmap_tasks
            if (task.week, task.day) == key
        )
        == 120
        for key in saturdays
    )
    assert all(task.exercise_type in EXPECTED_EXERCISES for task in config_bundle.roadmap_tasks)
    assert all(task.mapping_version == "seed-v1" for task in config_bundle.roadmap_tasks)


def test_weekdays_expose_one_dynamic_correction_warmup(config_bundle) -> None:
    for week in range(1, 5):
        for day in range((week - 1) * 6 + 1, week * 6):
            tasks = [
                task
                for task in config_bundle.roadmap_tasks
                if (task.week, task.day) == (week, day)
            ]
            warmups = [task for task in tasks if task.block == "correction_warmup"]
            communication = [
                task for task in tasks if task.block == "communication_spoken"
            ]
            assert len(warmups) == 1
            assert warmups[0].timebox_minutes == 10
            assert warmups[0].correction_selection is not None
            assert warmups[0].correction_selection.source == "due_corrections"
            assert warmups[0].correction_selection.maximum_items == 1
            assert warmups[0].correction_selection.no_attempt_c is True
            assert len(communication) == 1
            assert communication[0].timebox_minutes == 35

    correction = config_bundle.exercise("correction_warmup")
    assert correction.evidence_mode == "guided_practice"
    assert correction.skill_impacts == {}


def test_day_23_correction_conflict_has_reviewed_reconciliation(config_bundle) -> None:
    day_23_close = next(
        task
        for task in config_bundle.roadmap_tasks
        if task.stable_id == "m1-w4-d23-close"
    )
    assert "no more than two" in day_23_close.objective.lower()
    reconciliation = config_bundle.reconciliations[0]
    assert reconciliation.reviewed is True
    assert reconciliation.target_task_id == day_23_close.stable_id
    assert "exactly three" in reconciliation.original_source_text.lower()
    assert reconciliation.executable_text == day_23_close.objective
    assert reconciliation.what_changed
    assert reconciliation.why_changed
    assert reconciliation.evidence
    assert reconciliation.roadmap_objective
    assert reconciliation.affects_time is False
    assert reconciliation.affects_required_coverage is False


def test_normative_composite_and_activity_contracts_are_executable(config_bundle) -> None:
    assert config_bundle.exercise("portfolio_triage").composite_metric_weights == {
        "portfolio_judgment": Decimal("1.00")
    }

    technical = config_bundle.roadmap_contracts["technical"]
    assert [(step.phase, step.minutes) for step in technical.procedure] == [
        ("preview", 2),
        ("focused_reading", 20),
        ("closed_source_recall", 8),
        ("application", 10),
        ("teach_back", 5),
    ]
    assert any("three key ideas" in item.lower() for item in technical.required_output)
    tam_case = config_bundle.roadmap_contracts["case"]
    assert [(step.phase, step.minutes) for step in tam_case.procedure] == [
        ("understand", 5),
        ("discovery", 10),
        ("structure", 5),
        ("solve_produce", 25),
        ("present_defend", 10),
        ("self_review", 5),
    ]
    assert any("canonical prompt" in item.lower() for item in tam_case.evidence_requirements)
    assert all(contract.constraints for contract in config_bundle.roadmap_contracts.values())


def test_hash_is_canonical_and_stable(config_bundle) -> None:
    again = load_config_bundle(CONFIG_DIR)
    assert config_bundle.content_hash == again.content_hash
    assert len(config_bundle.content_hash) == 32
    assert config_bundle.version_key.startswith("seed-v1-")


def test_canonical_payload_round_trips_every_runtime_contract(config_bundle) -> None:
    reconstructed = load_config_payload(config_bundle.canonical_payload)
    assert reconstructed.content_hash == config_bundle.content_hash
    assert reconstructed.canonical_payload == config_bundle.canonical_payload
    assert reconstructed.formula == config_bundle.formula
    assert reconstructed.roadmap_tasks == config_bundle.roadmap_tasks
    assert reconstructed.roadmap_contracts == config_bundle.roadmap_contracts
    assert reconstructed.reconciliations == config_bundle.reconciliations
    assert reconstructed.exercise("portfolio_triage").composite_metric_weights == {
        "portfolio_judgment": Decimal("1")
    }
    assert reconstructed.exercise("full_tam_gauntlet").child_exercise_type_refs


def test_hash_ignores_semantically_unordered_collections_and_decimal_spelling(
    config_bundle, tmp_path: Path
) -> None:
    fixture_dir = tmp_path / "config"
    shutil.copytree(CONFIG_DIR, fixture_dir)

    skills_path = fixture_dir / "tam-skills.yaml"
    skills = yaml.safe_load(skills_path.read_text(encoding="utf-8"))
    skills["skills"].reverse()
    skills_path.write_text(yaml.safe_dump(skills, sort_keys=False), encoding="utf-8")

    exercises_path = fixture_dir / "tam-exercise-types.yaml"
    exercises = yaml.safe_load(exercises_path.read_text(encoding="utf-8"))
    exercises["supporting_tags"].reverse()
    exercises["exercise_types"].reverse()
    for exercise in exercises["exercise_types"]:
        impacts = exercise.get("skill_impacts")
        if impacts:
            exercise["skill_impacts"] = dict(reversed(tuple(impacts.items())))
        for field in (
            "tags",
            "allowed_domain_competencies",
            "allowed_story_competencies",
            "child_exercise_type_refs",
        ):
            if field in exercise:
                exercise[field].reverse()
    exercises_path.write_text(
        yaml.safe_dump(exercises, sort_keys=False), encoding="utf-8"
    )

    roadmap_path = fixture_dir / "tam-roadmap-task-map.yaml"
    roadmap = yaml.safe_load(roadmap_path.read_text(encoding="utf-8"))
    roadmap["days"].reverse()
    for day in roadmap["days"]:
        day["tasks"].reverse()
    roadmap_path.write_text(yaml.safe_dump(roadmap, sort_keys=False), encoding="utf-8")

    equivalent = load_config_bundle(fixture_dir)
    assert equivalent.content_hash == config_bundle.content_hash
    assert equivalent.canonical_payload == config_bundle.canonical_payload


def test_hash_preserves_rubric_dimension_and_explicit_task_semantic_order(
    config_bundle, tmp_path: Path
) -> None:
    fixture_dir = tmp_path / "config"
    shutil.copytree(CONFIG_DIR, fixture_dir)
    rubrics_path = fixture_dir / "tam-rubrics.yaml"
    rubrics = yaml.safe_load(rubrics_path.read_text(encoding="utf-8"))
    rubrics["rubrics"][0]["dimensions"].reverse()
    rubrics_path.write_text(yaml.safe_dump(rubrics, sort_keys=False), encoding="utf-8")
    assert load_config_bundle(fixture_dir).content_hash != config_bundle.content_hash

    shutil.rmtree(fixture_dir)
    shutil.copytree(CONFIG_DIR, fixture_dir)
    roadmap_path = fixture_dir / "tam-roadmap-task-map.yaml"
    roadmap = yaml.safe_load(roadmap_path.read_text(encoding="utf-8"))
    roadmap["days"][0]["tasks"][0]["order"] = 2
    roadmap["days"][0]["tasks"][1]["order"] = 1
    roadmap_path.write_text(yaml.safe_dump(roadmap, sort_keys=False), encoding="utf-8")
    assert load_config_bundle(fixture_dir).content_hash != config_bundle.content_hash


def test_invalid_mapping_reports_source_location() -> None:
    fixture_dir = Path(__file__).parents[2] / "fixtures" / "config"
    with pytest.raises(ConfigError, match=r"invalid-mapping\.yaml:\d+:\d+.*unknown skill"):
        load_config_bundle(CONFIG_DIR, exercise_types_path=fixture_dir / "invalid-mapping.yaml")


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("weight: 0.35", "weight: 1.01", "less than or equal to 1"),
        ("tags: [webhooks, idempotency, retries_backoff]", "tags: [not_allowed]", "unknown tag"),
        ("slug: sql_guided_lesson", "slug: official_reading", "duplicate slug"),
        (
            "exercise_type: portfolio_triage, mapping_version: seed-v1",
            "exercise_type: missing_child, mapping_version: seed-v1",
            "unknown child exercise",
        ),
    ],
)
def test_invalid_exercise_contracts_fail_with_location(
    tmp_path: Path, old: str, new: str, message: str
) -> None:
    fixture_dir = tmp_path / "config"
    shutil.copytree(CONFIG_DIR, fixture_dir)
    mapping = fixture_dir / "tam-exercise-types.yaml"
    original = mapping.read_text(encoding="utf-8")
    assert old in original
    mapping.write_text(original.replace(old, new, 1), encoding="utf-8")
    with pytest.raises(ConfigError, match=rf"tam-exercise-types\.yaml:\d+:\d+.*{message}"):
        load_config_bundle(fixture_dir)


def test_unknown_fields_and_duplicate_yaml_keys_fail_with_location(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "config"
    shutil.copytree(CONFIG_DIR, fixture_dir)
    skills = fixture_dir / "tam-skills.yaml"
    text = skills.read_text(encoding="utf-8")
    skills.write_text(
        text.replace("    name:", "    unknown_field: true\n    name:", 1),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match=r"tam-skills\.yaml:\d+:\d+.*Extra inputs"):
        load_config_bundle(fixture_dir)

    skills.write_text(
        text.replace("schema_version: 1", "schema_version: 1\nschema_version: 1"),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match=r"tam-skills\.yaml:2:1.*duplicate key"):
        load_config_bundle(fixture_dir)


def test_unknown_roadmap_day_group_field_fails_with_location(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "config"
    shutil.copytree(CONFIG_DIR, fixture_dir)
    roadmap = fixture_dir / "tam-roadmap-task-map.yaml"
    text = roadmap.read_text(encoding="utf-8")
    roadmap.write_text(
        text.replace("    day: 1", "    day: 1\n    unexpected: true", 1),
        encoding="utf-8",
    )

    with pytest.raises(
        ConfigError,
        match=r"tam-roadmap-task-map\.yaml:\d+:\d+.*unexpected.*not permitted",
    ):
        load_config_bundle(fixture_dir)


def test_partial_release_version_bump_is_rejected(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "config"
    shutil.copytree(CONFIG_DIR, fixture_dir)
    mapping = fixture_dir / "tam-exercise-types.yaml"
    text = mapping.read_text(encoding="utf-8")
    mapping.write_text(
        text.replace("mapping_version: seed-v1", "mapping_version: seed-v2"),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match=r"versions must match"):
        load_config_bundle(fixture_dir)


def test_explicit_rogue_exercise_mapping_version_is_rejected(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "config"
    shutil.copytree(CONFIG_DIR, fixture_dir)
    mapping = fixture_dir / "tam-exercise-types.yaml"
    text = mapping.read_text(encoding="utf-8")
    mapping.write_text(
        text.replace(
            "  - slug: official_reading\n    evidence_mode:",
            "  - slug: official_reading\n    mapping_version: rogue-v9\n    evidence_mode:",
            1,
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match=r"item mapping version must match release"):
        load_config_bundle(fixture_dir)


@pytest.mark.parametrize(
    ("injection", "message"),
    [
        (
            "    name: &shared API and integration architecture",
            "YAML aliases are not allowed",
        ),
        ("    <<: {unexpected: true}", "YAML merge keys are not allowed"),
    ],
)
def test_yaml_aliases_and_merge_keys_are_rejected(
    tmp_path: Path, injection: str, message: str
) -> None:
    fixture_dir = tmp_path / "config"
    shutil.copytree(CONFIG_DIR, fixture_dir)
    skills = fixture_dir / "tam-skills.yaml"
    text = skills.read_text(encoding="utf-8")
    if "&shared" in injection:
        text = text.replace(
            "    name: API and integration architecture",
            injection,
            1,
        ).replace("    name: Structured troubleshooting", "    name: *shared", 1)
    else:
        text = text.replace("    name: API and integration architecture", injection, 1)
    skills.write_text(text, encoding="utf-8")

    with pytest.raises(ConfigError, match=message):
        load_config_bundle(fixture_dir)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ("nested: " + "[" * 80 + "0" + "]" * 80, "maximum depth"),
        ("nodes: [" + "0," * 25000 + "]", "node limit"),
    ],
)
def test_yaml_complexity_is_bounded(tmp_path: Path, payload: str, message: str) -> None:
    fixture_dir = tmp_path / "config"
    shutil.copytree(CONFIG_DIR, fixture_dir)
    skills = fixture_dir / "tam-skills.yaml"
    skills.write_text(
        skills.read_text(encoding="utf-8") + f"\n{payload}\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match=message):
        load_config_bundle(fixture_dir)


@pytest.mark.parametrize("value", [".nan", ".inf", "-.inf"])
def test_nonfinite_decimal_is_a_source_located_config_error(
    tmp_path: Path, value: str
) -> None:
    fixture_dir = tmp_path / "config"
    shutil.copytree(CONFIG_DIR, fixture_dir)
    mapping = fixture_dir / "tam-exercise-types.yaml"
    text = mapping.read_text(encoding="utf-8")
    mapping.write_text(text.replace("weight: 0.35", f"weight: {value}", 1), encoding="utf-8")
    with pytest.raises(
        ConfigError,
        match=r"tam-exercise-types\.yaml:\d+:\d+.*finite decimal",
    ):
        load_config_bundle(fixture_dir)


@pytest.mark.parametrize(
    ("filename", "old", "new", "message"),
    [
        (
            "tam-skills.yaml",
            "name: API and integration architecture",
            "name: '   '",
            "must not be blank",
        ),
        (
            "tam-skills.yaml",
            "name: API and integration architecture",
            "name: '" + "é" * 65 + "'",
            "UTF-8 bytes",
        ),
        (
            "tam-rubrics.yaml",
            "    scale_min: 0\n    scale_max: 20",
            "    scale_min: 20\n    scale_max: 20",
            "scale maximum must be greater",
        ),
        (
            "tam-rubrics.yaml",
            "  performance_scale_min: 0\n  performance_scale_max: 4",
            "  performance_scale_min: 4\n  performance_scale_max: 4",
            "performance scale maximum must be greater",
        ),
    ],
)
def test_dry_run_mirrors_database_text_and_scale_constraints(
    tmp_path: Path, filename: str, old: str, new: str, message: str
) -> None:
    fixture_dir = tmp_path / "config"
    shutil.copytree(CONFIG_DIR, fixture_dir)
    target = fixture_dir / filename
    text = target.read_text(encoding="utf-8")
    assert old in text
    target.write_text(text.replace(old, new, 1), encoding="utf-8")
    with pytest.raises(ConfigError, match=message):
        load_config_bundle(fixture_dir)
